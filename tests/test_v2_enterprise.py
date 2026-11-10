from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

import cv2
import numpy as np
import openpyxl
import pikepdf
import pymupdf as pdf

from server import CLIENT_BUILD, ROOT, create_app
from settings import load_settings
from workload import WorkloadQueue


def _pdf_bytes(builder) -> bytes:
    with pdf.open() as doc:
        builder(doc)
        return doc.tobytes(garbage=4, deflate=True)


class V2EnterpriseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="folio-v2-test-")
        cls.root = Path(cls.tmp.name)
        cls.app = create_app(cls.root)
        cls.app.testing = True
        cls.client = cls.app.test_client()
        cls.headers = {"Origin": "http://localhost", "X-PDF-Client": CLIENT_BUILD}

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

    def test_v2_routes_csp_and_capabilities(self):
        for route in ("/", "/editor", "/pipeline", "/canvas", "/vault"):
            res = self.client.get(route)
            self.assertEqual(res.status_code, 200, route)
            html_txt = res.get_data(as_text=True)
            # Politica CSP estricta: sin bloques script inline en workspaces V2
            self.assertNotIn("<script>", html_txt)
            self.assertNotIn("<style>", html_txt)
            csp = res.headers["Content-Security-Policy"]
            self.assertIn("script-src 'self'", csp)
            self.assertNotIn("wasm-unsafe-eval", csp)

        caps = self.client.get("/api/capabilities").json
        self.assertTrue(caps["v2_enabled"])
        self.assertEqual(caps["ai_mode"], "disabled")
        self.assertFalse(caps["wasm_viewer"])
        self.assertGreaterEqual(len(caps["v2_operations"]), 24)

    def test_v2_opt_in_wasm_csp_and_extension_isolation(self):
        with tempfile.TemporaryDirectory(prefix="folio-wasm-") as td:
            wroot = Path(td)
            (wroot / "config").mkdir(exist_ok=True)
            (wroot / "config" / "site_config.json").write_text(
                json.dumps({"allow_wasm_viewer": True}), encoding="utf-8"
            )
            wapp = create_app(wroot)
            try:
                res = wapp.test_client().get("/canvas")
                self.assertIn("'wasm-unsafe-eval'", res.headers["Content-Security-Policy"])
                self.assertIn("worker-src 'self' blob:", res.headers["Content-Security-Policy"])
            finally:
                wapp.extensions["instance_lock"].close()

        # Extensiones peligrosas deben seguir rechazadas en endpoints V2
        self.call("anti_track", [(b"MZ\x90\x00", "evil.exe")], expected=422)
        self.call("crypto_container_unlock", [(b"{}", "bad.pdf")], {"role_password": "secret"}, expected=422)

    def test_ai_heavy_workload_cap(self):
        import threading

        cfg = load_settings(self.root)
        cfg["max_ai_jobs"] = 1
        cfg["max_parallel_jobs"] = 3
        cfg["max_heavy_jobs"] = 2
        q = WorkloadQueue(cfg, threading.BoundedSemaphore(3))
        t1 = q.enter("a" * 32, "translate_layout", 1024)
        self.assertTrue(t1.ai_heavy)
        self.assertEqual(q.status("a" * 32)["state"], "processing")
        # Una segunda peticion AI simultanea debe encolarse por limite max_ai_jobs=1
        holder = {}

        def _enter_second():
            holder["t2"] = q.enter("b" * 32, "latex_ocr", 1024)

        th = threading.Thread(target=_enter_second)
        th.start()
        import time
        time.sleep(0.15)
        st2 = q.status("b" * 32)
        self.assertIsNotNone(st2)
        self.assertEqual(st2["state"], "queued")
        q.leave(t1)
        th.join(timeout=3)
        q.leave(holder["t2"])

    def test_01_anti_track(self):
        # Construir PDF con OpenAction, JavaScript, URI tracking y pixel 1x1
        buf = io.BytesIO()
        with pikepdf.Pdf.new() as pk:
            pg = pk.add_blank_page(page_size=(400, 400))
            pk.Root["/OpenAction"] = pikepdf.Dictionary({"/S": pikepdf.Name("/JavaScript"), "/JS": pikepdf.String("app.alert(1)")})
            pk.Root["/Names"] = pikepdf.Dictionary({"/JavaScript": pikepdf.Dictionary({"/Names": pikepdf.Array([])})})
            link = pk.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/Annot"),
                "/Subtype": pikepdf.Name("/Link"),
                "/Rect": pikepdf.Array([20, 20, 200, 50]),
                "/A": pikepdf.Dictionary({
                    "/S": pikepdf.Name("/URI"),
                    "/URI": pikepdf.String("https://ejemplo.org/doc?utm_source=tracker&fbclid=xyz&page=2"),
                }),
            }))
            beacon = pk.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/Annot"),
                "/Subtype": pikepdf.Name("/Link"),
                "/Rect": pikepdf.Array([0, 0, 1, 1]),
                "/A": pikepdf.Dictionary({"/S": pikepdf.Name("/URI"), "/URI": pikepdf.String("https://pixel.test/p.gif")}),
            }))
            pg["/Annots"] = pikepdf.Array([link, beacon])
            pk.save(buf)

        res = self.call("anti_track", [(buf.getvalue(), "track.pdf")])
        with pikepdf.open(io.BytesIO(res.data)) as clean_pk:
            self.assertNotIn("/OpenAction", clean_pk.Root)
            annots = list(clean_pk.pages[0].get("/Annots", []))
            self.assertEqual(len(annots), 1)
            cleaned_uri = str(annots[0]["/A"]["/URI"])
            self.assertNotIn("utm_source", cleaned_uri)
            self.assertNotIn("fbclid", cleaned_uri)
            self.assertIn("page=2", cleaned_uri)

    def test_02_forensic_sanitize_single_eof_and_redaction(self):
        # Crear PDF de 2 revisiones incrementales reales (count %%EOF >= 2) con dato sensible
        inc_path = self.root / "inc_stage.pdf"
        with pdf.open() as d:
            p = d.new_page()
            p.insert_text((72, 100), "Publico visible", fontsize=12)
            p.insert_text((72, 150), "CLAVE_SECRETA_XYZ", fontsize=12)
            d.save(inc_path)
        with pdf.open(inc_path) as d2:
            d2[0].insert_text((72, 200), "Revision 2", fontsize=10)
            d2.saveIncr()
        multi_rev_bytes = inc_path.read_bytes()
        inc_path.unlink(missing_ok=True)
        self.assertGreaterEqual(multi_rev_bytes.count(b"%%EOF"), 2)

        res = self.call(
            "forensic_sanitize",
            [(multi_rev_bytes, "conf.pdf")],
            {"redact_patterns": ["CLAVE_SECRETA_XYZ"], "verify_terms": ["CLAVE_SECRETA_XYZ"], "include_report": True},
        )
        with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
            names = zf.namelist()
            pdf_entry = next(n for n in names if n.endswith(".pdf"))
            json_entry = next(n for n in names if n.endswith(".json"))
            raw_pdf = zf.read(pdf_entry)
            report = json.loads(zf.read(json_entry).decode("utf-8"))
            self.assertEqual(raw_pdf.count(b"%%EOF"), 1)
            self.assertTrue(report["verified_terms_absent"]["CLAVE_SECRETA_XYZ"])
            self.assertNotIn(b"CLAVE_SECRETA_XYZ", raw_pdf)

    def test_03_vectors_svg_and_layers(self):
        raw = _pdf_bytes(lambda doc: (
            p := doc.new_page(),
            p.draw_rect(pdf.Rect(50, 50, 200, 150), color=(0, 0, 1), fill=(0.9, 0.9, 1)),
            p.draw_line(pdf.Point(50, 150), pdf.Point(200, 50), color=(1, 0, 0), width=2),
            p.insert_text((60, 170), "Eje X Ventana", fontsize=11),
        ))
        res = self.call("extract_vectors_svg", [(raw, "chart.pdf")], {"include_eps": True})
        with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
            svgs = [n for n in zf.namelist() if n.endswith(".svg")]
            epss = [n for n in zf.namelist() if n.endswith(".eps")]
            self.assertGreaterEqual(len(svgs), 1)
            self.assertGreaterEqual(len(epss), 1)
            svg_txt = zf.read(svgs[0]).decode("utf-8")
            self.assertIn('id="vectors"', svg_txt)
            self.assertIn('id="labels"', svg_txt)
            self.assertIn("<text", svg_txt)

    def test_04_table_bridge_roundtrip(self):
        def _build(doc):
            p = doc.new_page()
            # Tabla con bordes explícitos
            for r in range(3):
                for c in range(2):
                    x0, y0 = 60 + c * 110, 60 + r * 28
                    p.draw_rect(pdf.Rect(x0, y0, x0 + 110, y0 + 28), color=(0, 0, 0), width=0.8)
            p.insert_text((68, 78), "Concepto", fontsize=10)
            p.insert_text((178, 78), "Monto", fontsize=10)
            p.insert_text((68, 106), "Licencia", fontsize=10)
            p.insert_text((178, 106), "$100.00", fontsize=10)
            p.insert_text((68, 134), "IVA", fontsize=10)
            p.insert_text((178, 134), "19%", fontsize=10)
            # Tabla sin bordes inferiores
            p.insert_text((68, 220), "ItemA", fontsize=10)
            p.insert_text((180, 220), "42", fontsize=10)
            p.insert_text((68, 240), "ItemB", fontsize=10)
            p.insert_text((180, 240), "84", fontsize=10)

        src = _pdf_bytes(_build)
        ext_res = self.call("table_bridge_extract", [(src, "tabla.pdf")], {"format": "xlsx"})
        wb = openpyxl.load_workbook(io.BytesIO(ext_res.data))
        self.assertIn("_EVA_COORDS", wb.sheetnames)
        self.assertIn("Tabla_01", wb.sheetnames)
        # Modificar el monto 100 -> 250 en Excel y reaplicar al PDF
        wb["Tabla_01"].cell(row=2, column=2, value=250.0)
        mod_xlsx = io.BytesIO()
        wb.save(mod_xlsx)

        app_res = self.call("table_bridge_apply", [(src, "tabla.pdf"), (mod_xlsx.getvalue(), "edit.xlsx")])
        with pdf.open(stream=app_res.data, filetype="pdf") as updated:
            txt = updated[0].get_text()
            self.assertIn("250.00", txt)

    def test_05_semantic_replace_and_currency(self):
        src = _pdf_bytes(lambda d: (
            p := d.new_page(),
            p.insert_text((60, 100), "Precio: USD 100.00", fontsize=12),
            p.insert_text((60, 130), "Fecha: 15/03/2026", fontsize=12),
        ))
        opts = {
            "rules": [
                {"kind": "currency", "rate": 2.0, "target_currency": "EUR", "decimals": 2},
                {"kind": "date", "target_format": "%Y-%m-%d"},
            ]
        }
        dry = self.call("semantic_replace", [(src, "precios.pdf")], {**opts, "dry_run": True})
        dry_json = json.loads(dry.data.decode("utf-8"))
        self.assertTrue(dry_json["dry_run"])
        self.assertEqual(dry_json["matches"], 2)

        live = self.call("semantic_replace", [(src, "precios.pdf")], opts)
        with pdf.open(stream=live.data, filetype="pdf") as out:
            txt = out[0].get_text()
            self.assertIn("EUR 200.00", txt)
            self.assertIn("2026-03-15", txt)

    def test_06_pipeline_and_contextual_zip_opt_in(self):
        def _build(d):
            p1 = d.new_page()
            p1.insert_text((60, 100), "FACTURA FAC-2026-001", fontsize=14)
            p2 = d.new_page()
            p2.insert_text((60, 100), "CONTRATO CTR-2026-099", fontsize=14)

        src = _pdf_bytes(_build)
        # Por defecto contextual_names=False -> mantiene estandar EVA00_XX
        res_std = self.call(
            "pipeline_run",
            [(src, "lote.pdf")],
            {"contextual_names": False, "pipeline": {"split_by_regex": r"(FACTURA|CONTRATO)"}},
        )
        with zipfile.ZipFile(io.BytesIO(res_std.data)) as zf:
            for nm in zf.namelist():
                self.assertRegex(Path(nm).name, r"^EVA00_\d{2,}\.[a-z0-9]+$")

        # Opt-in contextual_names=True (#6a) -> preserva subcarpetas y nombres semanticos en EVA00.zip
        res_ctx = self.call(
            "pipeline_run",
            [(src, "lote.pdf")],
            {
                "contextual_names": True,
                "pipeline": {
                    "split_by_regex": r"(FACTURA|CONTRATO)",
                    "routes": [
                        {"when": {"contains_text": "FACTURA"}, "folder": "Facturas", "name_template": "{folder}/{doc_id}.pdf"},
                        {"when": {"contains_text": "CONTRATO"}, "folder": "Contratos", "name_template": "{folder}/{doc_id}.pdf"},
                    ],
                    "transforms": [{"op": "anti_track"}],
                },
            },
        )
        with zipfile.ZipFile(io.BytesIO(res_ctx.data)) as zf:
            names = zf.namelist()
            self.assertIn("Facturas/FAC-2026-001.pdf", names)
            self.assertIn("Contratos/CTR-2026-099.pdf", names)
            self.assertIn("MANIFIESTO_PIPELINE.json", names)

    def test_07_template_detect_and_compile(self):
        tpl = _pdf_bytes(lambda d: (
            p := d.new_page(),
            p.insert_text((70, 100), "Cliente: {{cliente}}", fontsize=12),
            p.insert_text((70, 130), "Importe: {{monto}}", fontsize=12),
        ))
        det = self.call("template_detect", [(tpl, "tpl.pdf")])
        schema = json.loads(det.data.decode("utf-8"))
        self.assertIn("cliente", schema["columns"])
        self.assertIn("monto", schema["columns"])

        csv_bytes = "cliente,monto\nAna Lopez,USD 500\nCarlos Ruiz,USD 900\n".encode("utf-8")
        comp = self.call("template_compile", [(tpl, "tpl.pdf"), (csv_bytes, "datos.csv")])
        with zipfile.ZipFile(io.BytesIO(comp.data)) as zf:
            pdfs = [n for n in zf.namelist() if n.endswith(".pdf")]
            self.assertEqual(len(pdfs), 2)
            with pdf.open(stream=zf.read(pdfs[0]), filetype="pdf") as d1:
                self.assertIn("Ana Lopez", d1[0].get_text())

    def test_08_compare_semantic_and_migration(self):
        def _v1(d):
            p1 = d.new_page()
            p1.insert_text((72, 100), "Clausula de Confidencialidad Perpetua.", fontsize=12)
            p1.add_highlight_annot(pdf.Rect(70, 88, 280, 108)).set_info(content="Revisar plazo legal")
            d.new_page().insert_text((72, 100), "Anexo Final.", fontsize=12)

        def _v2(d):
            d.new_page().insert_text((72, 100), "Portada Nueva.", fontsize=12)
            p2 = d.new_page()
            p2.insert_text((72, 200), "Clausula de Confidencialidad Perpetua.", fontsize=12)
            p2.insert_text((72, 260), "Anexo Final.", fontsize=12)

        res = self.call("compare_semantic", [(_pdf_bytes(_v1), "v1.pdf"), (_pdf_bytes(_v2), "v2.pdf")])
        with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
            diff = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith(".json"))).decode("utf-8"))
            statuses = {c["status"] for c in diff["changes"]}
            self.assertIn("MOVED", statuses)
            self.assertEqual(len(diff["annotations_migrated"]), 1)
            self.assertEqual(diff["annotations_migrated"][0]["v2_page"], 2)

    def test_09_research_link(self):
        p1 = _pdf_bytes(lambda d: (
            pg1 := d.new_page(),
            pg1.insert_text((72, 80), "Estudio Cuantico A [1]", fontsize=13),
            pg1.insert_text((72, 110), "Referencia cruzada 10.1000/eva.2026", fontsize=11),
            pg2 := d.new_page(),
            pg2.insert_text((72, 80), "[1] Nota bibliografica interna", fontsize=10),
        ))
        p2 = _pdf_bytes(lambda d: (
            pg := d.new_page(),
            pg.insert_text((72, 80), "Paper Base 10.1000/eva.2026", fontsize=12),
        ))
        res = self.call("research_link", [(p1, "paper1.pdf"), (p2, "paper2.pdf")])
        with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
            contents = {Path(n).suffix: zf.read(n) for n in zf.namelist()}
            self.assertIn(".bib", contents)
            self.assertIn(".ris", contents)
            self.assertIn(".json", contents)
            graph = json.loads(contents[".json"].decode("utf-8")) if b"nodes" in contents[".json"] else None
            # Verifica enlaces internos y/o cruzados inyectados
            pdf_docs = [n for n in zf.namelist() if n.endswith(".pdf")]
            self.assertEqual(len(pdf_docs), 2)
            with pdf.open(stream=zf.read(pdf_docs[0]), filetype="pdf") as linked:
                self.assertGreaterEqual(len(linked[0].get_links()), 1)

    def test_10_scan_enhance_3d_and_mrc(self):
        # Construir imagen sintetica inclinada con hoja blanca sobre fondo oscuro + texto
        canvas = np.full((500, 500, 3), 30, dtype=np.uint8)
        cv2.rectangle(canvas, (70, 60), (430, 440), (242, 240, 235), -1)
        cv2.putText(canvas, "EVA MRC 3D", (120, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (10, 10, 10), 2)
        ok, enc = cv2.imencode(".png", canvas)
        self.assertTrue(ok)
        res = self.call("scan_enhance_3d", [(enc.tobytes(), "foto.png")], {"perspective": True, "dewarp": True, "mrc": True})
        with pdf.open(stream=res.data, filetype="pdf") as mrc_doc:
            self.assertEqual(len(mrc_doc), 1)
            self.assertGreaterEqual(len(mrc_doc[0].get_images()), 1)

    def test_11_edit_reflow_and_liquid_compile(self):
        src = _pdf_bytes(lambda d: (
            p := d.new_page(),
            p.insert_text((50, 80), "Titulo Principal", fontsize=20),
            p.insert_text((50, 130), "Columna izquierda primer parrafo de texto fluido.", fontsize=11),
            p.insert_text((320, 130), "Columna derecha segundo bloque independiente.", fontsize=11),
        ))
        prev = self.call("edit_reflow", [(src, "cols.pdf")], {"dry_run": True})
        prev_data = json.loads(prev.data.decode("utf-8"))
        self.assertTrue(prev_data["dry_run"])
        self.assertGreaterEqual(len(prev_data["thumbnails_png_b64"]), 1)

        out = self.call("edit_reflow", [(src, "cols.pdf")], {"edits": [{"find": "fluido", "replace": "adaptado"}]})
        with pdf.open(stream=out.data, filetype="pdf") as reflowed:
            self.assertIn("adaptado", reflowed[0].get_text())

        liq = self.call("liquid_compile", [(src, "cols.pdf")], {"preset": "kindle_6", "format": "pdf"})
        with pdf.open(stream=liq.data, filetype="pdf") as kdoc:
            self.assertAlmostEqual(kdoc[0].rect.width, 255.0, delta=2.0)

    def test_12_font_reconstruct_latex_wcag_and_translate(self):
        src = _pdf_bytes(lambda d: (
            p := d.new_page(),
            p.insert_text((72, 80), "Factura", fontsize=16),
            p.insert_text((72, 120), "Total", fontsize=11),
        ))
        # #4 Auditoria + Reconstructor
        f_aud = self.call("font_reconstruct", [(src, "doc.pdf")], {"audit_only": True})
        self.assertIn("fonts", json.loads(f_aud.data.decode("utf-8")))
        f_rep = self.call(
            "font_reconstruct",
            [(src, "doc.pdf")],
            {"replacements": [{"page": 1, "bbox": [70, 105, 220, 135], "text": "Canción España €", "font": "Arial"}]},
        )
        with pdf.open(stream=f_rep.data, filetype="pdf") as rfdoc:
            self.assertIn("Canci", rfdoc[0].get_text())

        # #10 LaTeX Vectorial
        ltx = self.call("latex_ocr", [(src, "doc.pdf")], {"latex": r"\frac{x + 1}{y^2} = \sqrt{\alpha}", "insert_into_pdf": True})
        with zipfile.ZipFile(io.BytesIO(ltx.data)) as zf:
            tex = zf.read(next(n for n in zf.namelist() if n.endswith(".tex"))).decode("utf-8")
            svg = zf.read(next(n for n in zf.namelist() if n.endswith(".svg"))).decode("utf-8")
            self.assertIn(r"\frac", tex)
            self.assertIn("<svg", svg)

        # #18 WCAG PDF/UA + Audio-Tags
        wcag = self.call("accessibility_tagger", [(src, "doc.pdf")], {"lang": "es-ES", "format": "zip"})
        with zipfile.ZipFile(io.BytesIO(wcag.data)) as zf:
            pdf_ua = zf.read(next(n for n in zf.namelist() if n.endswith(".pdf")))
            with pikepdf.open(io.BytesIO(pdf_ua)) as pk:
                self.assertIn("/StructTreeRoot", pk.Root)
                self.assertEqual(str(pk.Root.get("/Lang")), "es-ES")
                self.assertTrue(bool(pk.Root["/MarkInfo"]["/Marked"]))
            narr = next(n for n in zf.namelist() if n.endswith(".json") and b"segments" in zf.read(n))
            self.assertGreaterEqual(len(json.loads(zf.read(narr).decode("utf-8"))["segments"]), 2)

        # #12 Traductor Vectorial In-Situ (validacion y fallback de glosario aislado)
        self.call("translate_layout", [(src, "doc.pdf")], {"source_lang": "es", "target_lang": "es"}, expected=400)
        tr = self.call("translate_layout", [(src, "doc.pdf")], {"source_lang": "es", "target_lang": "en"})
        with pdf.open(stream=tr.data, filetype="pdf") as trdoc:
            self.assertIn("Invoice", trdoc[0].get_text())

    def test_13_copilot_plan_vs_apply_forensic_audit_crypto_vault_and_canvas_sync(self):
        doc_bytes = _pdf_bytes(lambda d: (
            p := d.new_page(),
            p.insert_text((60, 80), "Informe para contacto@privado.org", fontsize=12),
            p.insert_text((60, 120), "Salario secreto: USD 99000", fontsize=12),
            p.insert_text((60, 160), "Cita sin fuente [9]", fontsize=11),
        ))
        # #7 Co-Piloto: plan nunca muta; apply sin approved se rechaza
        self.call("copilot_apply", [(doc_bytes, "d.pdf")], {"approved": False, "steps": [{"action": "anti_track"}]}, expected=400)
        plan_res = self.call("copilot_plan", [(doc_bytes, "d.pdf")], {"prompt": "Censura correos y pon marca de agua INTERNO"})
        plan = json.loads(plan_res.data.decode("utf-8"))
        self.assertFalse(plan["mutated_source"])
        self.assertGreaterEqual(len(plan["steps"]), 1)

        applied = self.call("copilot_apply", [(doc_bytes, "d.pdf")], {"approved": True, "plan": plan})
        with pdf.open(stream=applied.data, filetype="pdf") as adoc:
            txt = adoc[0].get_text()
            self.assertNotIn("contacto@privado.org", txt)
            self.assertIn("INTERNO", txt)

        # #14 Auditoria forense y corpus local
        corpus = b"Informe para contacto@privado.org Salario secreto Cita sin fuente [9] texto compartido"
        audit_res = self.call("forensic_audit", [(doc_bytes, "d.pdf"), (corpus, "corpus.txt")], {"format": "json"})
        audit = json.loads(audit_res.data.decode("utf-8"))
        self.assertIn(9, audit["citations"]["dangling_citations"])
        self.assertEqual(len(audit["local_corpus_overlap"]), 1)
        self.assertIn("NO constituyen prueba legal", audit["disclaimer"])

        # #16 Cripto-contenedor Multi-Rol dual (.evacrypt + role AES-256 ZIP) + unlock
        pack_res = self.call(
            "crypto_container_pack",
            [(doc_bytes, "conf.pdf")],
            {
                "mode": "dual",
                "roles": [
                    {"role": "Auditor", "password": "ClaveAuditor2026!", "redact_patterns": ["99000"]},
                    {"role": "Director", "password": "ClaveDirector2026!", "redact_patterns": []},
                ],
            },
        )
        with zipfile.ZipFile(io.BytesIO(pack_res.data)) as zf:
            evacrypt_name = next(n for n in zf.namelist() if n.endswith(".evacrypt"))
            evacrypt_bytes = zf.read(evacrypt_name)

        # Clave erronea -> 403
        self.call("crypto_container_unlock", [(evacrypt_bytes, "box.evacrypt")], {"role": "Auditor", "role_password": "MALA"}, expected=403)
        # Rol Auditor obtiene PDF sin 99000 ni siquiera en raw bytes COS
        unlocked = self.call(
            "crypto_container_unlock",
            [(evacrypt_bytes, "box.evacrypt")],
            {"role": "Auditor", "role_password": "ClaveAuditor2026!"},
        )
        self.assertNotIn(b"99000", unlocked.data)
        with pdf.open(stream=unlocked.data, filetype="pdf") as aud_pdf:
            self.assertIn("Informe para", aud_pdf[0].get_text())

        # #20 Canvas extract sync
        sync1 = self.call("canvas_extract_sync", [(doc_bytes, "d.pdf")], {"extracts": [{"id": "n1", "doc_index": 0, "page": 1}]})
        s1 = json.loads(sync1.data.decode("utf-8"))
        sha = s1["extracts"][0]["sha256"]
        sync2 = self.call(
            "canvas_extract_sync",
            [(applied.data, "d_v2.pdf")],
            {"extracts": [{"id": "n1", "doc_index": 0, "page": 1, "expected_sha256": sha}]},
        )
        s2 = json.loads(sync2.data.decode("utf-8"))
        self.assertEqual(s2["extracts"][0]["status"], "updated")

        # Privacidad SQLite intacta tras las 20 capacidades V2
        with closing(sqlite3.connect(self.root / "instance" / "platform.sqlite3")) as conn:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            self.assertEqual(tables, [("settings",)])
            dump = str(conn.execute("SELECT * FROM settings").fetchall())
            self.assertNotIn("99000", dump)
            self.assertNotIn("ClaveAuditor", dump)

    def test_14_offline_nmt_translation_paragraphs_diacritics_and_scans(self):
        from engines.addons import addons_status
        from engines.typography_and_layout import handle_translate_layout
        from pdf_engine import capabilities

        nmt_dir = ROOT / "addons" / "pack-nmt"
        if not (nmt_dir / "es_en" / "model" / "model.bin").is_file() or not (nmt_dir / "en_es" / "model" / "model.bin").is_file():
            self.skipTest("Modelos NMT offline (pack-nmt) no instalados")

        cfg = load_settings(ROOT)
        st = addons_status(cfg, ROOT)
        self.assertTrue(st["ctranslate2"])
        self.assertTrue(st["nmt_offline"])
        self.assertEqual(sorted(st["nmt_pairs"]), ["en_es", "es_en"])

        with tempfile.TemporaryDirectory(prefix="folio-nmt-test-") as td:
            work = Path(td)

            # 1. Documento nativo ES->EN con >45 bloques (sin truncamiento a 40), parrafo largo, MAYUSCULAS y datos preservados
            def _build_es_doc(doc: pdf.Document) -> None:
                p1 = doc.new_page(width=595, height=842)
                p1.insert_text((50, 60), "CONTRATO DE SERVICIOS PROFESIONALES", fontname="hebo", fontsize=14)
                p1.insert_text((50, 95), "El proveedor entregará el informe mensual al cliente", fontsize=11)
                p1.insert_text((50, 110), "antes del viernes sin cargos adicionales.", fontsize=11)
                p1.insert_text((50, 145), "contacto@empresa.org", fontsize=10)
                p2 = doc.new_page(width=595, height=842)
                for i in range(46):
                    row_y = 45 + (i % 23) * 32
                    col_x = 50 if i < 23 else 310
                    p2.insert_text((col_x, row_y), f"Cláusula número {i + 1}: pago seguro.", fontsize=9.5)

            es_src = work / "es_src.pdf"
            es_src.write_bytes(_pdf_bytes(_build_es_doc))
            res_es_en = handle_translate_layout(
                "translate_layout",
                [es_src],
                {"source_lang": "es", "target_lang": "en"},
                work,
                cfg,
                ROOT,
            )
            self.assertIn("motor=nmt_offline_es_en", res_es_en["notice"])
            with pdf.open(work / res_es_en["file"]) as out_en:
                t1 = out_en[0].get_text().replace("\xa0", " ")
                self.assertIn("CONTRACT", t1.upper())
                self.assertIn("monthly report", t1.lower())
                self.assertIn("contacto@empresa.org", t1)
                t2 = out_en[1].get_text().replace("\xa0", " ")
                self.assertIn("46", t2)
                self.assertNotIn("Cláusula número 46", t2)

            # 2. Traduccion EN->ES con tildes/eñe UTF-8 preservadas mediante fuente del sistema
            en_src = work / "en_src.pdf"
            en_src.write_bytes(_pdf_bytes(lambda d: (
                pg := d.new_page(),
                pg.insert_text((60, 90), "Electronic communication and technical information for Spain.", fontsize=12),
                pg.insert_text((60, 130), "The evaluation guarantees high resolution and data protection.", fontsize=12),
            )))
            res_en_es = handle_translate_layout(
                "translate_layout",
                [en_src],
                {"source_lang": "en", "target_lang": "es"},
                work,
                cfg,
                ROOT,
            )
            self.assertIn("motor=nmt_offline_en_es", res_en_es["notice"])
            with pdf.open(work / res_en_es["file"]) as out_es:
                t_es = out_es[0].get_text().replace("\xa0", " ")
                self.assertIn("comunicación", t_es.lower())
                self.assertIn("información", t_es.lower())

            # 3. PDF puramente escaneado (0 texto nativo) ES->EN usando OCR local + parche de fondo
            if capabilities(cfg, ROOT)["ocr"]:
                with pdf.open() as vec_scan:
                    sp = vec_scan.new_page(width=595, height=400)
                    sp.insert_text((60, 120), "Este documento es un contrato confidencial de servicios.", fontname="hebo", fontsize=15)
                    scan_png = sp.get_pixmap(dpi=200, colorspace=pdf.csRGB, alpha=False).tobytes("png")
                scan_pdf = work / "scan_es.pdf"
                with pdf.open() as img_doc:
                    ip = img_doc.new_page(width=595, height=400)
                    ip.insert_image(ip.rect, stream=scan_png)
                    img_doc.save(scan_pdf)

                res_scan = handle_translate_layout(
                    "translate_layout",
                    [scan_pdf],
                    {"source_lang": "es", "target_lang": "en"},
                    work,
                    cfg,
                    ROOT,
                )
                self.assertIn("OCR aplicado", res_scan["notice"])
                with pdf.open(work / res_scan["file"]) as out_scan:
                    txt_scan = out_scan[0].get_text().replace("\xa0", " ").lower()
                    self.assertIn("confidential", txt_scan)
                    self.assertIn("contract", txt_scan)

                # 4. PDF escaneado que ya traia capa OCR oculta (GlyphLessFont / render_mode=3)
                already_ocr = work / "already_ocr.pdf"
                with pdf.open(scan_pdf) as raw_img:
                    pix_ocr = raw_img[0].get_pixmap(dpi=200, colorspace=pdf.csRGB, alpha=False)
                    already_ocr.write_bytes(pix_ocr.pdfocr_tobytes(language=cfg["ocr_language"], tessdata=str(ROOT / "models")))
                res_reocr = handle_translate_layout(
                    "translate_layout",
                    [already_ocr],
                    {"source_lang": "es", "target_lang": "en"},
                    work,
                    cfg,
                    ROOT,
                )
                with pdf.open(work / res_reocr["file"]) as out_reocr:
                    txt_reocr = out_reocr[0].get_text().replace("\xa0", " ").lower()
                    self.assertIn("confidential", txt_reocr)
                    self.assertNotIn("confidencial", txt_reocr)

            # 5. Subproceso real worker.py (EN->ES) con CT2_USE_MKL=0 y ProcessTree
            sub_en_es = self.call(
                "translate_layout",
                [(en_src.read_bytes(), "en_sub.pdf")],
                {"source_lang": "en", "target_lang": "es"},
            )
            self.assertIn("nmt_offline_en_es", sub_en_es.headers["X-PDF-Notice"])
            with pdf.open(stream=sub_en_es.data, filetype="pdf") as sub_doc:
                self.assertIn("comunicación", sub_doc[0].get_text().replace("\xa0", " ").lower())

            # 6. Fallback seguro a glosario si un root aislado no tiene addons/pack-nmt
            from engines.typography_and_layout import _translate_offline_or_ai
            gloss_out, gloss_mode = _translate_offline_or_ai(["Factura"], "es", "en", {}, cfg, root=work)
            self.assertEqual(gloss_out, ["Invoice"])
            self.assertEqual(gloss_mode, "offline_glossary")
