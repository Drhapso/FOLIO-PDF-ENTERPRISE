from __future__ import annotations

import io
import json
import unittest
import zipfile

import pikepdf
import pymupdf as pdf
from PIL import Image

import test_platform as base
from test_platform import sample_pdf


class ExtendedTests(unittest.TestCase):
    setUpClass = classmethod(base.PlatformTests.setUpClass.__func__)
    tearDownClass = classmethod(base.PlatformTests.tearDownClass.__func__)
    tearDown = base.PlatformTests.tearDown
    call = base.PlatformTests.call

    def test_extract_and_delete(self):
        for operation, pages, expected in (("extract_pages", "3,1", 2), ("delete_pages", "2", 2)):
            with self.subTest(operation=operation):
                result = self.call(operation, {"pages": pages})
                with pdf.open(stream=result.data, filetype="pdf") as doc:
                    self.assertEqual(len(doc), expected)
                    self.assertNotIn("PRUEBA 2", "".join(p.get_text() for p in doc))
        self.call("delete_pages", expected=422)
        self.call("delete_pages", {"pages": "1-3"}, expected=422)

    def test_numbering(self):
        result = self.call("number_pages", {"pages": "2,3", "start": "7", "position": "top"})
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertNotIn("7 / 8", doc[0].get_text())
            self.assertIn("7 / 8", doc[1].get_text())
            self.assertIn("8 / 8", doc[2].get_text())
        self.call("number_pages", {"position": "elsewhere"}, expected=422)

    def test_embedded_images_and_mask(self):
        image = Image.new("RGBA", (120, 80), (200, 10, 20, 120))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        with pdf.open() as doc:
            page = doc.new_page()
            page.insert_image(pdf.Rect(10, 10, 130, 90), stream=buffer.getvalue())
            source = doc.tobytes()
        result = self.call("extract_images", uploads=[(source, "image.pdf")])
        with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
            self.assertEqual(len(archive.namelist()), 1)
            with Image.open(io.BytesIO(archive.read(archive.namelist()[0]))) as extracted:
                self.assertEqual(extracted.size, (120, 80))
                self.assertIn("A", extracted.mode)
        self.call("extract_images", expected=422)

    def test_crop_visual_only(self):
        result = self.call("crop", {"pages": "1", "x": "10", "y": "10", "width": "80", "height": "80"})
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertAlmostEqual(doc[0].rect.width, 595 * .8, places=1)
            self.assertEqual(doc[1].rect.width, 595)
            self.assertIn("Recorte visual", result.headers["X-PDF-Notice"])
        self.call("crop", {"x": "90", "width": "50"}, expected=422)

    def test_resize_and_nup(self):
        result = self.call("resize", {"paper": "letter"})
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertEqual(len(doc), 3)
            self.assertEqual(doc[0].rect.width, 612)
            self.assertIn("SECRETO", doc[0].get_text())
        result = self.call("nup", {"per_sheet": "4"})
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertEqual(len(doc), 1)
            for n in (1, 2, 3):
                self.assertIn(f"PRUEBA {n}", doc[0].get_text())
        self.call("nup", {"per_sheet": "3"}, expected=422)

    def test_overlay(self):
        with pdf.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 300), "MEMBRETE LOCAL")
            template = doc.tobytes()
        result = self.call("overlay", uploads=[(self.original, "a.pdf"), (template, "b.pdf")])
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertTrue(all("MEMBRETE" in page.get_text() for page in doc))
            self.assertIn("SECRETO", doc[0].get_text())
        self.call("overlay", expected=422)

    def test_compare_appearance_and_text(self):
        result = self.call("compare", uploads=[(self.original, "a.pdf"), (sample_pdf(1), "b.pdf")])
        with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
            self.assertEqual(len([name for name in archive.namelist() if name.endswith(".pdf")]), 1)
            diffs = [name for name in archive.namelist() if name.endswith(".diff")]
            images = [name for name in archive.namelist() if name.endswith(".png")]
            self.assertIn("PRUEBA 2", archive.read(diffs[1]).decode())
            with Image.open(io.BytesIO(archive.read(images[1]))) as image:
                self.assertIsNotNone(image.getbbox())
        result = self.call("compare", uploads=[(self.original, "a.pdf"), (self.original, "b.pdf")])
        with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
            image_name = next(name for name in archive.namelist() if name.endswith(".png"))
            with Image.open(io.BytesIO(archive.read(image_name))) as image:
                self.assertIsNone(image.getbbox())

    def test_metadata(self):
        with pdf.open(stream=self.original, filetype="pdf") as doc:
            doc.set_metadata({"author": "PRIVATE AUTHOR", "title": "PRIVATE TITLE"})
            doc.set_xml_metadata("<root>PRIVATE XML</root>")
            source = doc.tobytes()
        result = self.call("remove_metadata", uploads=[(source, "meta.pdf")])
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertFalse(doc.metadata["author"])
            self.assertFalse(doc.get_xml_metadata())
            self.assertIn("SECRETO", doc[0].get_text())

    def test_grayscale_and_rasterize(self):
        for operation in ("grayscale", "rasterize"):
            with self.subTest(operation=operation):
                result = self.call(operation, {"pages": "2", "dpi": "72"})
                with pdf.open(stream=result.data, filetype="pdf") as doc:
                    self.assertEqual(len(doc), 1)
                    self.assertFalse(doc[0].get_text().strip())
                    self.assertTrue(doc[0].get_images())
                    if operation == "grayscale":
                        pix = pdf.Pixmap(doc, doc[0].get_images()[0][0])
                        self.assertEqual(pix.colorspace.n, 1)

    def test_annotations_and_flatten(self):
        result = self.call("edit", {"edits": [
            {"kind": kind, "page": 1, "x": .1, "y": .1 + n * .1, "w": .3, "h": .05,
             "text": "NOTA LOCAL", "size": 12}
            for n, kind in enumerate(("highlight", "rectangle", "note"))
        ]})
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertEqual(len(list(doc[0].annots())), 3)
        flat = self.call("flatten", uploads=[(result.data, "annotated.pdf")])
        with pdf.open(stream=flat.data, filetype="pdf") as doc:
            self.assertFalse(list(doc[0].annots() or []))
            self.assertIn("SECRETO", doc[0].get_text())

    def test_qpdf_repair_and_linearize(self):
        for operation in ("repair", "web_optimize"):
            with self.subTest(operation=operation):
                result = self.call(operation)
                with pikepdf.open(io.BytesIO(result.data)) as doc:
                    self.assertFalse(doc.check_pdf_syntax())
                    self.assertEqual(len(doc.pages), 3)
                    if operation == "web_optimize":
                        self.assertTrue(doc.is_linearized)
        self.call("repair", uploads=[(b"not a pdf", "bad.pdf")], expected=422)

    def test_blank_report_and_confirmed_delete(self):
        with pdf.open(stream=sample_pdf(1), filetype="pdf") as doc:
            doc.new_page()
            source = doc.tobytes()
        result = self.call("blank_report", uploads=[(source, "white.pdf")])
        self.assertEqual(result.json["candidates"], [2])
        result = self.call("remove_blank", {"pages": "2"}, [(source, "white.pdf")])
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertEqual(len(doc), 1)
        self.call("remove_blank", uploads=[(source, "white.pdf")], expected=422)
        self.call("remove_blank", {"pages": "1"}, [(source, "white.pdf")], expected=422)

    def test_form_inspect_fill_and_flatten(self):
        with pdf.open() as doc:
            page = doc.new_page()
            widget = pdf.Widget()
            widget.field_name = "nombre"
            widget.field_type = pdf.PDF_WIDGET_TYPE_TEXT
            widget.rect = pdf.Rect(72, 72, 300, 100)
            page.add_widget(widget)
            source = doc.tobytes()
        result = self.call("form_fields", uploads=[(source, "form.pdf")])
        self.assertEqual(result.json[0]["name"], "nombre")
        result = self.call("fill_form", {"fields": {"nombre": "Ana Local"}}, [(source, "form.pdf")])
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertEqual(next(doc[0].widgets()).field_value, "Ana Local")
        flattened = self.call("flatten", uploads=[(result.data, "filled.pdf")])
        with pdf.open(stream=flattened.data, filetype="pdf") as doc:
            self.assertFalse(list(doc[0].widgets() or []))
            self.assertIn("Ana Local", doc[0].get_text())
        self.call("fill_form", {"fields": {"missing": "value"}}, [(source, "form.pdf")], expected=422)
        self.call("form_fields", expected=422)

    def test_dossier(self):
        result = self.call("dossier", {"text": "EXPEDIENTE LOCAL"},
                           [(sample_pdf(1), "one.pdf"), (self.original, "two.pdf")])
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertEqual(len(doc), 5)
            self.assertIn("EXPEDIENTE LOCAL", doc[0].get_text())

    def test_dossier_multiple_files_quota(self):
        caps = self.client.get("/api/capabilities").json
        self.assertIn("dossier", caps["bulk_operations"])
        self.assertEqual(caps["max_upload_mb"], 1024)
        sources = [sample_pdf(1) for _ in range(12)]
        uploads = [(source, f"anexo-{index}.pdf") for index, source in enumerate(sources)]
        original_total = self.config["max_upload_mb"]
        original_count = self.config["max_batch_files"]
        try:
            # Cuota reducida para probar el limite exacto sin cargar 1 GB.
            self.config["max_upload_mb"] = sum(map(len, sources)) / (1024 * 1024)
            result = self.call("dossier", {"text": "EXPEDIENTE MULTIPLE"}, uploads)
            with pdf.open(stream=result.data, filetype="pdf") as doc:
                self.assertEqual(len(doc), 13)
                self.assertIn("EXPEDIENTE MULTIPLE", doc[0].get_text())
            self.config["max_upload_mb"] -= 1 / (1024 * 1024)
            rejected = self.call("dossier", uploads=uploads, expected=413)
            self.assertIn("peso conjunto", rejected.json["error"])
            self.config["max_upload_mb"] = original_total
            self.config["max_batch_files"] = 6
            self.call("dossier", uploads=uploads, expected=400)
        finally:
            self.config["max_upload_mb"] = original_total
            self.config["max_batch_files"] = original_count

    def test_dossier_optional_cover(self):
        uploads = [(sample_pdf(1), "one.pdf"), (sample_pdf(2), "two.pdf")]
        for include_cover in (True, False):
            with self.subTest(include_cover=include_cover):
                result = self.call("dossier", {"include_cover": include_cover}, uploads)
                with pdf.open(stream=result.data, filetype="pdf") as doc:
                    self.assertEqual(len(doc), 3 + int(include_cover))
                    if include_cover:
                        self.assertIn("Expediente documental", doc[0].get_text())
                    self.assertIn("PRUEBA 1", doc[int(include_cover)].get_text())
                    self.assertIn("PRUEBA 2", doc[-1].get_text())
        self.call("dossier", {"include_cover": False, "text": ""}, uploads)
        self.call("dossier", {"include_cover": True, "text": ""}, uploads, expected=422)
        for invalid in ("false", 0, None):
            self.call("dossier", {"include_cover": invalid}, uploads, expected=422)
        previous = self.config["max_pages"]
        try:
            self.config["max_pages"] = 3
            self.call("dossier", {"include_cover": False}, uploads)
            self.call("dossier", {"include_cover": True}, uploads, expected=422)
        finally:
            self.config["max_pages"] = previous

    def test_dossier_over_previous_page_limits(self):
        self.assertEqual(self.config["max_pages"], 0)
        self.assertEqual(self.config["max_batch_pages"], 0)
        source = sample_pdf(201)
        uploads = [(source, f"anexo-{index}.pdf") for index in range(26)]
        for operation, extra in (("dossier", 1), ("merge", 0)):
            with self.subTest(operation=operation):
                result = self.call(operation, uploads=uploads)
                with pdf.open(stream=result.data, filetype="pdf") as doc:
                    self.assertEqual(len(doc), 5226 + extra)
        result = self.call("split", uploads=[(source, "grande.pdf")])
        with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
            self.assertEqual(len(archive.namelist()), 201)

    def test_stamp_visual(self):
        image = Image.new("RGB", (120, 60), "red")
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        result = self.call("stamp", {"pages": "2", "x": 10, "y": 50, "width": 30, "height": 10},
                           [(self.original, "source.pdf"), (buffer.getvalue(), "sign.png")])
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertFalse(doc[0].get_images())
            self.assertTrue(doc[1].get_images())
        self.assertIn("no firma digital", result.headers["X-PDF-Notice"])
        self.call("stamp", expected=422)

    def test_jpeg_and_tiff_export(self):
        for format_name in ("jpg", "tiff"):
            with self.subTest(format=format_name):
                result = self.call("pdf_to_images", {"pages": "1", "dpi": 72, "image_format": format_name})
                with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
                    image_name = archive.namelist()[0]
                    self.assertTrue(image_name.endswith("." + format_name))
                    with Image.open(io.BytesIO(archive.read(image_name))) as image:
                        self.assertEqual(image.width, 595)

    def test_bad_box_and_limits(self):
        for value in ("nan", "inf", "bad", True):
            self.call("crop", {"width": value}, expected=422)
        self.call("compare", uploads=[(self.original, "a.pdf")], expected=422)
        self.call("extract_pages", {"pages": "900"}, expected=422)

    def test_desktop_download_and_permissions(self):
        response = self.client.get("/desktop/download")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"WIA.CommonDialog", response.get_data())
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertIn("camera=(self)", response.headers["Permissions-Policy"])
        finally:
            response.close()

    def test_html_text_only_no_remote_resources(self):
        source = ('<html><style>HIDDEN CSS</style><body><h1>TITULO LOCAL</h1>'
                  '<script>SECRET SCRIPT</script><p>Documento sin red</p>'
                  '<img src="https://invalid.example/no-request"><a href="https://invalid.example">Enlace</a>'
                  '</body></html>').encode()
        result = self.call("html_to_pdf", uploads=[(source, "local.html")])
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            text = "".join(page.get_text() for page in doc)
            self.assertIn("TITULO LOCAL", text)
            self.assertNotIn("SECRET SCRIPT", text)
            self.assertNotIn("HIDDEN CSS", text)
            self.assertFalse(list(doc[0].links()))
        self.call("html_to_pdf", uploads=[(b"<script>only script</script>", "empty.html")], expected=422)

    def test_svg_export(self):
        result = self.call("pdf_to_svg", {"pages": "2"})
        with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
            self.assertEqual(len(archive.namelist()), 1)
            self.assertTrue(archive.namelist()[0].endswith(".svg"))
            self.assertIn(b"<svg", archive.read(archive.namelist()[0]))


if __name__ == "__main__":
    unittest.main()
