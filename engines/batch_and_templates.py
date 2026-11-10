from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import re
import shutil
import zipfile
from pathlib import Path

import pymupdf as pdf

from acrobat_tools import parse_color, resolve_font
from engines.forensics import handle_anti_track, handle_forensic_sanitize
from engines.vectors_and_tables import _fit_text_in_box, handle_semantic_replace
from extended_tools import report_pdf
from pdf_engine import ProcessingError, check_size, open_pdf, save


def _safe_slug(name: str, fallback: str = "doc") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._")
    cleaned = re.sub(r"\s+", "-", cleaned)
    return (cleaned[:80] or fallback)


def _safe_rel_path(raw_path: str, fallback_name: str) -> str:
    parts = [p for p in re.split(r"[/\\]+", raw_path.strip()) if p and p not in (".", "..")]
    safe_parts = [_safe_slug(p, "item") for p in parts[:-1]]
    leaf = _safe_slug(Path(parts[-1]).stem if parts else fallback_name, fallback_name) + ".pdf"
    return "/".join([*safe_parts, leaf])


def _doc_context_tokens(doc: pdf.Document, source_label: str, rule_match: str = "") -> dict[str, str]:
    first_text = doc[0].get_text(sort=True) if len(doc) else ""
    date_m = re.search(r"\b(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})\b", first_text)
    id_m = re.search(r"\b((?:FAC|INV|CON|CTR|ORD|EXP|DOC)[-_ ]?\d{2,10}(?:[-_][A-Za-z0-9]+)*)\b", first_text, re.IGNORECASE)
    meta_title = (doc.metadata or {}).get("title") or ""
    return {
        "source": _safe_slug(Path(source_label).stem, "archivo"),
        "title": _safe_slug(meta_title, _safe_slug(Path(source_label).stem, "documento")),
        "date": (date_m.group(1).replace("/", "-") if date_m else "sin-fecha"),
        "doc_id": (_safe_slug(id_m.group(1)) if id_m else "SN"),
        "match": _safe_slug(rule_match, "general"),
        "pages": str(len(doc)),
    }


def handle_pipeline_run(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    pipeline = options.get("pipeline")
    if pipeline is None:
        pipeline = options
    if not isinstance(pipeline, dict):
        raise ProcessingError("Configuracion de pipeline no valida.", 400)

    contextual_names = bool(options.get("contextual_names", pipeline.get("contextual_names", False)))
    source_labels = options.get("source_labels") or []
    split_regex = str(pipeline.get("split_by_regex", "")).strip()
    split_compiled = None
    if split_regex:
        if len(split_regex) > 300:
            raise ProcessingError("Expresion regex de division demasiado larga.", 400)
        try:
            split_compiled = re.compile(split_regex, re.IGNORECASE)
        except re.error as err:
            raise ProcessingError(f"Regex de division invalida: {err}", 400) from None

    routes = pipeline.get("routes", []) or []
    transforms = pipeline.get("transforms", []) or []
    if not isinstance(routes, list) or len(routes) > 30:
        raise ProcessingError("Lista de reglas de enrutamiento no valida.", 400)
    if not isinstance(transforms, list) or len(transforms) > 15:
        raise ProcessingError("Lista de transformaciones no valida.", 400)

    password = str(options.get("password", ""))
    bundle = folder / "pipeline_resultado.zip"
    manifest_entries: list[dict] = []
    used_zip_names: set[str] = set()
    produced_count = 0

    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for src_idx, src_path in enumerate(sources, 1):
            label = str(source_labels[src_idx - 1]) if src_idx - 1 < len(source_labels) else f"lote-{src_idx:03d}.pdf"
            work_dir = folder / f"pipe-{src_idx:03d}"
            work_dir.mkdir(exist_ok=True)
            try:
                with open_pdf(src_path, password, config["max_pages"]) as doc:
                    # 1. Calcular segmentos (split_by_regex opcional)
                    segments: list[tuple[int, int, str]] = []
                    if split_compiled is not None:
                        starts = []
                        for pno in range(len(doc)):
                            m = split_compiled.search(doc[pno].get_text())
                            if m:
                                starts.append((pno, m.group(1) if m.groups() else m.group(0)))
                        if not starts:
                            segments = [(0, len(doc) - 1, "")]
                        else:
                            if starts[0][0] != 0:
                                starts.insert(0, (0, "portada"))
                            for idx_s, (s_page, hit_tok) in enumerate(starts):
                                end_page = (starts[idx_s + 1][0] - 1) if idx_s + 1 < len(starts) else (len(doc) - 1)
                                segments.append((s_page, end_page, hit_tok))
                    else:
                        segments = [(0, len(doc) - 1, "")]

                    for seg_idx, (p_start, p_end, hit_tok) in enumerate(segments, 1):
                        if produced_count >= config["max_batch_files"] * 4:
                            raise ProcessingError("El pipeline supero el maximo de subdocumentos por sesion.")
                        sub_path = work_dir / f"seg-{seg_idx:03d}.pdf"
                        with pdf.open() as sub_doc:
                            sub_doc.insert_pdf(doc, from_page=p_start, to_page=p_end)
                            save(sub_doc, sub_path)
                            full_seg_text = "\n".join(p.get_text() for p in sub_doc)
                            has_text = bool(full_seg_text.strip())
                            seg_pages = len(sub_doc)
                            ctx = _doc_context_tokens(sub_doc, label, hit_tok)
                            ctx["index"] = f"{produced_count + 1:03d}"
                            ctx["start_page"] = str(p_start + 1)
                            ctx["end_page"] = str(p_end + 1)

                        # 2. Aplicar transformaciones secuenciales configuradas
                        applied_transforms: list[str] = []
                        current_pdf = sub_path
                        for t_idx, step in enumerate(transforms):
                            if not isinstance(step, dict):
                                continue
                            kind = str(step.get("op") or step.get("type") or "").lower()
                            step_dir = work_dir / f"step-{seg_idx:03d}-{t_idx:02d}"
                            step_dir.mkdir(exist_ok=True)
                            if kind == "anti_track":
                                res = handle_anti_track("anti_track", [current_pdf], step, step_dir, config, root)
                                next_pdf = step_dir / res["file"]
                                current_pdf = work_dir / f"cur-{seg_idx}-{t_idx}.pdf"
                                shutil.move(next_pdf, current_pdf)
                                applied_transforms.append("anti_track")
                            elif kind == "forensic_sanitize":
                                res = handle_forensic_sanitize("forensic_sanitize", [current_pdf], step, step_dir, config, root)
                                next_pdf = step_dir / res["file"]
                                current_pdf = work_dir / f"cur-{seg_idx}-{t_idx}.pdf"
                                shutil.move(next_pdf, current_pdf)
                                applied_transforms.append("forensic_sanitize")
                            elif kind == "semantic_replace":
                                res = handle_semantic_replace("semantic_replace", [current_pdf], step, step_dir, config, root)
                                next_pdf = step_dir / res["file"]
                                current_pdf = work_dir / f"cur-{seg_idx}-{t_idx}.pdf"
                                shutil.move(next_pdf, current_pdf)
                                applied_transforms.append("semantic_replace")
                            elif kind == "watermark":
                                wtext = str(step.get("text", "")).strip()
                                if wtext:
                                    with open_pdf(current_pdf, "", config["max_pages"]) as wdoc:
                                        for pg in wdoc:
                                            pg.insert_textbox(
                                                pdf.Rect(20, pg.rect.height / 2 - 25, pg.rect.width - 20, pg.rect.height / 2 + 45),
                                                wtext[:100], fontsize=22, color=(0.4, 0.4, 0.4), align=1, overlay=True, fill_opacity=0.35,
                                            )
                                        next_pdf = work_dir / f"cur-{seg_idx}-{t_idx}.pdf"
                                        save(wdoc, next_pdf)
                                        current_pdf = next_pdf
                                    applied_transforms.append("watermark")
                            elif kind == "compress":
                                with open_pdf(current_pdf, "", config["max_pages"]) as cdoc:
                                    next_pdf = work_dir / f"cur-{seg_idx}-{t_idx}.pdf"
                                    save(cdoc, next_pdf, clean=True)
                                    current_pdf = next_pdf
                                applied_transforms.append("compress")

                        # 3. Enrutamiento por reglas
                        matched_folder = str(pipeline.get("default_folder", "Procesados"))
                        name_template = str(pipeline.get("default_name_template", "{folder}/{index}_{source}.pdf"))
                        matched_rule_name = "default"
                        for r_idx, rule in enumerate(routes, 1):
                            if not isinstance(rule, dict):
                                continue
                            cond = rule.get("when", {}) if isinstance(rule.get("when"), dict) else rule
                            ok = True
                            if cond.get("match_regex"):
                                try:
                                    rm = re.search(str(cond["match_regex"]), full_seg_text, re.IGNORECASE)
                                except re.error as err:
                                    raise ProcessingError(f"Regex de regla invalida: {err}", 400) from None
                                if not rm:
                                    ok = False
                                elif rm.groups():
                                    ctx["rule_capture"] = _safe_slug(rm.group(1), ctx["match"])
                            if ok and cond.get("contains_text"):
                                if str(cond["contains_text"]).lower() not in full_seg_text.lower():
                                    ok = False
                            if ok and "min_pages" in cond:
                                if seg_pages < int(cond["min_pages"]):
                                    ok = False
                            if ok and cond.get("is_scanned") is True:
                                if has_text:
                                    ok = False
                            if ok:
                                matched_folder = str(rule.get("folder", matched_folder))
                                name_template = str(rule.get("name_template", name_template))
                                matched_rule_name = str(rule.get("name", f"regla-{r_idx}"))
                                break

                        ctx["folder"] = _safe_slug(matched_folder, "Procesados")
                        try:
                            formatted = name_template.format(**ctx)
                        except KeyError:
                            formatted = f"{ctx['folder']}/{ctx['index']}_{ctx['source']}.pdf"
                        rel_target = _safe_rel_path(formatted, f"doc-{produced_count + 1:03d}")
                        while rel_target in used_zip_names:
                            stem = Path(rel_target).stem
                            parent = str(Path(rel_target).parent)
                            suffix_name = f"{stem}_{produced_count + 1}.pdf"
                            rel_target = f"{parent}/{suffix_name}" if parent != "." else suffix_name
                        used_zip_names.add(rel_target)

                        archive.write(current_pdf, rel_target, compress_type=zipfile.ZIP_STORED)
                        produced_count += 1
                        manifest_entries.append({
                            "index": produced_count,
                            "source_index": src_idx,
                            "pages": f"{p_start + 1}-{p_end + 1}",
                            "rule": matched_rule_name,
                            "transforms": applied_transforms,
                            "output_path": rel_target if contextual_names else f"EVA00_{produced_count:02d}.pdf",
                        })
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)
            check_size(bundle, config)

        manifest_name = "MANIFIESTO_PIPELINE.json"
        archive.writestr(
            manifest_name,
            json.dumps(
                {
                    "contextual_names_enabled": contextual_names,
                    "total_inputs": len(sources),
                    "total_outputs": produced_count,
                    "items": manifest_entries,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    notice = (
        f"Pipeline completado: {len(sources)} entrada(s) -> {produced_count} documento(s) generados"
        + (" con nombres contextuales por carpeta." if contextual_names else " en EVA00.zip.")
    )
    return {
        "file": bundle.name,
        "notice": notice,
        "preserve_pipeline_structure": contextual_names,
    }


def handle_template_detect(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    password = str(options.get("password", ""))
    field_patterns = [
        ("placeholder_braces", re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")),
        ("placeholder_brackets", re.compile(r"\[\[([A-Za-z0-9_.-]+)\]\]|\[([A-Z0-9_]{2,30})\]")),
        ("placeholder_underscores", re.compile(r"_{4,}")),
        ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
        ("date", re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{2}[/-]\d{2}[/-]\d{4})\b")),
        ("currency", re.compile(r"(?:USD|EUR|COP|MXN|\$|€)\s*\d[\d.,]*")),
    ]
    detected_fields: list[dict] = []
    seen_keys: dict[str, int] = {}

    with open_pdf(source, password, config["max_pages"]) as doc:
        for pno, page in enumerate(doc, 1):
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        txt = span.get("text", "")
                        if not txt.strip():
                            continue
                        for kind, rx in field_patterns:
                            for m in rx.finditer(txt):
                                raw_tok = m.group(0)
                                cand = next((g for g in m.groups() if g), None)
                                if cand:
                                    field_name = re.sub(r"\W+", "_", cand).strip("_").lower()
                                else:
                                    seen_keys[kind] = seen_keys.get(kind, 0) + 1
                                    field_name = f"{kind}_{seen_keys[kind]}"
                                detected_fields.append({
                                    "field": field_name,
                                    "kind": kind,
                                    "token": raw_tok,
                                    "page": pno,
                                    "bbox": [round(float(v), 2) for v in span["bbox"]],
                                    "font": str(span.get("font", "Arial")).split("+")[-1],
                                    "size": round(float(span.get("size", 10.0)), 2),
                                    "color": f"#{int(span.get('color', 0)) & 0xFFFFFF:06x}",
                                    "span_text": txt,
                                })

    out_json = folder / "esquema_plantilla.json"
    unique_columns = list(dict.fromkeys(f["field"] for f in detected_fields))
    out_json.write_text(
        json.dumps(
            {"columns": unique_columns, "fields": detected_fields},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "file": out_json.name,
        "notice": f"Plantilla detectada: {len(detected_fields)} campos en {len(unique_columns)} columnas.",
    }


def _load_template_rows(data_path: Path, max_rows: int) -> tuple[list[dict[str, str]], list[dict] | None]:
    suffix = data_path.suffix.lower()
    if suffix == ".json":
        try:
            parsed = json.loads(data_path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProcessingError("El archivo JSON de registros no es valido.") from None
        fields_meta = None
        if isinstance(parsed, dict):
            fields_meta = parsed.get("fields")
            rows = parsed.get("rows", [])
        elif isinstance(parsed, list):
            rows = parsed
        else:
            raise ProcessingError("El JSON debe contener una lista de filas.")
        if not isinstance(rows, list) or not rows:
            raise ProcessingError("No hay registros para compilar.")
        if len(rows) > max_rows:
            raise ProcessingError(f"Limite maximo excedido: {max_rows} registros por lote.")
        return [{str(k): str(v) for k, v in r.items()} for r in rows if isinstance(r, dict)], fields_meta

    raw_text = data_path.read_text(encoding="utf-8-sig", errors="replace")
    sample = raw_text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(raw_text), delimiter=delimiter)
    rows = []
    for row in reader:
        rows.append({str(k).strip(): str(v or "") for k, v in row.items() if k is not None})
        if len(rows) > max_rows:
            raise ProcessingError(f"El CSV supera el limite de {max_rows} filas por lote.")
    if not rows:
        raise ProcessingError("El archivo CSV no contiene filas de datos.")
    return rows, None


def handle_template_compile(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    tpl_pdf = next((p for p in sources if p.suffix.lower() == ".pdf"), None)
    data_file = next((p for p in sources if p.suffix.lower() in (".csv", ".json")), None)
    if tpl_pdf is None or data_file is None:
        raise ProcessingError("Suba primero la plantilla PDF y luego el archivo CSV o JSON de datos.", 400)

    password = str(options.get("password", ""))
    max_rows = min(200, max(10, int(config.get("max_batch_files", 50))))
    rows, embedded_fields = _load_template_rows(data_file, max_rows=max_rows)
    explicit_fields = options.get("fields") or embedded_fields or []
    tpl_bytes = tpl_pdf.read_bytes()

    bundle = folder / "plantillas_compiladas.zip"
    manifest: list[dict] = []

    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for idx, row in enumerate(rows, 1):
            with pdf.open(stream=tpl_bytes, filetype="pdf") as doc:
                if doc.needs_pass and not doc.authenticate(password):
                    raise ProcessingError("La plantilla esta protegida; clave incorrecta.")
                if config["max_pages"] and len(doc) > config["max_pages"]:
                    raise ProcessingError("La plantilla excede el limite de paginas.")

                # 1. Reemplazos por cajas explicitas (si fueron provistas)
                page_boxes: dict[int, list[dict]] = {}
                for fdef in explicit_fields:
                    if not isinstance(fdef, dict):
                        continue
                    fname = str(fdef.get("field", ""))
                    if fname not in row:
                        continue
                    pno = int(fdef.get("page", 1)) - 1
                    if 0 <= pno < len(doc) and "bbox" in fdef:
                        page_boxes.setdefault(pno, []).append({
                            "bbox": [float(v) for v in fdef["bbox"]],
                            "value": row[fname],
                            "font": str(fdef.get("font", "Arial")),
                            "size": float(fdef.get("size", 10.0)),
                            "color": str(fdef.get("color", "#000000")),
                        })

                for pno, page in enumerate(doc):
                    if page.rotation:
                        raise ProcessingError("Quite la rotacion de la plantilla antes de compilar.")
                    ops = list(page_boxes.get(pno, []))
                    # 2. Tambien detectar {{columna}} o [COLUMNA] directamente en los spans
                    for block in page.get_text("dict").get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                txt = span.get("text", "")
                                updated = txt
                                for col_key, col_val in row.items():
                                    for marker in (f"{{{{{col_key}}}}}", f"[{col_key}]", f"[{col_key.upper()}]", f"[[{col_key}]]"):
                                        if marker in updated:
                                            updated = updated.replace(marker, col_val)
                                if updated != txt:
                                    ops.append({
                                        "bbox": list(span["bbox"]),
                                        "value": updated,
                                        "font": str(span.get("font", "Arial")).split("+")[-1],
                                        "size": float(span.get("size", 10.0)),
                                        "color": f"#{int(span.get('color', 0)) & 0xFFFFFF:06x}",
                                    })
                    if not ops:
                        continue
                    for item in ops:
                        rect = pdf.Rect(item["bbox"]) & page.rect
                        if not rect.is_empty:
                            page.add_redact_annot(rect, fill=False, cross_out=False)
                    page.apply_redactions(images=0, graphics=0, text=pdf.PDF_REDACT_TEXT_REMOVE)
                    for item in ops:
                        rect = pdf.Rect(item["bbox"]) & page.rect
                        if rect.is_empty:
                            continue
                        font_code = resolve_font(page, item["font"])
                        color = parse_color(item["color"])
                        _fit_text_in_box(page, rect, item["value"], font_code, item["size"], color)

                pdf_name = f"registro-{idx:03d}.pdf"
                archive.writestr(pdf_name, doc.tobytes(garbage=4, deflate=True))
                manifest.append({"index": idx, "file": pdf_name, "row": row})
            check_size(bundle, config)
        archive.writestr("manifiesto-lote.json", json.dumps({"items": manifest}, ensure_ascii=False, indent=2))

    return {
        "file": bundle.name,
        "notice": f"Plantilla inversa compilada: {len(rows)} documentos generados desde tabla de datos.",
    }


def _doc_paragraphs(doc: pdf.Document) -> list[dict]:
    paras: list[dict] = []
    for pno, page in enumerate(doc):
        blocks = page.get_text("blocks") or []
        blocks.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))
        for idx, b in enumerate(blocks):
            if len(b) >= 5 and isinstance(b[4], str) and b[4].strip():
                txt = " ".join(b[4].split())
                paras.append({
                    "id": f"p{pno + 1}_{idx}",
                    "page": pno,
                    "bbox": [float(b[0]), float(b[1]), float(b[2]), float(b[3])],
                    "text": txt,
                })
    return paras


def handle_compare_semantic(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    if len(sources) != 2 or any(s.suffix.lower() != ".pdf" for s in sources):
        raise ProcessingError("Suba exactamente dos archivos PDF (V1 origen y V2 destino).", 400)

    password = str(options.get("password", ""))
    migrate_annotations = bool(options.get("migrate_annotations", True))

    with open_pdf(sources[0], password, config["max_pages"]) as doc1, open_pdf(sources[1], password, config["max_pages"]) as doc2:
        p1 = _doc_paragraphs(doc1)
        p2 = _doc_paragraphs(doc2)

        t1 = [p["text"] for p in p1]
        t2 = [p["text"] for p in p2]
        sm = difflib.SequenceMatcher(a=t1, b=t2, autojunk=False)
        changes: list[dict] = []
        v1_to_v2: dict[int, tuple[int, float]] = {}

        removed_indices: list[int] = []
        added_indices: list[int] = []

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for off in range(i2 - i1):
                    src_i = i1 + off
                    dst_j = j1 + off
                    v1_to_v2[src_i] = (dst_j, 1.0)
                    status = "MOVED" if p1[src_i]["page"] != p2[dst_j]["page"] else "UNCHANGED"
                    if status == "MOVED":
                        changes.append({
                            "status": "MOVED",
                            "v1_page": p1[src_i]["page"] + 1,
                            "v2_page": p2[dst_j]["page"] + 1,
                            "text": p1[src_i]["text"][:200],
                        })
            elif tag == "replace":
                pair_count = min(i2 - i1, j2 - j1)
                for off in range(pair_count):
                    src_i = i1 + off
                    dst_j = j1 + off
                    ratio = difflib.SequenceMatcher(None, p1[src_i]["text"], p2[dst_j]["text"]).ratio()
                    v1_to_v2[src_i] = (dst_j, ratio)
                    changes.append({
                        "status": "MODIFIED",
                        "v1_page": p1[src_i]["page"] + 1,
                        "v2_page": p2[dst_j]["page"] + 1,
                        "similarity": round(ratio, 3),
                        "before": p1[src_i]["text"][:220],
                        "after": p2[dst_j]["text"][:220],
                    })
                for off in range(pair_count, i2 - i1):
                    removed_indices.append(i1 + off)
                for off in range(pair_count, j2 - j1):
                    added_indices.append(j1 + off)
            elif tag == "delete":
                removed_indices.extend(range(i1, i2))
            elif tag == "insert":
                added_indices.extend(range(j1, j2))

        # Emparejar bloques movidos lejanos (ej: reordenamiento completo entre paginas)
        matched_added: set[int] = set()
        for src_i in list(removed_indices):
            best_j = None
            best_ratio = 0.0
            for dst_j in added_indices:
                if dst_j in matched_added:
                    continue
                ratio = difflib.SequenceMatcher(None, p1[src_i]["text"], p2[dst_j]["text"]).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_j = dst_j
            if best_j is not None and best_ratio >= 0.72:
                matched_added.add(best_j)
                removed_indices.remove(src_i)
                v1_to_v2[src_i] = (best_j, best_ratio)
                changes.append({
                    "status": "MOVED",
                    "v1_page": p1[src_i]["page"] + 1,
                    "v2_page": p2[best_j]["page"] + 1,
                    "similarity": round(best_ratio, 3),
                    "text": p2[best_j]["text"][:200],
                })

        for src_i in removed_indices:
            changes.append({"status": "REMOVED", "v1_page": p1[src_i]["page"] + 1, "text": p1[src_i]["text"][:220]})
        for dst_j in added_indices:
            if dst_j not in matched_added:
                changes.append({"status": "ADDED", "v2_page": p2[dst_j]["page"] + 1, "text": p2[dst_j]["text"][:220]})

        migrated_log: list[dict] = []
        if migrate_annotations:
            for pno in range(len(doc1)):
                page1 = doc1[pno]
                page_paras = [idx for idx, p in enumerate(p1) if p["page"] == pno]
                for annot in list(page1.annots() or []):
                    arect = annot.rect
                    center = (arect.tl + arect.br) / 2
                    atype = annot.type[1] if annot.type else "Text"
                    content = (annot.info or {}).get("content", "") or f"Nota migrada ({atype})"
                    # Encontrar parrafo ancla en V1
                    anchor_idx = None
                    best_dist = 1e9
                    for idx in page_paras:
                        pr = pdf.Rect(p1[idx]["bbox"])
                        if pr.contains(center) or pr.intersects(arect):
                            anchor_idx = idx
                            break
                        dist = abs(center.y - (pr.y0 + pr.y1) / 2) + abs(center.x - (pr.x0 + pr.x1) / 2)
                        if dist < best_dist:
                            best_dist = dist
                            anchor_idx = idx
                    target_page_no = min(pno, len(doc2) - 1)
                    target_rect = pdf.Rect(arect)
                    confidence = 0.35
                    if anchor_idx is not None and anchor_idx in v1_to_v2:
                        dst_idx, sim = v1_to_v2[anchor_idx]
                        target_page_no = p2[dst_idx]["page"]
                        src_pr = pdf.Rect(p1[anchor_idx]["bbox"])
                        dst_pr = pdf.Rect(p2[dst_idx]["bbox"])
                        dx = dst_pr.x0 - src_pr.x0
                        dy = dst_pr.y0 - src_pr.y0
                        target_rect = pdf.Rect(arect.x0 + dx, arect.y0 + dy, arect.x1 + dx, arect.y1 + dy) & doc2[target_page_no].rect
                        if target_rect.is_empty:
                            target_rect = dst_pr
                        confidence = round(float(sim), 3)
                    tpage = doc2[target_page_no]
                    if atype == "Highlight":
                        new_annot = tpage.add_highlight_annot(target_rect)
                        new_annot.set_info(content=content)
                        new_annot.update()
                    else:
                        pt = pdf.Point(target_rect.x0, target_rect.y0)
                        note_txt = content if confidence >= 0.75 else f"[Revisar confianza {confidence}] {content}"
                        tpage.add_text_annot(pt, note_txt)
                    migrated_log.append({
                        "v1_page": pno + 1,
                        "v2_page": target_page_no + 1,
                        "type": atype,
                        "confidence": confidence,
                        "needs_review": confidence < 0.75,
                        "content": content[:200],
                    })

        v2_migrated_path = folder / "v2_con_notas_migradas.pdf"
        save(doc2, v2_migrated_path, clean=True)

    summary = {
        "v1_paragraphs": len(p1),
        "v2_paragraphs": len(p2),
        "changes": changes,
        "annotations_migrated": migrated_log,
    }
    report_lines = [
        "INFORME COMPARADOR SEMANTICO V1 vs V2",
        f"Bloques V1={len(p1)}, V2={len(p2)}, Cambios detectados={len(changes)}, Notas migradas={len(migrated_log)}",
        "",
    ]
    for ch in changes[:120]:
        report_lines.append(f"[{ch['status']}] {ch.get('before', ch.get('text', ''))[:100]}")

    rep_pdf = folder / "informe_comparacion.pdf"
    report_pdf(report_lines, rep_pdf, config)

    bundle = folder / "comparacion_semantica.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(v2_migrated_path, "documento_v2_anotaciones_migradas.pdf")
        archive.write(rep_pdf, "informe_comparacion.pdf")
        archive.writestr("diff_semantico.json", json.dumps(summary, ensure_ascii=False, indent=2))

    return {
        "file": bundle.name,
        "notice": f"Comparacion semantica lista: {len(changes)} cambios y {len(migrated_log)} notas migradas.",
    }


def _parse_bib_entries(bib_text: str) -> list[dict]:
    entries = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+)\s*,(.*?)\n\s*\}", bib_text, re.DOTALL):
        etype, key, body = m.group(1).lower(), m.group(2).strip(), m.group(3)
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*[\{\"]([^\}\"]+)[\}\"]", body):
            fields[fm.group(1).lower()] = " ".join(fm.group(2).split())
        entries.append({"type": etype, "key": key, **fields})
    return entries


def handle_research_link(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    password = str(options.get("password", ""))
    pdfs = [s for s in sources if s.suffix.lower() == ".pdf"]
    bibs = [s for s in sources if s.suffix.lower() == ".bib"]
    if not pdfs and not bibs:
        raise ProcessingError("Suba al menos un archivo PDF o BibTeX (.bib).", 400)

    bib_records: list[dict] = []
    for bp in bibs:
        bib_records.extend(_parse_bib_entries(bp.read_text(encoding="utf-8", errors="ignore")))

    nodes: list[dict] = []
    edges: list[dict] = []
    ris_lines: list[str] = []
    bib_lines: list[str] = []
    apa_refs: list[dict] = []
    doc_records: list[dict] = []

    for idx, ppath in enumerate(pdfs, 1):
        with open_pdf(ppath, password, config["max_pages"]) as doc:
            meta = doc.metadata or {}
            first_page_txt = doc[0].get_text(sort=True) if len(doc) else ""
            lines = [ln.strip() for ln in first_page_txt.splitlines() if ln.strip()]
            title = (meta.get("title") or (lines[0] if lines else f"Documento_{idx}")).strip()[:180]
            author = (meta.get("author") or (lines[1] if len(lines) > 1 else "Autor desconocido")).strip()[:120]
            full_text = "\n".join(pg.get_text() for pg in doc)
            dois = sorted(set(re.findall(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", full_text)))
            year_m = re.search(r"\b(19\d{2}|20[0-2]\d)\b", first_page_txt or meta.get("creationDate", ""))
            year = year_m.group(1) if year_m else "2026"
            key = f"eva_doc_{idx:02d}_{year}"
            doc_records.append({
                "index": idx,
                "key": key,
                "pdf_name": f"documento-{idx:02d}.pdf",
                "title": title,
                "author": author,
                "year": year,
                "dois": dois,
                "path": ppath,
            })

    # Segunda pasada: inyectar enlaces internos [N] -> pagina de referencias y LINK_GOTOR cruzados
    bundle = folder / "paquete_academico.zip"
    links_injected = 0

    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for rec in doc_records:
            with open_pdf(rec["path"], password, config["max_pages"]) as doc:
                ref_targets: dict[str, tuple[int, pdf.Point]] = {}
                for pno in range(len(doc)):
                    txt = doc[pno].get_text()
                    for num_m in re.finditer(r"(?m)^\[(\d+)\]\s+(.+)$", txt):
                        cit_num = num_m.group(1)
                        hits = doc[pno].search_for(f"[{cit_num}]")
                        if hits:
                            ref_targets[cit_num] = (pno, pdf.Point(hits[-1].x0, hits[-1].y0))

                # Enlaces internos [1] -> destino en bibliografia
                for pno in range(len(doc)):
                    page = doc[pno]
                    for cit_num, (t_page, t_pt) in ref_targets.items():
                        if pno == t_page:
                            continue
                        for rect in page.search_for(f"[{cit_num}]"):
                            page.insert_link({"kind": pdf.LINK_GOTO, "from": rect, "page": t_page, "to": t_pt})
                            links_injected += 1

                    # Enlaces cruzados LINK_GOTOR hacia otros PDFs cargados si mencionan su DOI o titulo
                    for other in doc_records:
                        if other["index"] == rec["index"]:
                            continue
                        tokens = [d for d in other["dois"]] + ([other["title"][:35]] if len(other["title"]) >= 12 else [])
                        for tok in tokens:
                            for rect in page.search_for(tok):
                                page.insert_link({"kind": pdf.LINK_GOTOR, "from": rect, "file": other["pdf_name"], "page": 0})
                                links_injected += 1
                                edges.append({"source": rec["key"], "target": other["key"], "relation": "cross_citation", "token": tok})

                out_doc = folder / rec["pdf_name"]
                save(doc, out_doc, clean=True)
                archive.write(out_doc, rec["pdf_name"])

            nodes.append({
                "id": rec["key"],
                "kind": "pdf",
                "title": rec["title"],
                "author": rec["author"],
                "year": rec["year"],
                "dois": rec["dois"],
            })
            bib_lines.extend([
                f"@article{{{rec['key']},",
                f"  title = {{{rec['title']}}},",
                f"  author = {{{rec['author']}}},",
                f"  year = {{{rec['year']}}},",
                *( [f"  doi = {{{rec['dois'][0]}}},"] if rec["dois"] else [] ),
                "}",
                "",
            ])
            ris_lines.extend([
                "TY  - JOUR",
                f"ID  - {rec['key']}",
                f"TI  - {rec['title']}",
                f"AU  - {rec['author']}",
                f"PY  - {rec['year']}",
                *( [f"DO  - {d}" for d in rec["dois"]] ),
                "ER  - ",
                "",
            ])
            apa_refs.append({
                "id": rec["key"],
                "type": "article-journal",
                "title": rec["title"],
                "author": [{"literal": rec["author"]}],
                "issued": {"date-parts": [[int(rec["year"])]]},
                **({"DOI": rec["dois"][0]} if rec["dois"] else {}),
            })

        for brec in bib_records:
            nodes.append({"id": brec["key"], "kind": "bibtex", "title": brec.get("title", brec["key"])})
            bib_lines.append(f"@{brec['type']}{{{brec['key']}, title = {{{brec.get('title', brec['key'])}}}, year = {{{brec.get('year', '2026')}}}}}")

        archive.writestr("bibliografia.bib", "\n".join(bib_lines).encode("utf-8"))
        archive.writestr("referencias.ris", "\n".join(ris_lines).encode("utf-8"))
        archive.writestr("csl_apa7.json", json.dumps(apa_refs, ensure_ascii=False, indent=2).encode("utf-8"))
        archive.writestr(
            "grafo-citas.json",
            json.dumps({"nodes": nodes, "edges": edges, "links_injected": links_injected}, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    return {
        "file": bundle.name,
        "notice": f"Paquete academico generado: {len(doc_records)} PDFs, {links_injected} enlaces internos/cruzados y BibTeX/RIS/APA7.",
    }


def handle_canvas_sync(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    password = str(options.get("password", ""))
    extracts = options.get("extracts", [])
    if not isinstance(extracts, list) or len(extracts) > 500:
        raise ProcessingError("Lista de extractos Canvas no valida.", 400)

    docs = []
    try:
        for src in sources:
            docs.append(open_pdf(src, password, config["max_pages"]))

        synced: list[dict] = []
        for idx, ext in enumerate(extracts):
            if not isinstance(ext, dict):
                continue
            d_idx = int(ext.get("doc_index", 0))
            pno = int(ext.get("page", 1)) - 1
            bbox = ext.get("bbox")
            if not (0 <= d_idx < len(docs)) or not (0 <= pno < len(docs[d_idx])):
                synced.append({"id": ext.get("id", f"ext_{idx}"), "status": "missing_page"})
                continue
            page = docs[d_idx][pno]
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                clip = pdf.Rect([float(v) for v in bbox]) & page.rect
                text = " ".join(page.get_text("text", clip=clip).split())
            else:
                text = " ".join(page.get_text("text").split()[:80])
            cur_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            prev_sha = str(ext.get("expected_sha256", ""))
            status = "unchanged" if prev_sha and prev_sha == cur_sha else ("updated" if prev_sha else "synced")
            synced.append({
                "id": ext.get("id", f"ext_{idx}"),
                "doc_index": d_idx,
                "page": pno + 1,
                "text": text,
                "sha256": cur_sha,
                "status": status,
            })

        toc_summaries = [
            {
                "doc_index": d_i,
                "pages": len(d),
                "toc": [[lvl, title, pg] for lvl, title, pg in (d.get_toc() or [])[:50]],
            }
            for d_i, d in enumerate(docs)
        ]
    finally:
        for d in docs:
            d.close()

    out_json = folder / "canvas_sync.json"
    out_json.write_text(
        json.dumps({"extracts": synced, "documents": toc_summaries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "file": out_json.name,
        "notice": f"Canvas sincronizado: {len(synced)} extractos verificados.",
    }
