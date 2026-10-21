from __future__ import annotations

import io
import base64
import json
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

import pymupdf as pdf

from server import CLIENT_BUILD, create_app


def create_sample_pdf() -> bytes:
    with pdf.open() as doc:
        page = doc.new_page(width=612, height=792)  # Carta
        page.insert_text((50, 80), "Encabezado Original de Prueba", fontsize=18, fontname="hebo")
        page.insert_text((50, 130), "Parrafo que sera modificado con estilo Acrobat.", fontsize=12, fontname="helv")
        page.insert_text((50, 180), "Linea que sera eliminada completamente.", fontsize=12, fontname="tiro")
        page.insert_text((50, 230), "Reporte de TerminoClave para busqueda.", fontsize=12, fontname="helv")
        return doc.tobytes()


class AcrobatEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="folio-acrobat-test-")
        cls.root = Path(cls.temporary.name)
        cls.app = create_app(cls.root)
        cls.app.testing = True
        cls.client = cls.app.test_client()
        cls.headers = {"Origin": "http://localhost", "X-PDF-Client": CLIENT_BUILD}
        cls.sample = create_sample_pdf()

    @classmethod
    def tearDownClass(cls):
        cls.app.extensions["instance_lock"].close()
        cls.temporary.cleanup()

    def call(self, operation: str, options: dict = None, uploads: list = None, expected: int = 200):
        uploads = uploads if uploads is not None else [(self.sample, "muestra.pdf")]
        response = self.client.post(
            "/api/process/" + operation,
            headers=self.headers,
            data={
                "options": json.dumps(options or {}),
                "files": [(io.BytesIO(data), name) for data, name in uploads],
            },
        )
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, expected)
        return response

    def test_inspect_extracts_blocks(self):
        response = self.call("inspect", {"page": 1})
        data = response.json
        self.assertIn("blocks", data)
        self.assertGreaterEqual(len(data["blocks"]), 3)
        texts = [b["text"] for b in data["blocks"]]
        self.assertTrue(any("Encabezado Original" in t for t in texts))
        self.assertTrue(any("Parrafo que sera modificado" in t for t in texts))
        first = data["blocks"][0]
        self.assertIn("bbox", first)
        self.assertIn("size", first)
        self.assertIn("color", first)

    def test_acrobat_modify_and_add_text(self):
        # 1. Inspect first to get exact block bbox
        inspect_res = self.call("inspect", {"page": 1}).json
        blocks = inspect_res["blocks"]
        target_block = next(b for b in blocks if "modificado" in b["text"])

        changes = [
            {
                "action": "modify",
                "page": 1,
                "orig_bbox": target_block["bbox"],
                "bbox": [50, 130, 450, 165],
                "text": "Parrafo editado con nuevo texto y formato.",
                "font": "Arial",
                "size": 13,
                "color": "#0055aa",
                "bold": True,
                "align": "left",
            },
            {
                "action": "add",
                "page": 1,
                "bbox": [50, 300, 400, 340],
                "text": "Bloque nuevo agregado al final de la pagina.",
                "font": "Times New Roman",
                "size": 14,
                "color": "#118822",
                "bold": False,
                "italic": True,
                "align": "center",
            },
        ]

        response = self.call("edit_text_pro", {"changes": changes})
        self.assertEqual(response.status_code, 200)

        # Verificar el documento resultante
        with pdf.open(stream=response.data, filetype="pdf") as res_doc:
            text = res_doc[0].get_text()
            self.assertIn("Parrafo editado con nuevo texto y formato.", text)
            self.assertIn("Bloque nuevo agregado al final", text)
            # El texto original modificado no debe aparecer
            self.assertNotIn("Parrafo que sera modificado con estilo Acrobat.", text)

    def test_acrobat_delete_text(self):
        inspect_res = self.call("inspect", {"page": 1}).json
        target_block = next(b for b in inspect_res["blocks"] if "eliminada" in b["text"])

        changes = [
            {
                "action": "delete",
                "page": 1,
                "orig_bbox": target_block["bbox"],
            }
        ]
        response = self.call("edit_text_pro", {"changes": changes})
        self.assertEqual(response.status_code, 200)

        with pdf.open(stream=response.data, filetype="pdf") as res_doc:
            text = res_doc[0].get_text()
            self.assertNotIn("Linea que sera eliminada", text)
            # Otros textos deben permanecer
            self.assertIn("Encabezado Original", text)

    def editor_bundle(self, source, change, *, experimental=False):
        response = self.call("edit_text_pro", {
            "changes": [change], "editor_preview": True, "page": 1,
            "experimental_preview": experimental,
        }, uploads=[(source, "edicion.pdf")])
        body = response.get_data()
        self.assertEqual(response.mimetype, "multipart/form-data")
        message = BytesParser(policy=policy.default).parsebytes(
            f'Content-Type: {response.content_type}\r\nMIME-Version: 1.0\r\n\r\n'.encode() + body
        )
        parts = {part.get_param("name", header="content-disposition"): part
                 for part in message.iter_parts()}
        self.assertEqual(set(parts), {"document", "preview"})
        self.assertEqual(parts["document"].get_content_type(), "application/pdf")
        document = parts["document"].get_payload(decode=True)
        preview = json.loads(parts["preview"].get_payload(decode=True))
        self.assertTrue(base64.b64decode(preview["background"]).startswith(b"\x89PNG"))
        self.assertEqual(preview["page"], 1)
        self.assertEqual(preview["dpi"], 130)
        self.assertEqual(list((self.root / "runtime").glob("job-*")), [])
        response.close()
        return document, preview

    def test_live_preview_matches_saved_document_across_edits(self):
        source, _ = self.background_sample()
        with patch.dict(self.app.extensions["pdf_settings"], editor_live_preview=True):
            target = next(block for block in self.call(
                "inspect", uploads=[(source, "color.pdf")]
            ).json["blocks"] if block["text"] == "TEXTO ORIGINAL")
            change = {"action": "modify", "page": 1, "orig_bbox": target["bbox"],
                      "bbox": target["bbox"], "text": "NUEVO", "size": target["size"],
                      "font": target["font"], "bold": True}
            document, preview = self.editor_bundle(source, change, experimental=True)
            reopened = self.call("inspect", {
                "page": 1, "dpi": 130, "text_background": True,
            }, uploads=[(document, "resultado.pdf")]).json
            self.assertEqual(preview, reopened)
            target = next(block for block in preview["blocks"] if block["text"] == "NUEVO")
            document, preview = self.editor_bundle(document, {
                "action": "delete", "page": 1, "orig_bbox": target["bbox"],
            }, experimental=True)
            with pdf.open(stream=document, filetype="pdf") as edited:
                self.assertNotIn("NUEVO", edited[0].get_text())
                self.assertNotIn("ORIGINAL", edited[0].get_text())
                self.assertIn("VECINO", edited[0].get_text())
            reopened = self.call("inspect", {
                "page": 1, "dpi": 130, "text_background": True,
            }, uploads=[(document, "resultado.pdf")]).json
            self.assertEqual(preview, reopened)

    def test_live_preview_requires_server_flag_and_request_opt_in(self):
        from acrobat_tools import process_acrobat
        from pdf_engine import process

        change = {"action": "add", "page": 1, "bbox": [50, 300, 400, 340],
                  "text": "PRUEBA", "size": 12}
        for enabled, requested in ((False, True), (True, False), (True, True)):
            with self.subTest(enabled=enabled, requested=requested):
                with tempfile.TemporaryDirectory() as directory:
                    folder = Path(directory)
                    source = folder / "entrada.pdf"
                    source.write_bytes(self.sample)
                    config = dict(self.app.extensions["pdf_settings"], editor_live_preview=enabled)
                    with patch("pdf_engine.process", wraps=process) as inspect_call:
                        process_acrobat("edit_text_pro", [source], {
                            "changes": [change], "editor_preview": True,
                            "experimental_preview": requested,
                        }, folder, config)
                    self.assertEqual(inspect_call.call_count, 0 if enabled and requested else 1)

    def test_live_preview_streaming_cleanup(self):
        with patch.dict(self.app.extensions["pdf_settings"], editor_live_preview=True):
            with patch("server.INLINE_RESULT_BYTES", 1):
                self.editor_bundle(self.sample, {
                    "action": "add", "page": 1, "bbox": [50, 300, 400, 340],
                    "text": "PRUEBA", "size": 12,
                }, experimental=True)
        self.assertEqual(list((self.root / "runtime" / "outgoing").iterdir()), [])

    def test_save_returns_updated_pdf_and_preview_for_next_edit(self):
        change = {"action": "add", "page": 1, "bbox": [50, 300, 400, 340],
                  "text": "PRIMER CAMBIO", "font": "Arial", "size": 12}
        document, preview = self.editor_bundle(self.sample, change)
        target = next(block for block in preview["blocks"] if block["text"] == "PRIMER CAMBIO")
        change = {"action": "modify", "page": 1, "orig_bbox": target["bbox"], "bbox": target["bbox"],
                  "text": "SEGUNDO", "font": target["font"], "size": target["size"]}
        document, preview = self.editor_bundle(document, change)
        with pdf.open(stream=document, filetype="pdf") as edited:
            self.assertIn("SEGUNDO", edited[0].get_text())
            self.assertNotIn("PRIMER CAMBIO", edited[0].get_text())
            self.assertIn("Encabezado Original", edited[0].get_text())
        self.assertTrue(any(block["text"] == "SEGUNDO" for block in preview["blocks"]))

    def test_editor_bundle_streaming_cleans_delivery_file(self):
        change = {"action": "add", "page": 1, "bbox": [50, 300, 400, 340],
                  "text": "TRANSMISION", "font": "Arial", "size": 12}
        with patch("server.INLINE_RESULT_BYTES", 1):
            document, preview = self.editor_bundle(self.sample, change)
        self.assertTrue(document.startswith(b"%PDF"))
        self.assertEqual(list((self.root / "runtime" / "outgoing").iterdir()), [])

    def test_acrobat_replace_all(self):
        changes = [
            {
                "action": "replace_all",
                "find": "TerminoClave",
                "replace": "PalabraActualizada",
            }
        ]
        response = self.call("edit_text_pro", {"changes": changes})
        self.assertEqual(response.status_code, 200)

        with pdf.open(stream=response.data, filetype="pdf") as res_doc:
            text = res_doc[0].get_text()
            self.assertIn("PalabraActualizada", text)
            self.assertNotIn("TerminoClave", text)

    def background_sample(self):
        with pdf.open() as doc:
            page = doc.new_page(width=400, height=250)
            page.draw_rect(pdf.Rect(20, 20, 380, 220), color=None, fill=(0.65, 0.75, 0.85))
            image = pdf.Pixmap(pdf.csRGB, pdf.IRect(0, 0, 60, 60))
            image.clear_with(100)
            page.insert_image(pdf.Rect(45, 45, 105, 105), pixmap=image)
            page.draw_line((30, 72), (360, 72), color=(1, 0, 0), width=1)
            background = doc.tobytes()
            page.insert_text((50, 80), "TEXTO ORIGINAL", fontsize=16, fontname="hebo")
            page.insert_text((200, 80), "VECINO", fontsize=16)
            return doc.tobytes(), background

    def test_delete_preserves_background_images_and_lines(self):
        source, background = self.background_sample()
        data = self.call("inspect", uploads=[(source, "color.pdf")]).json
        target = next(block for block in data["blocks"] if block["text"] == "TEXTO ORIGINAL")
        result = self.call("edit_text_pro", {"changes": [
            {"action": "delete", "page": 1, "orig_bbox": target["bbox"]},
        ]}, uploads=[(source, "color.pdf")])
        with pdf.open(stream=background, filetype="pdf") as expected, pdf.open(stream=result.data, filetype="pdf") as actual:
            # El vecino no pertenece al fragmento eliminado.
            expected[0].insert_text((200, 80), "VECINO", fontsize=16)
            self.assertEqual(actual[0].get_pixmap().samples, expected[0].get_pixmap().samples)
            self.assertIn("VECINO", actual[0].get_text())
            self.assertNotIn("ORIGINAL", actual[0].get_text())

    def test_inspect_real_background_and_font_flags(self):
        source, background = self.background_sample()
        data = self.call("inspect", {"text_background": True}, uploads=[(source, "color.pdf")]).json
        self.assertEqual(data["image_mime"], "image/png")
        self.assertTrue(base64.b64decode(data["image"]).startswith(b"\x89PNG"))
        actual = pdf.Pixmap(base64.b64decode(data["background"]))
        with pdf.open(stream=background, filetype="pdf") as expected:
            self.assertEqual(actual.samples, expected[0].get_pixmap(dpi=90).samples)
        target = next(block for block in data["blocks"] if block["text"] == "TEXTO ORIGINAL")
        neighbor = next(block for block in data["blocks"] if block["text"] == "VECINO")
        self.assertTrue(target["bold"])
        self.assertFalse(target["italic"])
        self.assertFalse(neighbor["bold"])
        self.assertFalse(neighbor["italic"])

    def test_modify_preserves_baseline_and_rejects_overflow(self):
        data = self.call("inspect").json
        target = next(block for block in data["blocks"] if "Encabezado" in block["text"])
        change = {"action": "modify", "page": 1, "orig_bbox": target["bbox"], "bbox": target["bbox"],
                  "text": "NUEVO", "size": target["size"], "font": target["font"], "bold": target["bold"]}
        result = self.call("edit_text_pro", {"changes": [change]})
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            spans = [span for block in doc[0].get_text("dict")["blocks"] if block["type"] == 0
                     for line in block["lines"] for span in line["spans"]]
            inserted = next(span for span in spans if span["text"] == "NUEVO")
            self.assertAlmostEqual(inserted["origin"][1], target["origin"][1], places=2)
            self.assertNotIn("Encabezado Original", doc[0].get_text())
        change["text"] = "TEXTO DEMASIADO LARGO " * 30
        self.call("edit_text_pro", {"changes": [change]}, expected=422)

    def test_both_edit_routes_replace_without_ghost_text_on_real_background(self):
        source, background = self.background_sample()
        data = self.call("inspect", uploads=[(source, "color.pdf")]).json
        target = next(block for block in data["blocks"] if block["text"] == "TEXTO ORIGINAL")
        change = {"action": "modify", "page": 1, "orig_bbox": target["bbox"],
                  "bbox": target["bbox"], "text": "NUEVO", "size": 16, "bold": True}
        with pdf.open(stream=background, filetype="pdf") as expected:
            expected[0].insert_text((200, 80), "VECINO", fontsize=16)
            expected[0].insert_text((50, 80), "NUEVO", fontsize=16, fontname="hebo")
            expected_pixels = expected[0].get_pixmap().samples
        for operation in ("edit", "edit_text_pro"):
            with self.subTest(operation=operation):
                result = self.call(operation, {"changes": [change]}, uploads=[(source, "color.pdf")])
                with pdf.open(stream=result.data, filetype="pdf") as actual:
                    self.assertEqual(actual[0].get_pixmap().samples, expected_pixels)
                    self.assertNotIn("ORIGINAL", actual[0].get_text())
                    self.assertIn("VECINO", actual[0].get_text())

    def test_legacy_text_boxes_replace_instead_of_overlay(self):
        target = self.call("inspect").json["blocks"][0]
        x0, y0, x1, y1 = target["bbox"]
        edit = {"kind": "text", "page": 1, "x": (x0 - 1) / 612, "y": (y0 - 1) / 792,
                "w": (x1 - x0 + 2) / 612, "h": (y1 - y0 + 10) / 792, "text": "NUEVO", "size": 12}
        for operation in ("edit", "edit_text_pro"):
            with self.subTest(operation=operation):
                result = self.call(operation, {"edits": [edit]})
                with pdf.open(stream=result.data, filetype="pdf") as doc:
                    self.assertNotIn("Encabezado Original", doc[0].get_text())
                    self.assertIn("NUEVO", doc[0].get_text())
                    self.assertIn("Parrafo", doc[0].get_text())
        edit["w"] /= 2
        self.call("edit", {"edits": [edit]}, expected=422)

    def test_unified_annotations_and_redaction(self):
        target = self.call("inspect").json["blocks"][0]
        for operation in ("edit", "edit_text_pro"):
            with self.subTest(operation=operation):
                result = self.call(operation, {"changes": [
                    {"action": "highlight", "page": 1, "bbox": [40, 110, 400, 140]},
                    {"action": "rectangle", "page": 1, "bbox": [40, 160, 400, 190]},
                    {"action": "note", "page": 1, "bbox": [450, 300, 500, 350], "text": "NOTA"},
                    {"action": "redact", "page": 1, "bbox": target["bbox"]},
                ]})
                with pdf.open(stream=result.data, filetype="pdf") as doc:
                    self.assertNotIn("Encabezado Original", doc[0].get_text())
                    self.assertIn("Parrafo", doc[0].get_text())
                    self.assertEqual(len(list(doc[0].annots())), 3)
                    self.assertEqual(doc[0].get_pixmap().pixel(55, 75), (0, 0, 0))

    def test_redaction_removes_text_inserted_in_same_request(self):
        for operation in ("edit", "edit_text_pro"):
            result = self.call(operation, {"changes": [
                {"action": "redact", "page": 1, "bbox": [40, 300, 400, 360]},
                {"action": "add", "page": 1, "bbox": [50, 310, 350, 350], "text": "SENSIBLE"},
            ]})
            with pdf.open(stream=result.data, filetype="pdf") as doc:
                self.assertNotIn("SENSIBLE", doc[0].get_text())

    def test_unified_redaction_removes_images_metadata_and_attachments(self):
        source, _ = self.background_sample()
        with pdf.open(stream=source, filetype="pdf") as doc:
            doc.set_metadata({"author": "SENSIBLE"})
            doc.embfile_add("original.txt", b"SENSIBLE")
            source = doc.tobytes()
        for operation in ("edit", "edit_text_pro"):
            result = self.call(operation, {"changes": [
                {"action": "redact", "page": 1, "bbox": [40, 40, 190, 110]},
            ]}, uploads=[(source, "color.pdf")])
            with pdf.open(stream=result.data, filetype="pdf") as doc:
                self.assertNotIn("ORIGINAL", doc[0].get_text())
                self.assertIn("VECINO", doc[0].get_text())
                self.assertEqual(doc[0].get_pixmap().pixel(60, 60), (0, 0, 0))
                self.assertEqual(doc.embfile_count(), 0)
                self.assertFalse(doc.metadata["author"])
                self.assertFalse(doc.get_xml_metadata())

    def test_invalid_changes_cannot_fall_back_to_overlay(self):
        for operation in ("edit", "edit_text_pro"):
            for change in (
                {"action": "modify", "bbox": [50, 50, 200, 100], "text": "NUEVO"},
                {"action": "add", "page": 20, "bbox": [50, 50, 200, 100], "text": "NUEVO"},
                {"action": "note", "bbox": [50, 50, 200, 100], "text": ""},
                {"action": "redact", "bbox": [-1, 50, 200, 100]},
                {"action": "unknown", "bbox": [50, 50, 200, 100]},
            ):
                with self.subTest(operation=operation, change=change):
                    self.call(operation, {"changes": [change]}, expected=422)
            self.call(operation, {"changes": [], "edits": []}, expected=422)

    def test_legacy_route_supports_editor_bundle(self):
        result = self.call("edit", {"changes": [
            {"action": "add", "page": 1, "bbox": [50, 300, 300, 350], "text": "UNIFICADO"},
        ], "editor_preview": True})
        self.assertTrue(result.content_type.startswith("multipart/form-data; boundary="))
        message = BytesParser(policy=policy.default).parsebytes(
            ("Content-Type: " + result.content_type + "\r\n\r\n").encode("ascii") + result.data)
        parts = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                 for part in message.iter_parts()}
        with pdf.open(stream=parts["document"], filetype="pdf") as doc:
            self.assertIn("UNIFICADO", doc[0].get_text())
        self.assertTrue(any(block["text"] == "UNIFICADO" for block in json.loads(parts["preview"])["blocks"]))

    def test_single_editor_controls_and_legacy_controls_removed(self):
        page = self.client.get("/editor")
        self.assertEqual(page.status_code, 200)
        for control in (b"acro-region-tool", b"acro-note-text", b"acro-region-add", b"acro-region-list"):
            self.assertIn(control, page.data)
        index = self.client.get("/")
        self.assertNotIn(b'id="edit-kind"', index.data)
        self.assertNotIn(b'id="edit-text"', index.data)

    def scanned_sample(self, hidden_ocr=False):
        with pdf.open() as native:
            page = native.new_page(width=400, height=200)
            page.insert_text((40, 70), "ORIGINAL", fontsize=18)
            page.insert_text((230, 140), "VECINO", fontsize=18)
            image = page.get_pixmap(dpi=216).tobytes("png")
        with pdf.open() as scanned:
            page = scanned.new_page(width=400, height=200)
            page.insert_image(page.rect, stream=image)
            if hidden_ocr:
                page.insert_text((40, 70), "ORIGINAL", fontsize=18, render_mode=3)
            return scanned.tobytes()

    def test_scan_replacement_removes_original_pixels_and_preserves_outside(self):
        import numpy as np
        for hidden, mixed in ((False, False), (True, False), (True, True)):
            with self.subTest(hidden_ocr=hidden, native_text=mixed):
                source = self.scanned_sample(hidden)
                if mixed:
                    with pdf.open(stream=source, filetype="pdf") as doc:
                        doc[0].insert_text((220, 50), "NATIVE", fontsize=12)
                        source = doc.tobytes()
                data = self.call("inspect", {"text_background": True},
                                 uploads=[(source, "scan.pdf")]).json
                target = next(block for block in data["blocks"] if block["text"] == "ORIGINAL")
                self.assertTrue(target["editable"])
                result = self.call("edit_text_pro", {"changes": [{
                    "action": "modify", "page": 1, "orig_bbox": target["bbox"],
                    "bbox": target["bbox"], "text": "NEW", "size": 12,
                }]}, uploads=[(source, "scan.pdf")])
                with pdf.open(stream=source, filetype="pdf") as before, pdf.open(stream=result.data, filetype="pdf") as after:
                    self.assertIn("NEW", after[0].get_text())
                    self.assertNotIn("ORIGINAL", after[0].get_text())
                    if mixed:
                        self.assertIn("NATIVE", after[0].get_text())
                    a = before[0].get_pixmap(dpi=216)
                    b = after[0].get_pixmap(dpi=216)
                    old = np.frombuffer(a.samples, dtype=np.uint8).reshape(a.height, a.width, 3)
                    new = np.frombuffer(b.samples, dtype=np.uint8).reshape(b.height, b.width, 3)
                    outside = np.ones((a.height, a.width), dtype=bool)
                    rect = (pdf.Rect(target["bbox"]) + (-2, -2, 2, 2)) * 3
                    outside[int(rect.y0):int(rect.y1) + 1, int(rect.x0):int(rect.x1) + 1] = False
                    self.assertTrue(np.array_equal(old[outside], new[outside]))
                    page = after[0]
                    page.add_redact_annot(pdf.Rect(target["bbox"]), fill=False, cross_out=False)
                    page.apply_redactions(images=0, graphics=0, text=pdf.PDF_REDACT_TEXT_REMOVE)
                    clean = page.get_pixmap(dpi=216, clip=pdf.Rect(target["bbox"]))
                    pixels = np.frombuffer(clean.samples, dtype=np.uint8)
                    self.assertGreater(float(np.mean(pixels)), 250)
                    self.assertLess(np.count_nonzero(pixels < 220) / pixels.size, 0.01)

    def test_scan_complex_region_rejected_without_modifying_source(self):
        from scan_editor import clean_scan_patch
        from pdf_engine import ProcessingError
        with pdf.open() as doc:
            page = doc.new_page(width=300, height=150)
            page.insert_text((50, 80), "ORIGINAL", fontsize=16)
            page.draw_line((40, 70), (160, 70), width=1)
            before = page.get_pixmap().samples
            with self.assertRaises(ProcessingError):
                clean_scan_patch(page, [40, 55, 160, 90], self.app.extensions["pdf_settings"])
            self.assertEqual(before, page.get_pixmap().samples)

    def test_scan_global_replace_rejected(self):
        self.call("edit_text_pro", {"changes": [{
            "action": "replace_all", "find": "ORIGINAL", "replace": "NEW",
        }]}, uploads=[(self.scanned_sample(), "scan.pdf")], expected=422)


if __name__ == "__main__":
    unittest.main()
