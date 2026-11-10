from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
import pymupdf as pdf
from docx import Document
from docx.shared import Inches
from openpyxl import load_workbook
from PIL import Image
from pptx import Presentation

from pdf_engine import capabilities, libreoffice_path
from server import CLIENT_BUILD, ROOT, create_app


def _build_complex_scan_pdf(*, rotated: bool = False) -> tuple[bytes, bytes]:
    """Genera un PDF puramente rasterizado (0 texto nativo, 0 trazos nativos) y su PNG fuente."""
    with pdf.open() as vector_src:
        page = vector_src.new_page(width=600, height=760)
        # 1. Encabezado en rojo oscuro negrita
        page.insert_text((52, 68), "INFORME TRIMESTRAL DE VENTAS", fontname="hebo", fontsize=19, color=(0.78, 0.1, 0.1))

        # 2. Tabla con cabecera combinada sombreada azul claro (#DCEBFF)
        xs = (52, 230, 390, 540)
        ys = (110, 148, 188, 228)
        page.draw_rect((xs[0], ys[0], xs[3], ys[1]), color=None, fill=(0.86, 0.92, 1.0))
        for y in ys:
            page.draw_line((xs[0], y), (xs[3], y), color=(0.12, 0.12, 0.12), width=1.6)
        for x in (xs[0], xs[2], xs[3]):
            page.draw_line((x, ys[0]), (x, ys[3]), color=(0.12, 0.12, 0.12), width=1.6)
        page.draw_line((xs[1], ys[1]), (xs[1], ys[3]), color=(0.12, 0.12, 0.12), width=1.6)

        page.insert_text((65, 134), "Resumen General", fontname="hebo", fontsize=13, color=(0.08, 0.12, 0.25))
        page.insert_text((408, 134), "Estado", fontname="hebo", fontsize=13, color=(0.08, 0.12, 0.25))
        page.insert_text((65, 173), "Producto Alpha", fontname="helv", fontsize=11.5)
        page.insert_text((248, 173), "1250.00", fontname="helv", fontsize=11.5)
        page.insert_text((408, 173), "Aprobado", fontname="helv", fontsize=11.5)
        page.insert_text((65, 213), "Producto Beta", fontname="helv", fontsize=11.5)
        page.insert_text((248, 213), "840.50", fontname="helv", fontsize=11.5)
        page.insert_text((408, 213), "Revision", fontname="helv", fontsize=11.5)

        # 3. Diagrama de flujo: caja rectangular -> flecha -> caja ovalo/redondeada
        page.draw_rect((55, 290, 205, 350), color=(0.18, 0.49, 0.20), fill=(0.91, 0.96, 0.91), width=2.0)
        page.insert_text((100, 326), "Inicio", fontname="hebo", fontsize=14, color=(0.08, 0.25, 0.08))

        page.draw_line((205, 320), (312, 320), color=(0.15, 0.15, 0.15), width=2.2)
        arrow_poly = page.new_shape()
        arrow_poly.draw_polyline([pdf.Point(322, 320), pdf.Point(306, 312), pdf.Point(306, 328)])
        arrow_poly.finish(color=(0.15, 0.15, 0.15), fill=(0.15, 0.15, 0.15), closePath=True)
        arrow_poly.commit()

        ov = page.new_shape()
        ov.draw_oval(pdf.Rect(326, 290, 486, 350))
        ov.finish(color=(0.94, 0.42, 0.0), fill=(1.0, 0.95, 0.88), width=2.0)
        ov.commit()
        page.insert_text((385, 326), "Final", fontname="hebo", fontsize=14, color=(0.45, 0.2, 0.0))

        # 4. Parrafo libre
        page.insert_text((55, 420), "Documento digitalizado para verificacion local.", fontname="helv", fontsize=12)

        # 5. Logo multicolor / ruidoso que debe sobrevivir intacto en el fondo residual
        arr = np.zeros((140, 180, 3), dtype=np.uint8)
        for yy in range(140):
            for xx in range(180):
                arr[yy, xx] = [((xx * 3) % 255), ((yy * 5) % 255), ((xx + yy) * 4) % 255]
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="PNG")
        page.insert_image((55, 510, 210, 620), stream=buf.getvalue())

        png_bytes = page.get_pixmap(dpi=200, colorspace=pdf.csRGB, alpha=False).tobytes("png")

    with pdf.open() as scan_doc:
        sp = scan_doc.new_page(width=600, height=760)
        sp.insert_image(sp.rect, stream=png_bytes)
        if rotated:
            sp.set_rotation(90)
        return scan_doc.tobytes(garbage=4, deflate=True), png_bytes


def _build_borderless_table_scan_pdf() -> bytes:
    with pdf.open() as vector_src:
        p = vector_src.new_page(width=580, height=400)
        rows = [
            ("Cuenta", "Importe", "Moneda"),
            ("Soporte", "450.00", "USD"),
            ("Hosting", "180.00", "USD"),
        ]
        for r_idx, cols in enumerate(rows):
            y = 85 + r_idx * 34
            fn = "hebo" if r_idx == 0 else "helv"
            p.insert_text((65, y), cols[0], fontname=fn, fontsize=13)
            p.insert_text((240, y), cols[1], fontname=fn, fontsize=13)
            p.insert_text((390, y), cols[2], fontname=fn, fontsize=13)
        png = p.get_pixmap(dpi=200, colorspace=pdf.csRGB, alpha=False).tobytes("png")
    with pdf.open() as doc:
        pg = doc.new_page(width=580, height=400)
        pg.insert_image(pg.rect, stream=png)
        return doc.tobytes(garbage=4, deflate=True)


def _extract_ppt_all_text(pres: Presentation) -> str:
    chunks: list[str] = []
    for slide in pres.slides:
        for sh in slide.shapes:
            if sh.has_text_frame:
                chunks.append(sh.text)
            if sh.has_table:
                for row in sh.table.rows:
                    for cell in row.cells:
                        chunks.append(cell.text)
    return "\n".join(chunks)


class ScanOfficeBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="folio-scan-office-")
        cls.root = Path(cls.tmp.name)
        cls.app = create_app(cls.root)
        cls.app.testing = True
        cls.client = cls.app.test_client()
        cls.config = cls.app.extensions["pdf_settings"]
        cls.headers = {"Origin": "http://localhost", "X-PDF-Client": CLIENT_BUILD}
        cls.scan_pdf, cls.scan_png = _build_complex_scan_pdf(rotated=False)
        cls.rotated_scan_pdf, _ = _build_complex_scan_pdf(rotated=True)

    @classmethod
    def tearDownClass(cls):
        cls.app.extensions["instance_lock"].close()
        cls.tmp.cleanup()

    def tearDown(self):
        self.assertEqual(list((self.root / "runtime").glob("job-*")), [])

    def call(self, op: str, uploads: list[tuple[bytes, str]], options: dict | None = None, expected: int = 200):
        resp = self.client.post(
            "/api/process/" + op,
            headers=self.headers,
            data={
                "options": json.dumps(options or {}),
                "files": [(io.BytesIO(data), name) for data, name in uploads],
            },
        )
        resp.get_data()
        resp.request.environ["wsgi.input"].close()
        self.assertEqual(resp.status_code, expected, resp.get_json() if resp.is_json else resp.data[:300])
        if expected == 200:
            self.assertEqual(resp.headers["X-PDF-Cleanup"], "complete")
            self.assertRegex(resp.headers["Content-Disposition"], r'filename="?EVA00\.[a-z0-9]+"?$')
        return resp

    def test_scan_to_office_registered_in_capabilities_and_js(self):
        import re
        from pdf_engine import OPERATIONS

        caps = self.client.get("/api/capabilities").json
        ids = {item["id"] for item in caps["v2_operations"]}
        self.assertIn("scan_to_office", ids)
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id:"scan_to_office"', app_js)
        self.assertIn("scan_editable_mode", app_js)
        self.assertIn("refine_scans", app_js)
        self.assertIn("unavailableInBackend", app_js)
        self.assertIn("REINICIAR SERVIDOR", app_js)

        for line in app_js.splitlines():
            stripped = line.strip()
            if stripped.startswith('{id:"') and "workspaceUrl" not in line and "standaloneTab" not in line:
                m = re.search(r'id:"([^"]+)"', line)
                self.assertIsNotNone(m)
                self.assertIn(m.group(1), OPERATIONS)

    def test_scan_to_office_pptx_acrobat_pro_mode(self):
        if not capabilities(self.config, ROOT)["ocr"]:
            self.skipTest("Modelos OCR no disponibles")

        # Verificar que el origen de entrada realmente no tiene texto ni dibujos nativos
        with pdf.open(stream=self.scan_pdf, filetype="pdf") as raw_doc:
            self.assertEqual(raw_doc[0].get_text().strip(), "")
            self.assertEqual(len(raw_doc[0].get_drawings()), 0)

        res = self.call(
            "scan_to_office",
            [(self.scan_pdf, "escaneo_complejo.pdf")],
            {"target_format": "pptx", "ocr_dpi": "200", "preprocess": "auto", "vectorize_tables": True, "vectorize_diagrams": True},
        )
        self.assertTrue(res.headers["Content-Disposition"].endswith("EVA00.pptx"))
        self.assertIn("OCR", res.headers["X-PDF-Notice"])

        pres = Presentation(io.BytesIO(res.data))
        self.assertEqual(len(pres.slides), 1)
        slide = pres.slides[0]

        # 1. Tabla editable con celda combinada, sombreado de cabecera y bordes ECMA-376
        tables = [sh.table for sh in slide.shapes if sh.has_table]
        self.assertGreaterEqual(len(tables), 1)
        tbl = tables[0]
        self.assertTrue(tbl.cell(0, 0).is_merge_origin)
        hdr_hex = str(tbl.cell(0, 0).fill.fore_color.rgb)
        self.assertGreater(int(hdr_hex[4:6], 16), 210)  # Azul claro en canal B
        self.assertIsNotNone(tbl.cell(0, 0)._tc.tcPr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}lnL"))

        all_text = _extract_ppt_all_text(pres).upper()
        for expected in ("INFORME", "VENTAS", "RESUMEN", "PRODUCTO", "ALPHA", "1250", "BETA", "INICIO", "FINAL"):
            self.assertIn(expected, all_text)

        # 2. Formas vectoriales de diagrama + conector con punta de flecha
        autoshapes = [sh for sh in slide.shapes if not sh.has_table and getattr(sh, "shape_type", None) == 1]  # AUTO_SHAPE
        self.assertGreaterEqual(len(autoshapes), 2)
        xml_blob = slide._element.xml
        self.assertIn("a:tailEnd", xml_blob if "a:tailEnd" in xml_blob else xml_blob.replace("tailEnd", "a:tailEnd"))

        # 3. Color de tinta rojo recuperado en el titulo editable
        title_runs = [
            run
            for sh in slide.shapes
            if sh.has_text_frame and "INFORME" in sh.text.upper()
            for p in sh.text_frame.paragraphs
            for run in p.runs
        ]
        self.assertTrue(
            any(
                int(str(r.font.color.rgb)[0:2], 16) > 130 and int(str(r.font.color.rgb)[2:4], 16) < 80
                for r in title_runs
                if r.font.color.rgb
            )
        )

        # 4. Fondo residual conserva el grafico complejo multicolor, pero borro pixeles rojos del titulo
        pics = [sh for sh in slide.shapes if sh.shape_type == 13]  # PICTURE
        self.assertEqual(len(pics), 1)
        with Image.open(io.BytesIO(pics[0].image.blob)) as bg:
            bg_rgb = bg.convert("RGB")
            bw, bh = bg_rgb.size
            title_crop = bg_rgb.crop((int(bw * 0.07), int(bh * 0.04), int(bw * 0.70), int(bh * 0.12))).tobytes()
            red_title_pixels = sum(
                title_crop[i] > 150 and title_crop[i + 1] < 90 and title_crop[i + 2] < 90
                for i in range(0, len(title_crop), 3)
            )
            self.assertEqual(red_title_pixels, 0)
            # Zona de logo inferior izquierdo conserva varianza cromatica (no fue destruida)
            logo_crop = np.array(bg_rgb.crop((int(bw * 0.10), int(bh * 0.68), int(bw * 0.32), int(bh * 0.80))))
            self.assertGreater(float(np.max(np.std(logo_crop.reshape(-1, 3), axis=0))), 30.0)

        # 5. LibreOffice Impress debe abrir EVA00.pptx sin errores ni perdida de contenido
        if libreoffice_path(self.config):
            work = self.root / "lo-check-pptx"
            work.mkdir(exist_ok=True)
            pptx_path = work / "in.pptx"
            pptx_path.write_bytes(res.data)
            from pdf_engine import convert_office
            rendered = convert_office(pptx_path, work, self.config)
            with pdf.open(rendered) as rendered_doc:
                self.assertEqual(len(rendered_doc), 1)
                self.assertIn("PRODUCTO", rendered_doc[0].get_text().upper())

    def test_legacy_pdf_to_pptx_refined_vs_default_fallback(self):
        if not capabilities(self.config, ROOT)["ocr"]:
            self.skipTest("Modelos OCR no disponibles")

        # Por API sin scan_editable_mode se mantiene retrocompatibilidad con fallback explicito
        res_legacy = self.call("pdf_to_pptx", [(self.scan_pdf, "scan.pdf")], {})
        self.assertIn("OCR", res_legacy.headers["X-PDF-Notice"])
        pres_legacy = Presentation(io.BytesIO(res_legacy.data))
        self.assertEqual(sum(sh.has_table for sh in pres_legacy.slides[0].shapes), 0)

        # Con scan_editable_mode=True reconstruye tabla editable, diagramas y texto OCR
        res_refined = self.call(
            "pdf_to_pptx",
            [(self.scan_pdf, "scan.pdf")],
            {"scan_editable_mode": True, "vectorize_diagrams": True, "ocr_dpi": "200", "preprocess": "auto"},
        )
        pres_ref = Presentation(io.BytesIO(res_refined.data))
        self.assertGreaterEqual(sum(sh.has_table for sh in pres_ref.slides[0].shapes), 1)
        self.assertIn("ALPHA", _extract_ppt_all_text(pres_ref).upper())

    def test_scan_to_office_docx_xlsx_and_vector_pdf(self):
        if not capabilities(self.config, ROOT)["ocr"]:
            self.skipTest("Modelos OCR no disponibles")

        # DOCX
        res_docx = self.call("scan_to_office", [(self.scan_pdf, "scan.pdf")], {"target_format": "docx"})
        self.assertTrue(res_docx.headers["Content-Disposition"].endswith("EVA00.docx"))
        doc_out = Document(io.BytesIO(res_docx.data))
        self.assertGreaterEqual(len(doc_out.tables), 1)
        docx_text = "\n".join(
            [p.text for p in doc_out.paragraphs] + [c.text for tbl in doc_out.tables for c in tbl._cells]
        ).upper()
        self.assertIn("INFORME", docx_text)
        self.assertIn("ALPHA", docx_text)

        # XLSX
        res_xlsx = self.call("scan_to_office", [(self.scan_pdf, "scan.pdf")], {"target_format": "xlsx"})
        self.assertTrue(res_xlsx.headers["Content-Disposition"].endswith("EVA00.xlsx"))
        wb = load_workbook(io.BytesIO(res_xlsx.data))
        try:
            self.assertEqual(wb.sheetnames, ["Pagina 1", "Original 1"])
            values = [str(cell.value or "").upper() for row in wb["Pagina 1"].iter_rows() for cell in row]
            joined = "\n".join(values)
            self.assertIn("PRODUCTO", joined)
            self.assertIn("1250", joined)
        finally:
            wb.close()

        # PDF vectorial + OCR
        res_pdf = self.call("scan_to_office", [(self.scan_pdf, "scan.pdf")], {"target_format": "pdf"})
        self.assertTrue(res_pdf.headers["Content-Disposition"].endswith("EVA00.pdf"))
        with pdf.open(stream=res_pdf.data, filetype="pdf") as vec_pdf:
            txt = vec_pdf[0].get_text().upper()
            self.assertIn("INFORME", txt)
            self.assertIn("ALPHA", txt)
            self.assertGreaterEqual(len(vec_pdf[0].get_drawings()), 6)

    def test_png_image_rotated_and_mixed_pdf_plus_borderless_table(self):
        if not capabilities(self.config, ROOT)["ocr"]:
            self.skipTest("Modelos OCR no disponibles")

        # Imagen PNG directa -> PPTX editable
        res_png = self.call("scan_to_office", [(self.scan_png, "captura_scan.png")], {"target_format": "pptx"})
        pres_png = Presentation(io.BytesIO(res_png.data))
        self.assertGreaterEqual(sum(sh.has_table for sh in pres_png.slides[0].shapes), 1)

        # PDF escaneado rotado 90 grados
        res_rot = self.call("scan_to_office", [(self.rotated_scan_pdf, "rotado.pdf")], {"target_format": "pptx"})
        pres_rot = Presentation(io.BytesIO(res_rot.data))
        self.assertIn("INFORME", _extract_ppt_all_text(pres_rot).upper())

        # PDF mixto: pag 1 nativa vectorial + pag 2 escaneada
        with pdf.open() as mixed, pdf.open(stream=self.scan_pdf, filetype="pdf") as scan_src:
            p1 = mixed.new_page(width=600, height=760)
            p1.insert_text((72, 100), "PAGINA NATIVA INTACTA", fontname="hebo", fontsize=18)
            mixed.insert_pdf(scan_src)
            mixed_bytes = mixed.tobytes(garbage=4, deflate=True)
        res_mix = self.call("scan_to_office", [(mixed_bytes, "mixto.pdf")], {"target_format": "pptx"})
        pres_mix = Presentation(io.BytesIO(res_mix.data))
        self.assertEqual(len(pres_mix.slides), 2)
        self.assertTrue(any(sh.has_text_frame and "NATIVA INTACTA" in sh.text for sh in pres_mix.slides[0].shapes))
        self.assertGreaterEqual(sum(sh.has_table for sh in pres_mix.slides[1].shapes), 1)

        # Tabla sin bordes detectada por alineacion columnar OCR
        borderless_pdf = _build_borderless_table_scan_pdf()
        res_bl = self.call("scan_to_office", [(borderless_pdf, "sin_bordes.pdf")], {"target_format": "pptx"})
        pres_bl = Presentation(io.BytesIO(res_bl.data))
        self.assertGreaterEqual(sum(sh.has_table for sh in pres_bl.slides[0].shapes), 1)
        self.assertIn("450", _extract_ppt_all_text(pres_bl))

    def test_office_to_pdf_with_refine_scans_embedded_table(self):
        if not (libreoffice_path(self.config) and capabilities(self.config, ROOT)["ocr"]):
            self.skipTest("LibreOffice u OCR no disponibles")

        # Crear imagen raster de una tabla con titulo para incrustar dentro de .docx
        with pdf.open() as tbl_src:
            tp = tbl_src.new_page(width=420, height=200)
            for y in (30, 80, 140):
                tp.draw_line((20, y), (390, y), width=1.6)
            for x in (20, 210, 390):
                tp.draw_line((x, 30), (x, 140), width=1.6)
            tp.insert_text((35, 62), "Concepto", fontname="hebo", fontsize=13)
            tp.insert_text((225, 62), "Total", fontname="hebo", fontsize=13)
            tp.insert_text((35, 115), "Servicio", fontname="helv", fontsize=12)
            tp.insert_text((225, 115), "990.00", fontname="helv", fontsize=12)
            tbl_png = tp.get_pixmap(dpi=200).tobytes("png")

        word = Document()
        word.add_heading("Anexo Office Nativo", level=1)
        word.add_picture(io.BytesIO(tbl_png), width=Inches(5.5))
        doc_buf = io.BytesIO()
        word.save(doc_buf)

        res = self.call("office_to_pdf", [(doc_buf.getvalue(), "anexo.docx")], {"refine_scans": True})
        self.assertIn("refinado", res.headers["X-PDF-Notice"].lower())
        with pdf.open(stream=res.data, filetype="pdf") as pdf_out:
            txt = pdf_out[0].get_text().upper()
            self.assertIn("ANEXO OFFICE NATIVO", txt)
            self.assertIn("CONCEPTO", txt)
            self.assertIn("990", txt)
            self.assertGreaterEqual(len(pdf_out[0].get_drawings()), 4)

    def test_missing_ocr_models_returns_503_for_text_only_scan(self):
        from pdf_engine import ProcessingError, process

        with pdf.open() as src:
            p = src.new_page(width=500, height=300)
            p.insert_text((60, 100), "Texto escaneado sin tablas ni diagramas", fontsize=16)
            png = p.get_pixmap(dpi=150).tobytes("png")
        with pdf.open() as scan:
            sp = scan.new_page(width=500, height=300)
            sp.insert_image(sp.rect, stream=png)
            scan_bytes = scan.tobytes()

        with tempfile.TemporaryDirectory(prefix="folio-no-ocr-") as empty_dir:
            no_ocr_root = Path(empty_dir)
            work = no_ocr_root / "job"
            work.mkdir()
            src_pdf = work / "s.pdf"
            src_pdf.write_bytes(scan_bytes)
            with self.assertRaises(ProcessingError) as ctx:
                process("scan_to_office", [src_pdf], {"target_format": "pptx"}, work, self.config, no_ocr_root)
            self.assertEqual(ctx.exception.status, 503)


if __name__ == "__main__":
    unittest.main()
