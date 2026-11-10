from __future__ import annotations

import hashlib
import io
import json
import math
import re
import statistics
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import numpy as np
import pikepdf
import pymupdf as pdf

from pdf_engine import ProcessingError, check_size, open_pdf, save

TRACKING_QUERY_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "_hsenc", "_hsmi",
    "igshid", "si", "ref_src", "ref_url", "spm", "mkt_tok", "yclid", "wickedid",
})
TRACKING_PREFIXES = ("utm_", "hsa_", "oly_", "__hs")


def _sanitize_uri(uri: str) -> tuple[str, bool]:
    try:
        parts = urlsplit(uri.strip())
    except ValueError:
        return uri, False
    if parts.scheme.lower() not in ("http", "https"):
        return uri, False
    if not parts.query:
        return uri, False
    kept = []
    changed = False
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        lower = key.lower()
        if lower in TRACKING_QUERY_PARAMS or any(lower.startswith(pref) for pref in TRACKING_PREFIXES):
            changed = True
            continue
        kept.append((key, val))
    if not changed:
        return uri, False
    new_query = urlencode(kept, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)), True


def _detect_and_optionally_clean_printer_dots(doc_path: Path, apply_wash: bool) -> tuple[list[int], bytes | None]:
    """Heuristica en banda RGB/Y para micro-puntos amarillos o ruido cromatico periodico."""
    import cv2

    flagged_pages: list[int] = []
    washed_pdf: bytes | None = None
    with pdf.open(doc_path) as doc:
        out_doc = pdf.open() if apply_wash else None
        try:
            for index, page in enumerate(doc):
                if not page.get_images(full=False):
                    if out_doc is not None:
                        out_doc.insert_pdf(doc, from_page=index, to_page=index)
                    continue
                pix = page.get_pixmap(dpi=150, colorspace=pdf.csRGB, alpha=False)
                arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
                # Micro-puntos amarillos tipicos: R y G altos, B deprimido sobre fondo claro.
                r = arr[:, :, 0].astype(np.int16)
                g = arr[:, :, 1].astype(np.int16)
                b = arr[:, :, 2].astype(np.int16)
                bright = (r > 210) & (g > 210)
                yellow_dots = bright & ((r - b) > 35) & ((g - b) > 35) & (np.abs(r - g) < 30)
                dot_ratio = float(np.count_nonzero(yellow_dots)) / max(1, arr.shape[0] * arr.shape[1])
                if 0.0001 < dot_ratio < 0.05:
                    flagged_pages.append(index + 1)
                    if out_doc is not None:
                        neutral = ((r[yellow_dots] + g[yellow_dots]) // 2).astype(np.uint8)
                        arr[:, :, 2][yellow_dots] = neutral
                        buf = io.BytesIO()
                        from PIL import Image
                        Image.fromarray(arr).save(buf, format="PNG")
                        new_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
                        new_page.insert_image(new_page.rect, stream=buf.getvalue())
                        continue
                if out_doc is not None:
                    out_doc.insert_pdf(doc, from_page=index, to_page=index)
            if out_doc is not None and flagged_pages:
                washed_pdf = out_doc.tobytes(garbage=4, deflate=True)
        finally:
            if out_doc is not None:
                out_doc.close()
    return flagged_pages, washed_pdf


def handle_anti_track(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    password = str(options.get("password", ""))
    strip_external = bool(options.get("strip_external_uris", False))
    remove_beacons = bool(options.get("remove_beacons", True))
    neutralize_dots = bool(options.get("neutralize_printer_dots", False))
    include_report = bool(options.get("include_report", False))

    stats = {
        "javascript_removed": 0,
        "actions_removed": 0,
        "uri_params_cleaned": 0,
        "external_uris_stripped": 0,
        "beacons_removed": 0,
        "suspected_printer_dot_pages": [],
        "printer_dots_neutralized": False,
    }

    staged = folder / "anti_track_stage.pdf"
    try:
        with pikepdf.open(source, password=password) as pk:
            if not len(pk.pages) or (config["max_pages"] and len(pk.pages) > config["max_pages"]):
                raise ProcessingError("Numero de paginas fuera del limite configurado.")
            catalog = pk.Root
            for key in ("/OpenAction", "/AA", "/NeedsRendering"):
                if key in catalog:
                    del catalog[key]
                    stats["actions_removed"] += 1
            if "/Names" in catalog and isinstance(catalog["/Names"], pikepdf.Dictionary):
                names = catalog["/Names"]
                if "/JavaScript" in names:
                    del names["/JavaScript"]
                    stats["javascript_removed"] += 1
            if "/AcroForm" in catalog and isinstance(catalog["/AcroForm"], pikepdf.Dictionary):
                acro = catalog["/AcroForm"]
                for key in ("/AA", "/CO"):
                    if key in acro:
                        del acro[key]
                        stats["actions_removed"] += 1

            dangerous_actions = {"/JavaScript", "/Launch", "/SubmitForm", "/ImportData", "/GoToR", "/GoToE"}
            for page in pk.pages:
                if "/AA" in page:
                    del page["/AA"]
                    stats["actions_removed"] += 1

                if remove_beacons and "/Resources" in page and isinstance(page["/Resources"], pikepdf.Dictionary):
                    res = page["/Resources"]
                    if "/XObject" in res and isinstance(res["/XObject"], pikepdf.Dictionary):
                        xobjs = res["/XObject"]
                        to_del = []
                        for name, obj in xobjs.items():
                            try:
                                if isinstance(obj, pikepdf.Stream) and obj.get("/Subtype") == pikepdf.Name("/Image"):
                                    w = int(obj.get("/Width", 999))
                                    h = int(obj.get("/Height", 999))
                                    if w <= 2 and h <= 2:
                                        to_del.append(name)
                            except (ValueError, TypeError):
                                continue
                        for name in to_del:
                            del xobjs[name]
                            stats["beacons_removed"] += 1

                annots = page.get("/Annots")
                if isinstance(annots, pikepdf.Array):
                    kept_annots = []
                    for annot_ref in annots:
                        annot = annot_ref
                        if "/AA" in annot:
                            del annot["/AA"]
                            stats["actions_removed"] += 1
                        action = annot.get("/A")
                        drop_annot = False
                        if isinstance(action, pikepdf.Dictionary):
                            stype = str(action.get("/S", ""))
                            if stype in dangerous_actions or "/JS" in action:
                                if stype == "/JavaScript" or "/JS" in action:
                                    stats["javascript_removed"] += 1
                                else:
                                    stats["actions_removed"] += 1
                                del annot["/A"]
                            elif stype == "/URI" and "/URI" in action:
                                raw_uri = str(action["/URI"])
                                if strip_external and raw_uri.lower().startswith(("http://", "https://")):
                                    del annot["/A"]
                                    stats["external_uris_stripped"] += 1
                                else:
                                    cleaned, modified = _sanitize_uri(raw_uri)
                                    if modified:
                                        action["/URI"] = pikepdf.String(cleaned)
                                        stats["uri_params_cleaned"] += 1
                        # Rectangulo invisible 2x2 pt usado como pixel tracker
                        rect = annot.get("/Rect")
                        if remove_beacons and isinstance(rect, pikepdf.Array) and len(rect) == 4:
                            try:
                                rw = abs(float(rect[2]) - float(rect[0]))
                                rh = abs(float(rect[3]) - float(rect[1]))
                                if rw <= 2.5 and rh <= 2.5 and annot.get("/Subtype") == pikepdf.Name("/Link"):
                                    drop_annot = True
                                    stats["beacons_removed"] += 1
                            except (ValueError, TypeError):
                                pass
                        if not drop_annot:
                            kept_annots.append(annot)
                    page["/Annots"] = pk.make_indirect(pikepdf.Array(kept_annots)) if isinstance(page.get("/Annots"), pikepdf.Object) and page.get("/Annots").is_indirect else pikepdf.Array(kept_annots)

            pk.save(staged, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    except (pikepdf.PdfError, pikepdf.PasswordError):
        raise ProcessingError("No se pudo abrir el PDF para purga anti-rastreo. Verifique archivo y clave.") from None

    flagged, washed_bytes = _detect_and_optionally_clean_printer_dots(staged, apply_wash=neutralize_dots)
    stats["suspected_printer_dot_pages"] = flagged
    output_pdf = folder / "anti_tracking.pdf"
    if washed_bytes is not None:
        output_pdf.write_bytes(washed_bytes)
        stats["printer_dots_neutralized"] = True
    else:
        staged.replace(output_pdf)
    staged.unlink(missing_ok=True)

    notice = (
        f"Purga anti-rastreo: JS eliminados={stats['javascript_removed']}, "
        f"acciones={stats['actions_removed']}, parametros tracking={stats['uri_params_cleaned']}, "
        f"enlaces externos eliminados={stats['external_uris_stripped']}, balizas={stats['beacons_removed']}."
    )
    if flagged:
        notice += f" Paginas con patron cromatico sospechoso de micro-puntos: {flagged}."

    if include_report:
        bundle = folder / "anti_tracking.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(output_pdf, "documento-limpio.pdf")
            archive.writestr("auditoria-anti-tracking.json", json.dumps(stats, ensure_ascii=False, indent=2))
        return {"file": bundle.name, "notice": notice}
    return {"file": output_pdf.name, "notice": notice}


def handle_forensic_sanitize(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    password = str(options.get("password", ""))
    redactions = options.get("redactions", []) or []
    redact_patterns = options.get("redact_patterns", []) or []
    preserve_ocr = bool(options.get("preserve_ocr", False))
    purge_invisible = bool(options.get("purge_invisible_text", not preserve_ocr))
    purge_annotations = bool(options.get("purge_annotations", True))
    purge_hidden_layers = bool(options.get("purge_hidden_layers", True))
    verify_terms = [str(t) for t in (options.get("verify_terms") or []) if str(t).strip()]
    include_report = bool(options.get("include_report", False))

    if not isinstance(redactions, list) or len(redactions) > 500:
        raise ProcessingError("Lista de redacciones no valida (maximo 500).", 400)
    if not isinstance(redact_patterns, list) or len(redact_patterns) > 50:
        raise ProcessingError("Lista de patrones a censurar no valida (maximo 50).", 400)

    compiled_patterns = []
    for raw_pat in redact_patterns:
        pat = str(raw_pat)
        if not pat or len(pat) > 300:
            raise ProcessingError("Patron regex vacio o demasiado largo.", 400)
        try:
            compiled_patterns.append(re.compile(pat))
        except re.error as error:
            raise ProcessingError(f"Expresion regular invalida: {error}", 400) from None

    stats = {
        "explicit_redactions": 0,
        "pattern_redactions": 0,
        "invisible_traces_removed": 0,
        "annotations_removed": 0,
        "embedded_files_removed": 0,
        "pieceinfo_stripped": 0,
        "thumbnails_stripped": 0,
        "hidden_layers_purged": 0,
        "eof_markers_after": 1,
        "verified_terms_absent": {},
    }

    stage_mu = folder / "forensic_mu.pdf"
    with open_pdf(source, password, config["max_pages"]) as doc:
        for entry in redactions:
            if not isinstance(entry, dict) or "page" not in entry or "bbox" not in entry:
                raise ProcessingError("Cada redaccion requiere 'page' y 'bbox'.", 400)
            pno = int(entry["page"]) - 1
            if not 0 <= pno < len(doc):
                raise ProcessingError("Pagina de redaccion fuera de rango.")
            bbox = entry["bbox"]
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                raise ProcessingError("Coordenadas de redaccion invalidas.")
            rect = pdf.Rect([float(v) for v in bbox])
            if rect.is_empty or not doc[pno].rect.contains(rect):
                raise ProcessingError("La caja de redaccion debe estar dentro de la pagina.")
            doc[pno].add_redact_annot(rect, fill=(0, 0, 0))
            stats["explicit_redactions"] += 1

        if compiled_patterns:
            for page in doc:
                text_dict = page.get_text("dict")
                for block in text_dict.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            txt = span.get("text", "")
                            if any(p.search(txt) for p in compiled_patterns):
                                page.add_redact_annot(pdf.Rect(span["bbox"]), fill=(0, 0, 0))
                                stats["pattern_redactions"] += 1

        if purge_invisible and not preserve_ocr:
            for page in doc:
                for trace in page.get_texttrace():
                    if trace.get("type") == 3 or trace.get("opacity", 1) == 0:
                        page.add_redact_annot(pdf.Rect(trace["bbox"]), fill=False, cross_out=False)
                        stats["invisible_traces_removed"] += 1

        for page in doc:
            if list(page.annots() or []):
                page.apply_redactions(images=2, graphics=1, text=pdf.PDF_REDACT_TEXT_REMOVE)
            if purge_annotations:
                for annot in list(page.annots() or []):
                    page.delete_annot(annot)
                    stats["annotations_removed"] += 1

        stats["embedded_files_removed"] = doc.embfile_count()
        for idx in range(doc.embfile_count() - 1, -1, -1):
            doc.embfile_del(idx)
        doc.set_metadata({})
        doc.del_xml_metadata()
        save(doc, stage_mu, clean=True)

    output_pdf = folder / "saneado_forense.pdf"
    try:
        with pikepdf.open(stage_mu) as src_pk:
            rebuilt = pikepdf.Pdf.new()
            rebuilt.pages.extend(src_pk.pages)
            # Limpiar rastros COS privados por catalogo y por pagina
            for key in ("/PieceInfo", "/SpiderInfo", "/Metadata", "/OpenAction", "/AA", "/EmbeddedFiles"):
                if key in rebuilt.Root:
                    del rebuilt.Root[key]
                    if key == "/PieceInfo":
                        stats["pieceinfo_stripped"] += 1
            if purge_hidden_layers and "/OCProperties" in rebuilt.Root:
                del rebuilt.Root["/OCProperties"]
                stats["hidden_layers_purged"] += 1
            for page in rebuilt.pages:
                if "/PieceInfo" in page:
                    del page["/PieceInfo"]
                    stats["pieceinfo_stripped"] += 1
                if "/Thumb" in page:
                    del page["/Thumb"]
                    stats["thumbnails_stripped"] += 1
                if "/Metadata" in page:
                    del page["/Metadata"]
                if "/AA" in page:
                    del page["/AA"]
            rebuilt.save(output_pdf, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    except pikepdf.PdfError:
        raise ProcessingError("No se pudo reconstruir el arbol COS durante la desinfeccion.") from None
    finally:
        stage_mu.unlink(missing_ok=True)

    raw_bytes = output_pdf.read_bytes()
    stats["eof_markers_after"] = raw_bytes.count(b"%%EOF")
    with open_pdf(output_pdf, "", config["max_pages"]) as verified_doc:
        full_text = "\n".join(p.get_text() for p in verified_doc)
    for term in verify_terms:
        absent_raw = term.encode("utf-8", errors="ignore") not in raw_bytes
        absent_text = term not in full_text
        stats["verified_terms_absent"][term] = bool(absent_raw and absent_text)

    notice = (
        f"Desinfeccion forense completa: revision unica (%%EOF={stats['eof_markers_after']}), "
        f"redacciones={stats['explicit_redactions'] + stats['pattern_redactions']}, "
        f"trazos ocultos={stats['invisible_traces_removed']}, "
        f"anotaciones={stats['annotations_removed']}, adjuntos={stats['embedded_files_removed']}."
    )
    if include_report:
        bundle = folder / "desinfeccion-forense.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(output_pdf, "documento-saneado.pdf")
            archive.writestr("informe-forense.json", json.dumps(stats, ensure_ascii=False, indent=2))
        return {"file": bundle.name, "notice": notice}
    return {"file": output_pdf.name, "notice": notice}


def _shingles(text: str, k: int = 5) -> set[str]:
    words = re.findall(r"\b[\wáéíóúüñ]+\b", text.lower())
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def _extract_revisions(raw: bytes) -> list[dict]:
    positions = [m.end() for m in re.finditer(rb"%%EOF\r?\n?", raw)]
    if not positions:
        positions = [len(raw)]
    revisions = []
    prev_end = 0
    for idx, end in enumerate(positions, 1):
        slice_bytes = raw[:end]
        trailer_snippet = raw[max(0, end - 600):end]
        sig_flag = b"/Type /Sig" in raw[prev_end:end] or b"/ByteRange" in raw[prev_end:end]
        revisions.append({
            "revision": idx,
            "byte_end": end,
            "delta_bytes": end - prev_end,
            "sha256_prefix": hashlib.sha256(slice_bytes).hexdigest()[:16],
            "contains_signature_object": sig_flag,
            "has_xmp_delta": b"xmpmeta" in raw[prev_end:end] or b"/Metadata" in trailer_snippet,
        })
        prev_end = end
    return revisions


def _stylometry_metrics(text: str) -> dict:
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if len(s.strip()) > 3]
    words = re.findall(r"\b[\wáéíóúüñ]+\b", text.lower())
    if not words:
        return {"word_count": 0, "warning": "Sin texto extraible para estilometria."}
    sent_lengths = [len(re.findall(r"\b\w+\b", s)) for s in sentences] or [len(words)]
    mean_len = statistics.mean(sent_lengths)
    stdev_len = statistics.pstdev(sent_lengths) if len(sent_lengths) > 1 else 0.0
    freq = Counter(words)
    ttr = len(freq) / len(words)
    hapax = sum(1 for _, c in freq.items() if c == 1) / len(freq)
    total_chars = max(1, len(text))
    char_freq = Counter(text)
    entropy = -sum((c / total_chars) * math.log2(c / total_chars) for c in char_freq.values())
    return {
        "word_count": len(words),
        "sentence_count": len(sentences),
        "avg_sentence_words": round(mean_len, 2),
        "sentence_length_stdev": round(stdev_len, 2),
        "type_token_ratio": round(ttr, 4),
        "hapax_ratio": round(hapax, 4),
        "char_entropy_bits": round(entropy, 3),
        "interpretation": (
            "Metricas orientativas unicamente. Una baja varianza oracional puede darse tambien en textos "
            "tecnicos, legales o plantillas humanas; NUNCA constituye prueba concluyente de autoria IA."
        ),
    }


def _citation_audit(text: str) -> dict:
    inline_nums = {int(n) for grp in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", text) for n in grp.split(",")}
    inline_dois = set(re.findall(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text))
    # Buscar seccion de referencias al final
    ref_match = re.search(r"\n(?:Referencias|References|Bibliograf[ií]a)\b", text, re.IGNORECASE)
    ref_text = text[ref_match.start():] if ref_match else ""
    declared_nums = {int(m) for m in re.findall(r"(?m)^\[(\d+)\]", ref_text)}
    dangling_nums = sorted(inline_nums - declared_nums)
    uncited_nums = sorted(declared_nums - inline_nums) if declared_nums else []
    return {
        "inline_numeric_citations": sorted(inline_nums),
        "declared_bibliography_numbers": sorted(declared_nums),
        "dangling_citations": dangling_nums,
        "uncited_references": uncited_nums,
        "dois_detected": sorted(inline_dois),
    }


def handle_forensic_audit(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    from advanced_tools import signature_report
    from extended_tools import report_pdf

    primary = sources[0]
    if primary.suffix.lower() != ".pdf":
        raise ProcessingError("El primer archivo debe ser el PDF principal a auditar.")
    password = str(options.get("password", ""))
    output_format = str(options.get("format", "zip"))

    raw = primary.read_bytes()
    revisions = _extract_revisions(raw)
    sig_data = None
    try:
        sig_data = signature_report(primary)
    except ProcessingError as err:
        sig_data = {"modo": "offline", "firmas": [], "nota": str(err)}

    with open_pdf(primary, password, config["max_pages"]) as doc:
        primary_meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        primary_text = "\n".join(page.get_text(sort=True) for page in doc)
        page_count = len(doc)

    # Comparacion local con corpus adicional si fue cargado
    corpus_comparisons = []
    primary_shingles = _shingles(primary_text, k=5)
    for idx, corpus_path in enumerate(sources[1:], 2):
        if corpus_path.suffix.lower() == ".pdf":
            with open_pdf(corpus_path, password, config["max_pages"]) as cdoc:
                ctext = "\n".join(p.get_text(sort=True) for p in cdoc)
        else:
            ctext = corpus_path.read_text(encoding="utf-8", errors="ignore")
        cshingles = _shingles(ctext, k=5)
        overlap = primary_shingles & cshingles
        union = primary_shingles | cshingles
        jaccard = len(overlap) / len(union) if union else 0.0
        containment = len(overlap) / len(primary_shingles) if primary_shingles else 0.0
        corpus_comparisons.append({
            "corpus_index": idx,
            "shared_5grams": len(overlap),
            "jaccard_similarity": round(jaccard, 4),
            "containment_ratio": round(containment, 4),
            "sample_matches": sorted(overlap)[:10],
        })

    audit = {
        "chain_of_custody": {
            "pages": page_count,
            "file_sha256": hashlib.sha256(raw).hexdigest(),
            "revision_count": len(revisions),
            "revisions": revisions,
            "metadata_present": primary_meta,
            "signatures": sig_data,
        },
        "citations": _citation_audit(primary_text),
        "local_corpus_overlap": corpus_comparisons,
        "stylometry": _stylometry_metrics(primary_text),
        "disclaimer": (
            "Auditoria tecnica 100% offline. Las metricas de similitud solo comparan contra el corpus "
            "cargado en esta sesion. Los indicadores estilometricos NO constituyen prueba legal ni certeza de autoria IA."
        ),
    }

    if output_format == "json":
        out_json = folder / "auditoria-custodia.json"
        out_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "file": out_json.name,
            "notice": f"Auditoria completada: {len(revisions)} revisiones, {len(corpus_comparisons)} comparaciones de corpus local.",
        }

    bundle = folder / "auditoria-custodia.zip"
    report_lines = [
        "INFORME DE AUDITORIA FORENSE, CADENA DE CUSTODIA Y ESTILOMETRIA (OFFLINE)",
        f"Revisiones incrementales (%%EOF): {len(revisions)}",
        f"Firmas digitales detectadas: {len(sig_data.get('firmas', []))}",
        f"Palabras extraibles: {audit['stylometry'].get('word_count', 0)}",
        f"Citas huerfanas: {audit['citations']['dangling_citations']}",
        "",
        "ADVERTENCIA: La estilometria estadistica es solo orientativa y no certifica autoria humana o de IA.",
    ]
    for rev in revisions:
        report_lines.append(
            f"Revision {rev['revision']}: delta={rev['delta_bytes']}B hash={rev['sha256_prefix']} firma={rev['contains_signature_object']}"
        )
    for comp in corpus_comparisons:
        report_lines.append(
            f"Corpus #{comp['corpus_index']}: similitud Jaccard={comp['jaccard_similarity']} ({comp['shared_5grams']} 5-gramas)"
        )
    pdf_report = folder / "informe-custodia.pdf"
    report_pdf(report_lines, pdf_report, config)
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("auditoria-custodia.json", json.dumps(audit, ensure_ascii=False, indent=2))
        archive.write(pdf_report, "informe-custodia.pdf")
    return {
        "file": bundle.name,
        "notice": f"Auditoria completa: {len(revisions)} revisiones detectadas, {len(sig_data.get('firmas', []))} firmas.",
    }
