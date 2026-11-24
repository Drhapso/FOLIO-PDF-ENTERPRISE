import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
import pymupdf as pdf

from server import create_app, CLIENT_BUILD


class PDFgearEnhancementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="folio-enh-test-")
        cls.root = Path(cls.temporary.name)
        cls.app = create_app(cls.root)
        cls.app.testing = True
        cls.client = cls.app.test_client()
        cls.headers = {"Origin": "http://localhost", "X-PDF-Client": CLIENT_BUILD}

    @classmethod
    def tearDownClass(cls):
        cls.app.extensions["instance_lock"].close()
        cls.temporary.cleanup()

    def test_01_compression_multilevel_preserves_text_and_vectors(self):
        doc = pdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50), "Texto vectorial protegido", fontsize=14)
        # Add high-res image
        img = Image.new("RGB", (1000, 1000), (120, 180, 220))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        page.insert_image(pdf.Rect(50, 100, 500, 500), stream=buf.getvalue())
        src_bytes = doc.tobytes()
        doc.close()

        # Test medium mode
        res_med = self.client.post(
            "/api/process/compress",
            headers=self.headers,
            data={"files": (io.BytesIO(src_bytes), "test.pdf"), "options": json.dumps({"compression": "medium"})},
        )
        self.assertEqual(res_med.status_code, 200)
        self.assertIn("Compresion medium completada", res_med.headers.get("X-PDF-Notice", ""))
        with pdf.open(stream=res_med.data, filetype="pdf") as out_pdf:
            self.assertIn("Texto vectorial protegido", out_pdf[0].get_text())

        # Test low and high modes
        for mode in ("low", "high"):
            res = self.client.post(
                "/api/process/compress",
                headers=self.headers,
                data={"files": (io.BytesIO(src_bytes), "test.pdf"), "options": json.dumps({"compression": mode})},
            )
            self.assertEqual(res.status_code, 200)
            self.assertIn(f"Compresion {mode} completada", res.headers.get("X-PDF-Notice", ""))

    def test_02_signature_remove_background_and_flatten(self):
        # 1. API endpoint for background removal
        paper_sig = Image.new("RGB", (120, 80), (252, 252, 252))
        for i in range(80):
            paper_sig.putpixel((i, i), (15, 25, 80))  # dark ink
        buf = io.BytesIO()
        paper_sig.save(buf, format="PNG")

        res_bg = self.client.post(
            "/api/signature/remove_background",
            headers=self.headers,
            data={"file": (io.BytesIO(buf.getvalue()), "sig.png")},
        )
        self.assertEqual(res_bg.status_code, 200)
        trans_img = Image.open(io.BytesIO(res_bg.data))
        self.assertEqual(trans_img.mode, "RGBA")
        self.assertEqual(trans_img.getpixel((40, 40))[3], 255)  # ink intact
        self.assertEqual(trans_img.getpixel((10, 70))[3], 0)    # paper background 100% transparent

        # 2. Stamp with remove_background & flatten
        doc = pdf.open()
        doc.new_page()
        pdf_bytes = doc.tobytes()
        doc.close()

        res_stamp = self.client.post(
            "/api/process/stamp",
            headers=self.headers,
            data={
                "files": [
                    (io.BytesIO(pdf_bytes), "doc.pdf"),
                    (io.BytesIO(buf.getvalue()), "firma.png"),
                ],
                "options": json.dumps({"remove_background": True, "flatten": True, "x": 10, "y": 70, "width": 30, "height": 15}),
            },
        )
        self.assertEqual(res_stamp.status_code, 200)
        self.assertIn("Documento aplanado", res_stamp.headers.get("X-PDF-Notice", ""))

    def test_03_area_snippet_ocr(self):
        doc = pdf.open()
        page = doc.new_page(width=600, height=800)
        page.insert_text((120, 250), "CODIGO-SECRETO-SNIPPET-4455", fontsize=15)
        pdf_bytes = doc.tobytes()
        doc.close()

        res = self.client.post(
            "/api/ocr_snippet",
            headers=self.headers,
            data={
                "file": (io.BytesIO(pdf_bytes), "doc.pdf"),
                "page": 1,
                "x": 10,
                "y": 25,
                "w": 80,
                "h": 15,
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("CODIGO-SECRETO-SNIPPET-4455", data.get("text", ""))

    def test_04_copilot_chat_guidance_and_doc_qa(self):
        # Tool recommendation
        res1 = self.client.post(
            "/api/copilot/chat",
            headers=self.headers,
            data={"prompt": "¿Cómo censuro un PDF?"},
        )
        self.assertEqual(res1.status_code, 200)
        d1 = res1.get_json()
        self.assertEqual(d1.get("recommended_tool", {}).get("id"), "redact")

        # Document Q&A and summary
        doc = pdf.open()
        page = doc.new_page()
        page.insert_text((50, 50), "CONTRATO LEGAL. El plazo maximo de entrega es el 31 de Diciembre.", fontsize=12)
        pdf_bytes = doc.tobytes()
        doc.close()

        res2 = self.client.post(
            "/api/copilot/chat",
            headers=self.headers,
            data={"prompt": "¿Cuál es el plazo de entrega?", "file": (io.BytesIO(pdf_bytes), "contrato.pdf")},
        )
        self.assertEqual(res2.status_code, 200)
        d2 = res2.get_json()
        self.assertEqual(d2.get("type"), "qa")
        self.assertTrue(len(d2.get("matches", [])) >= 1)

    def test_05_visual_pdf_diff_color_highlighting(self):
        doc1 = pdf.open()
        page1 = doc1.new_page()
        page1.insert_text((50, 50), "Version Inicial Documento", fontsize=12)
        pdf1_bytes = doc1.tobytes()
        doc1.close()

        doc2 = pdf.open()
        page2 = doc2.new_page()
        page2.insert_text((50, 50), "Version Modificada Documento con Nuevas Clausulas", fontsize=12)
        pdf2_bytes = doc2.tobytes()
        doc2.close()

        res = self.client.post(
            "/api/process/compare",
            headers=self.headers,
            data={
                "files": [
                    (io.BytesIO(pdf1_bytes), "v1.pdf"),
                    (io.BytesIO(pdf2_bytes), "v2.pdf"),
                ],
                "options": json.dumps({}),
            },
        )
        self.assertEqual(res.status_code, 200)
        import zipfile
        with zipfile.ZipFile(io.BytesIO(res.data)) as archive:
            namelist = archive.namelist()
            png_count = sum(1 for n in namelist if n.endswith(".png"))
            self.assertGreaterEqual(png_count, 2)
            self.assertTrue(any(n.endswith(".pdf") for n in namelist))


if __name__ == "__main__":
    unittest.main()
