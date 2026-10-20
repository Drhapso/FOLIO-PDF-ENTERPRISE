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

    def editor_bundle(self, source, change):
        response = self.call("edit_text_pro", {
            "changes": [change], "editor_preview": True, "page": 1,
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


if __name__ == "__main__":
    unittest.main()
