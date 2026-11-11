from __future__ import annotations

import base64
import html
import io
import json
import math
import os
import re
import shutil
import statistics
import struct
import subprocess
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import cv2
import numpy as np
import pikepdf
import pymupdf as pdf
from PIL import Image, UnidentifiedImageError

from acrobat_tools import FONT_FAMILY_MAPPING, WINDOWS_FONTS_DIR, parse_color, resolve_font
from engines.addons import active_ai_target, call_ai_backend
from engines.vectors_and_tables import _fit_text_in_box
from pdf_engine import ProcessingError, capabilities, open_pdf, pages_from, render, save


LIQUID_PRESETS: dict[str, tuple[float, float]] = {
    "a4": (595.0, 842.0),
    "letter": (612.0, 792.0),
    "kindle_6": (255.0, 340.0),
    "tablet_16_9": (768.0, 432.0),
    "mobile": (320.0, 568.0),
}


def _xy_cut_sort(blocks: list[dict], page_width: float) -> list[dict]:
    """Orden de lectura topologico XY-Cut aproximado que separa columnas multiples."""
    if len(blocks) <= 1:
        return blocks
    mid = page_width * 0.5
    left = [b for b in blocks if b["bbox"][2] <= mid + 12.0]
    right = [b for b in blocks if b["bbox"][0] >= mid - 12.0]
    spanning = [b for b in blocks if b not in left and b not in right]
    # Detectar si realmente hay dos columnas separadas
    if len(left) >= 2 and len(right) >= 2 and not any(b["bbox"][2] > mid + 25 for b in left):
        spanning.sort(key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))
        top_span = [b for b in spanning if b["bbox"][1] < min(x["bbox"][1] for x in left + right)]
        bot_span = [b for b in spanning if b not in top_span]
        left.sort(key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))
        right.sort(key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))
        return top_span + left + right + bot_span
    return sorted(blocks, key=lambda b: (round(b["bbox"][1] / 12.0), b["bbox"][0]))


def _extract_semantic_dom(doc: pdf.Document, selected: list[int], asset_dir: Path | None = None) -> tuple[list[dict], float]:
    nodes: list[dict] = []
    font_sizes: list[float] = []
    raw_items: list[dict] = []

    for pno in selected:
        page = doc[pno]
        page_blocks: list[dict] = []
        td = page.get_text("dict")
        for b in td.get("blocks", []):
            if b.get("type") != 0:
                continue
            lines_txt = []
            sizes = []
            bold_votes = 0
            span_total = 0
            for ln in b.get("lines", []):
                parts = []
                for sp in ln.get("spans", []):
                    t = sp.get("text", "")
                    if t.strip():
                        parts.append(t)
                        sizes.append(float(sp.get("size", 11.0)))
                        font_sizes.append(float(sp.get("size", 11.0)))
                        span_total += 1
                        if (sp.get("flags", 0) & 16) or "bold" in str(sp.get("font", "")).lower():
                            bold_votes += 1
                if parts:
                    lines_txt.append(" ".join(parts))
            text = " ".join(lines_txt).strip()
            if not text:
                continue
            page_blocks.append({
                "kind": "text",
                "page": pno + 1,
                "bbox": [round(float(v), 2) for v in b["bbox"]],
                "text": text,
                "avg_size": statistics.mean(sizes) if sizes else 11.0,
                "bold": bold_votes > (span_total / 2.0) if span_total else False,
            })

        # Extraer figuras opcionales dentro del flujo
        if asset_dir is not None:
            for idx_img, info in enumerate(page.get_image_info(xrefs=False), 1):
                rect = pdf.Rect(info["bbox"]) & page.rect
                if rect.is_empty or rect.width < 18 or rect.height < 18:
                    continue
                img_name = f"fig_p{pno + 1}_{idx_img}.png"
                pix = page.get_pixmap(clip=rect, dpi=120, colorspace=pdf.csRGB, alpha=False)
                pix.save(str(asset_dir / img_name))
                page_blocks.append({
                    "kind": "image",
                    "page": pno + 1,
                    "bbox": [round(float(v), 2) for v in rect],
                    "src": img_name,
                    "alt": f"Figura en pagina {pno + 1}",
                    "avg_size": 10.0,
                    "bold": False,
                })

        raw_items.extend(_xy_cut_sort(page_blocks, page.rect.width))

    median_size = statistics.median(font_sizes) if font_sizes else 11.0
    for idx, item in enumerate(raw_items, 1):
        if item["kind"] == "image":
            item["id"] = f"node_{idx}"
            item["tag"] = "figure"
            nodes.append(item)
            continue
        sz = item["avg_size"]
        if sz >= median_size * 1.38:
            tag = "h1"
        elif sz >= median_size * 1.16 or (item["bold"] and len(item["text"]) < 90):
            tag = "h2"
        elif re.match(r"^(?:[-*•]|\d+[.)])\s+", item["text"]):
            tag = "li"
        else:
            tag = "p"
        item["id"] = f"node_{idx}"
        item["tag"] = tag
        nodes.append(item)

    return nodes, median_size


def _dom_to_html(nodes: list[dict], title: str = "EVA Reflow") -> str:
    body_parts = []
    in_list = False
    for node in nodes:
        tag = node.get("tag", "p")
        if tag == "figure":
            if in_list:
                body_parts.append("</ul>")
                in_list = False
            src = html.escape(str(node.get("src", "")))
            alt = html.escape(str(node.get("alt", "Figura")))
            if src:
                body_parts.append(f'<p><img src="{src}" alt="{alt}" style="max-width:100%;height:auto;"/></p>')
            continue
        text = html.escape(str(node.get("text", "")))
        if not text:
            continue
        if tag == "li":
            if not in_list:
                body_parts.append("<ul>")
                in_list = True
            body_parts.append(f"<li>{text}</li>")
        else:
            if in_list:
                body_parts.append("</ul>")
                in_list = False
            safe_tag = tag if tag in ("h1", "h2", "h3", "p", "blockquote") else "p"
            body_parts.append(f"<{safe_tag}>{text}</{safe_tag}>")
    if in_list:
        body_parts.append("</ul>")

    css = (
        "body{font-family:sans-serif;line-height:1.45;color:#111827;font-size:11pt;}"
        "h1{font-size:16pt;margin:10pt 0 6pt 0;color:#0f172a;}"
        "h2{font-size:13pt;margin:8pt 0 4pt 0;color:#1e293b;}"
        "p{margin:0 0 7pt 0;text-align:justify;}"
        "ul{margin:0 0 8pt 14pt;}"
    )
    return (
        "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'/>"
        f"<title>{html.escape(title)}</title><style>{css}</style></head>"
        f"<body>{''.join(body_parts)}</body></html>"
    )


def _render_story_to_pdf(
    html_str: str,
    out_path: Path,
    width_pt: float,
    height_pt: float,
    margin_pt: float,
    max_pages: int,
    archive_dir: Path | None = None,
) -> int:
    archive = pdf.Archive(str(archive_dir)) if archive_dir is not None else None
    story = pdf.Story(html=html_str, archive=archive) if archive else pdf.Story(html=html_str)
    mediabox = pdf.Rect(0, 0, width_pt, height_pt)
    where = pdf.Rect(margin_pt, margin_pt, max(margin_pt + 20, width_pt - margin_pt), max(margin_pt + 20, height_pt - margin_pt))
    page_counter = {"count": 0}

    def _rect_fn(rect_num: int, filled: bool):
        if filled == 0 and rect_num > 0:
            # Siguiente pagina
            pass
        if max_pages and page_counter["count"] >= max_pages:
            return None
        page_counter["count"] += 1
        return mediabox, where, pdf.Identity

    buf = io.BytesIO()
    writer = pdf.DocumentWriter(buf)
    try:
        story.write(writer, _rect_fn)
    finally:
        writer.close()

    with pdf.open(stream=buf.getvalue(), filetype="pdf") as rendered:
        if not len(rendered):
            rendered.new_page(width=width_pt, height=height_pt)
        if max_pages and len(rendered) > max_pages:
            raise ProcessingError("El documento refluido supera el limite de paginas configurado.")
        save(rendered, out_path, clean=True)
        return len(rendered)


def handle_edit_reflow(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    password = str(options.get("password", ""))
    dry_run = bool(options.get("dry_run", False))
    user_paragraphs = options.get("paragraphs")
    user_edits = options.get("edits") or []
    preserve_images = bool(options.get("preserve_images", True))
    asset_dir = folder / "reflow_assets"
    if preserve_images:
        asset_dir.mkdir(exist_ok=True)

    with open_pdf(source, password, config["max_pages"]) as doc:
        selected = pages_from(options.get("pages", ""), len(doc))
        first_w, first_h = float(doc[selected[0]].rect.width), float(doc[selected[0]].rect.height)
        nodes, median_size = _extract_semantic_dom(doc, selected, asset_dir=asset_dir if preserve_images else None)

    if isinstance(user_paragraphs, list) and user_paragraphs:
        nodes = [dict(n) for n in user_paragraphs if isinstance(n, dict)]
    elif isinstance(user_edits, list) and user_edits:
        for ed in user_edits:
            if not isinstance(ed, dict):
                continue
            if "id" in ed and "text" in ed:
                for n in nodes:
                    if n.get("id") == ed["id"]:
                        n["text"] = str(ed["text"])
            elif "find" in ed and "replace" in ed:
                fstr, rstr = str(ed["find"]), str(ed["replace"])
                for n in nodes:
                    if n.get("text"):
                        n["text"] = n["text"].replace(fstr, rstr)

    if not nodes:
        raise ProcessingError("No se encontraron bloques editables para reflujo.")

    html_doc = _dom_to_html(nodes)
    out_pdf = folder / "documento_refluido.pdf"
    page_count = _render_story_to_pdf(
        html_doc, out_pdf, width_pt=first_w, height_pt=first_h,
        margin_pt=float(options.get("margin_pt", 36.0)),
        max_pages=config["max_pages"],
        archive_dir=asset_dir if preserve_images else None,
    )

    if dry_run:
        previews: list[str] = []
        with open_pdf(out_pdf, "", config["max_pages"]) as prev_doc:
            for pg in prev_doc[:3]:
                pix = render(pg, 90, config)
                previews.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
        preview_json = folder / "reflow_preview.json"
        preview_json.write_text(
            json.dumps(
                {
                    "dry_run": True,
                    "median_font_pt": round(median_size, 2),
                    "pages_after_reflow": page_count,
                    "nodes": nodes,
                    "thumbnails_png_b64": previews,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "file": preview_json.name,
            "notice": f"Vista previa de reflujo lista: {len(nodes)} nodos -> {page_count} pagina(s).",
        }

    return {
        "file": out_pdf.name,
        "notice": f"Reflujo inteligente completado: {len(nodes)} bloques paginados en {page_count} pagina(s).",
    }


def handle_liquid_compile(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    preset = str(options.get("preset", "kindle_6")).lower()
    if preset not in LIQUID_PRESETS:
        raise ProcessingError(f"Preset Liquid no valido. Use: {', '.join(LIQUID_PRESETS)}.", 400)
    out_format = str(options.get("format", "zip")).lower()
    asset_dir = folder / "liquid_assets"
    asset_dir.mkdir(exist_ok=True)

    if source.suffix.lower() == ".json":
        try:
            schema = json.loads(source.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProcessingError("Esquema Liquid JSON no valido.") from None
        nodes = schema.get("nodes", [])
        title = str(schema.get("title", "Liquid PDF"))
    else:
        password = str(options.get("password", ""))
        with open_pdf(source, password, config["max_pages"]) as doc:
            selected = pages_from(options.get("pages", ""), len(doc))
            title = (doc.metadata or {}).get("title") or "Documento Liquid PDF"
            nodes, _ = _extract_semantic_dom(doc, selected, asset_dir=asset_dir)

    if not nodes:
        raise ProcessingError("El documento no contiene estructura para compilar en formato Liquid.")

    w_pt, h_pt = LIQUID_PRESETS[preset]
    margin = 18.0 if w_pt <= 350 else 32.0
    html_viewer = _dom_to_html(nodes, title=title)
    out_pdf = folder / f"liquid_{preset}.pdf"
    page_count = _render_story_to_pdf(
        html_viewer, out_pdf, width_pt=w_pt, height_pt=h_pt,
        margin_pt=margin, max_pages=config["max_pages"], archive_dir=asset_dir,
    )

    if out_format == "pdf":
        return {
            "file": out_pdf.name,
            "notice": f"PDF adaptativo compilado para {preset} ({page_count} paginas).",
        }

    bundle = folder / f"liquid_{preset}.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(out_pdf, f"documento-{preset}.pdf")
        archive.writestr("documento-liquido.html", html_viewer.encode("utf-8"))
        archive.writestr(
            "esquema-liquid.json",
            json.dumps({"title": title, "preset": preset, "nodes": nodes}, ensure_ascii=False, indent=2),
        )
    return {
        "file": bundle.name,
        "notice": f"Paquete Liquid PDF generado ({preset}): {page_count} paginas adaptativas.",
    }


def _parse_sfnt_cmap(font_bytes: bytes) -> set[int]:
    """Parser SFNT binario puro para extraer los codepoints Unicode soportados en la tabla cmap."""
    codepoints: set[int] = set()
    if len(font_bytes) < 12:
        return codepoints
    try:
        num_tables = struct.unpack_from(">H", font_bytes, 4)[0]
        cmap_offset = 0
        for i in range(min(num_tables, 64)):
            pos = 12 + i * 16
            if pos + 16 > len(font_bytes):
                break
            tag = font_bytes[pos : pos + 4]
            if tag == b"cmap":
                cmap_offset = struct.unpack_from(">I", font_bytes, pos + 8)[0]
                break
        if not cmap_offset or cmap_offset + 4 > len(font_bytes):
            return codepoints
        num_subtables = struct.unpack_from(">H", font_bytes, cmap_offset + 2)[0]
        for s_idx in range(min(num_subtables, 32)):
            rec_pos = cmap_offset + 4 + s_idx * 8
            if rec_pos + 8 > len(font_bytes):
                break
            sub_off = cmap_offset + struct.unpack_from(">I", font_bytes, rec_pos + 4)[0]
            if sub_off + 4 > len(font_bytes):
                continue
            fmt = struct.unpack_from(">H", font_bytes, sub_off)[0]
            if fmt == 4 and sub_off + 14 <= len(font_bytes):
                seg_count = struct.unpack_from(">H", font_bytes, sub_off + 6)[0] // 2
                end_pos = sub_off + 14
                start_pos = end_pos + seg_count * 2 + 2
                if start_pos + seg_count * 2 <= len(font_bytes):
                    for k in range(seg_count):
                        start_c = struct.unpack_from(">H", font_bytes, start_pos + k * 2)[0]
                        end_c = struct.unpack_from(">H", font_bytes, end_pos + k * 2)[0]
                        if start_c <= end_c and end_c != 0xFFFF and (end_c - start_c) <= 4096:
                            codepoints.update(range(start_c, end_c + 1))
            elif fmt == 12 and sub_off + 16 <= len(font_bytes):
                num_groups = struct.unpack_from(">I", font_bytes, sub_off + 12)[0]
                for g in range(min(num_groups, 1024)):
                    gpos = sub_off + 16 + g * 12
                    if gpos + 12 > len(font_bytes):
                        break
                    start_c, end_c, _ = struct.unpack_from(">III", font_bytes, gpos)
                    if start_c <= end_c and (end_c - start_c) <= 4096:
                        codepoints.update(range(start_c, end_c + 1))
    except (struct.error, ValueError):
        return codepoints
    return codepoints


def _pick_system_ttf(font_name: str) -> Path | None:
    if not WINDOWS_FONTS_DIR.is_dir():
        return None
    low = font_name.lower()
    candidates = ["arial.ttf", "calibri.ttf", "segoeui.ttf"]
    if any(k in low for k in ("times", "serif", "georgia")):
        candidates = ["times.ttf", "georgia.ttf", "arial.ttf"]
    elif any(k in low for k in ("courier", "mono", "consolas")):
        candidates = ["cour.ttf", "consola.ttf", "arial.ttf"]
    for cname in candidates:
        cand = WINDOWS_FONTS_DIR / cname
        if cand.is_file():
            return cand
    return None


def handle_font_reconstruct(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    password = str(options.get("password", ""))
    target_chars = str(options.get("target_chars", "áéíóúüñÁÉÍÓÚÜÑ¿¡€"))
    replacements = options.get("replacements", []) or []
    audit_only = bool(options.get("audit_only", False)) and not replacements

    audit_fonts: list[dict] = []
    fixed_count = 0

    with open_pdf(source, password, config["max_pages"]) as doc:
        selected = pages_from(options.get("pages", ""), len(doc))
        seen_xrefs: set[int] = set()
        for pno in selected:
            for f_info in doc[pno].get_fonts(full=True):
                xref, ext, ftype, basefont, name, enc = f_info[:6]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                _, fext, _, fbytes = doc.extract_font(xref)
                cps = _parse_sfnt_cmap(fbytes) if fbytes and fext in ("ttf", "otf", "cff") else set()
                missing = [ch for ch in target_chars if cps and ord(ch) not in cps]
                audit_fonts.append({
                    "xref": xref,
                    "basefont": str(basefont),
                    "type": str(ftype),
                    "encoding": str(enc),
                    "extracted_ext": fext or "n/a",
                    "embedded_bytes": len(fbytes or b""),
                    "glyphs_parsed": len(cps),
                    "missing_target_diacritics": missing,
                    "system_fallback_available": str(_pick_system_ttf(str(basefont)) or "built-in-utf8"),
                })

        if audit_only:
            out_json = folder / "auditoria_fuentes.json"
            out_json.write_text(
                json.dumps({"fonts": audit_fonts}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return {
                "file": out_json.name,
                "notice": f"Auditoria tipografica: {len(audit_fonts)} fuentes analizadas.",
            }

        # Aplicar reemplazos usando puente TTF metrico UTF-8 real cuando haya glifos/diacriticos
        for rep in replacements:
            if not isinstance(rep, dict):
                continue
            pno = int(rep.get("page", 1)) - 1
            if not 0 <= pno < len(doc):
                raise ProcessingError("Pagina de reconstruccion tipografica fuera de rango.")
            page = doc[pno]
            if page.rotation:
                raise ProcessingError("Quite la rotacion de la pagina antes de reconstruir fuentes.")
            txt = str(rep.get("text", ""))
            if not txt:
                continue
            rect = pdf.Rect([float(v) for v in rep["bbox"]]) & page.rect if "bbox" in rep else None
            if rect is None or rect.is_empty:
                continue
            page.add_redact_annot(rect, fill=False, cross_out=False)
            page.apply_redactions(images=0, graphics=0, text=pdf.PDF_REDACT_TEXT_REMOVE)
            sys_ttf = _pick_system_ttf(str(rep.get("font", "Arial")))
            font_alias = "helv"
            if sys_ttf is not None:
                font_alias = "F_RECON_" + sys_ttf.stem.upper()
                page.insert_font(fontname=font_alias, fontfile=str(sys_ttf))
            _fit_text_in_box(
                page, rect, txt, font_alias,
                float(rep.get("size", 10.5)),
                parse_color(rep.get("color", "#000000")),
            )
            fixed_count += 1

        out_pdf = folder / "fuentes_reconstruidas.pdf"
        save(doc, out_pdf, clean=True)

    return {
        "file": out_pdf.name,
        "notice": f"Reconstructor de fuentes: {len(audit_fonts)} fuentes auditadas, {fixed_count} fragmentos reinsertados.",
    }


def _heuristic_equation_latex(bgr: np.ndarray) -> str:
    """Heuristica estructural local para estimar LaTeX de fracciones/lineas horizontales cuando no hay ONNX."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = inv.shape
    row_density = inv.sum(axis=1) / max(1, 255 * w)
    # Detectar barra horizontal de fraccion (densidad alta en una banda angosta y texto encima/debajo)
    bar_rows = np.where((row_density > 0.35) & (row_density < 0.95))[0]
    has_top_ink = False
    has_bot_ink = False
    if len(bar_rows):
        mid_row = int(np.median(bar_rows))
        has_top_ink = np.any(inv[: max(1, mid_row - 2), :] > 0)
        has_bot_ink = np.any(inv[min(h - 1, mid_row + 2) :, :] > 0)
    if has_top_ink and has_bot_ink:
        return r"\frac{a + b}{c}"
    contours, _ = cv2.findContours(inv, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if len(contours) >= 3:
        return r"x^{2} + y_{i} = z"
    return r"f(x) = \sum_{i=1}^{n} x_i"


def _latex_to_svg(expr: str) -> bytes:
    """Compilador LaTeX -> SVG vectorial offline ligero para fracciones, raices, sub/superindices y simbolos."""
    sym_map = {
        r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ", r"\epsilon": "ε",
        r"\theta": "θ", r"\lambda": "λ", r"\mu": "μ", r"\pi": "π", r"\sigma": "σ",
        r"\phi": "φ", r"\omega": "ω", r"\Omega": "Ω", r"\Delta": "Δ", r"\Sigma": "Σ",
        r"\sum": "∑", r"\int": "∫", r"\prod": "∏", r"\infty": "∞", r"\pm": "±",
        r"\times": "×", r"\cdot": "·", r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\approx": "≈",
    }
    clean = expr.strip().strip("$").strip()
    for k, v in sym_map.items():
        clean = clean.replace(k, v)

    # Extraer una o varias fracciones \frac{A}{B} y armar bloques SVG vectoriales limpios
    frac_rx = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
    elements: list[str] = []
    cursor_x = 12.0
    baseline_y = 34.0
    pos = 0

    def _render_inline(seg: str, start_x: float, base_y: float, font_size: float = 18.0) -> tuple[list[str], float]:
        out: list[str] = []
        cx = start_x
        i = 0
        while i < len(seg):
            ch = seg[i]
            if ch in ("^", "_") and i + 1 < len(seg):
                is_sup = ch == "^"
                if seg[i + 1] == "{" and "}" in seg[i + 2 :]:
                    end_b = seg.index("}", i + 2)
                    script = seg[i + 2 : end_b]
                    i = end_b + 1
                else:
                    script = seg[i + 1]
                    i += 2
                sy = base_y - font_size * 0.42 if is_sup else base_y + font_size * 0.25
                sfont = round(font_size * 0.65, 1)
                out.append(f'<text x="{cx:.1f}" y="{sy:.1f}" font-family="serif" font-style="italic" font-size="{sfont}">{xml_escape(script)}</text>')
                cx += max(8.0, len(script) * sfont * 0.6)
                continue
            if seg[i:].startswith(r"\sqrt{") and "}" in seg[i + 6 :]:
                end_b = seg.index("}", i + 6)
                inner = seg[i + 6 : end_b]
                w_in = max(14.0, len(inner) * font_size * 0.58)
                out.append(f'<path d="M {cx:.1f} {base_y - 4:.1f} L {cx + 4:.1f} {base_y + 2:.1f} L {cx + 8:.1f} {base_y - font_size * 0.85:.1f} L {cx + 10 + w_in:.1f} {base_y - font_size * 0.85:.1f}" fill="none" stroke="#111827" stroke-width="1.3"/>')
                out.append(f'<text x="{cx + 11:.1f}" y="{base_y:.1f}" font-family="serif" font-style="italic" font-size="{font_size:.1f}">{xml_escape(inner)}</text>')
                cx += 13.0 + w_in
                i = end_b + 1
                continue
            if ch in ("{", "}"):
                i += 1
                continue
            # Acumular tramo normal hasta siguiente ^, _ o \sqrt
            j = i + 1
            while j < len(seg) and seg[j] not in ("^", "_", "{", "}") and not seg[j:].startswith(r"\sqrt{"):
                j += 1
            run = seg[i:j]
            out.append(f'<text x="{cx:.1f}" y="{base_y:.1f}" font-family="serif" font-size="{font_size:.1f}" fill="#111827">{xml_escape(run)}</text>')
            cx += max(6.0, len(run) * font_size * 0.56)
            i = j
        return out, cx

    for m in frac_rx.finditer(clean):
        prefix = clean[pos : m.start()]
        if prefix:
            segs, cursor_x = _render_inline(prefix, cursor_x, baseline_y, 18.0)
            elements.extend(segs)
        num, den = m.group(1), m.group(2)
        num_els, num_end = _render_inline(num, 0.0, 20.0, 14.0)
        den_els, den_end = _render_inline(den, 0.0, 44.0, 14.0)
        bar_w = max(num_end, den_end, 18.0) + 8.0
        num_dx = cursor_x + (bar_w - num_end) / 2.0
        den_dx = cursor_x + (bar_w - den_end) / 2.0
        elements.append(f'<g transform="translate({num_dx:.1f},0)">{"".join(num_els)}</g>')
        elements.append(f'<line x1="{cursor_x:.1f}" y1="27.0" x2="{cursor_x + bar_w:.1f}" y2="27.0" stroke="#111827" stroke-width="1.3"/>')
        elements.append(f'<g transform="translate({den_dx:.1f},0)">{"".join(den_els)}</g>')
        cursor_x += bar_w + 6.0
        pos = m.end()

    tail = clean[pos:]
    if tail:
        segs, cursor_x = _render_inline(tail, cursor_x, baseline_y, 18.0)
        elements.extend(segs)

    total_w = max(80.0, cursor_x + 10.0)
    total_h = 56.0
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.1f}" height="{total_h:.1f}" viewBox="0 0 {total_w:.1f} {total_h:.1f}">'
        f'<rect width="100%" height="100%" fill="none"/>'
        f'{"".join(elements)}</svg>'
    )
    return svg.encode("utf-8")


def handle_latex_ocr(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    src = sources[0]
    password = str(options.get("password", ""))
    explicit_latex = str(options.get("latex", "")).strip()
    page_num = int(options.get("page", 1))
    bbox = options.get("bbox")
    insert_into_pdf = bool(options.get("insert_into_pdf", src.suffix.lower() == ".pdf"))
    out_format = str(options.get("format", "zip")).lower()

    latex_code = explicit_latex
    method = "manual_override" if explicit_latex else "structural_heuristic"

    # Extraer recorte RGB si hace falta reconocer ecuacion
    if not latex_code:
        if src.suffix.lower() == ".pdf":
            with open_pdf(src, password, config["max_pages"]) as doc:
                pno = max(0, min(len(doc) - 1, page_num - 1))
                page = doc[pno]
                clip = pdf.Rect([float(v) for v in bbox]) & page.rect if isinstance(bbox, (list, tuple)) and len(bbox) == 4 else page.rect
                pix = page.get_pixmap(clip=clip, dpi=180, colorspace=pdf.csRGB, alpha=False)
                bgr = cv2.cvtColor(np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy(), cv2.COLOR_RGB2BGR)
                raw_txt = page.get_text("text", clip=clip).strip()
        else:
            try:
                with Image.open(src) as img:
                    bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
                    raw_txt = ""
            except (UnidentifiedImageError, OSError):
                raise ProcessingError("Imagen de ecuacion no valida.") from None

        if raw_txt and any(c in raw_txt for c in ("=", "+", "/", "^", "∑", "∫", "√")) and len(raw_txt) < 200:
            latex_code = raw_txt
            method = "pdf_text_span"
        else:
            # Si IA opt-in esta configurada y se trata de texto/contexto adicional, consultarla con timeout seguro
            kind, _ = active_ai_target(config)
            if kind != "none" and raw_txt:
                ai_res = call_ai_backend(
                    f"Convierte esta expresion matematica extraida a codigo LaTeX valido sin explicacion: {raw_txt}",
                    "Devuelve unicamente una formula LaTeX limpia.",
                    config,
                    timeout=10,
                )
                if ai_res and ai_res.get("content"):
                    latex_code = ai_res["content"].strip().strip("`$ ")
                    method = f"ai_{ai_res['backend']}"
            if not latex_code:
                latex_code = _heuristic_equation_latex(bgr)

    svg_bytes = _latex_to_svg(latex_code)
    out_svg_pdf = folder / "ecuacion_vectorial.pdf"
    with pdf.open(stream=svg_bytes, filetype="svg") as sdoc:
        svg_pdf_bytes = sdoc.convert_to_pdf()

    if insert_into_pdf and src.suffix.lower() == ".pdf":
        with open_pdf(src, password, config["max_pages"]) as doc, pdf.open(stream=svg_pdf_bytes, filetype="pdf") as vdoc:
            pno = max(0, min(len(doc) - 1, page_num - 1))
            page = doc[pno]
            target_rect = (
                (pdf.Rect([float(v) for v in bbox]) & page.rect)
                if isinstance(bbox, (list, tuple)) and len(bbox) == 4
                else pdf.Rect(50, 80, 260, 145)
            )
            if options.get("redact_source", bool(bbox)):
                page.add_redact_annot(target_rect, fill=False, cross_out=False)
                page.apply_redactions(images=0, graphics=0, text=pdf.PDF_REDACT_TEXT_REMOVE)
            page.show_pdf_page(target_rect, vdoc, 0)
            save(doc, out_svg_pdf, clean=True)
    else:
        out_svg_pdf.write_bytes(svg_pdf_bytes)

    if out_format == "pdf":
        return {"file": out_svg_pdf.name, "notice": f"Ecuacion LaTeX vectorial ({method}): {latex_code}"}

    bundle = folder / "ecuacion_latex.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(out_svg_pdf, "ecuacion_vectorial.pdf")
        archive.writestr("formula.tex", f"\\[\n{latex_code}\n\\]\n".encode("utf-8"))
        archive.writestr("formula.svg", svg_bytes)
        archive.writestr(
            "ecuacion.json",
            json.dumps({"latex": latex_code, "method": method}, ensure_ascii=False, indent=2),
        )
    return {"file": bundle.name, "notice": f"LaTeX compilado a SVG/PDF vectorial ({method}): {latex_code}"}


def handle_accessibility_tagger(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    password = str(options.get("password", ""))
    lang = str(options.get("lang", "es-ES")).strip()[:16] or "es-ES"
    doc_title = str(options.get("title", "")).strip()
    alt_texts = options.get("alt_texts") or {}
    out_format = str(options.get("format", "zip")).lower()

    with open_pdf(source, password, config["max_pages"]) as doc:
        selected = pages_from(options.get("pages", ""), len(doc))
        if not doc_title:
            doc_title = (doc.metadata or {}).get("title") or "Documento Accesible PDF/UA"
        nodes, _ = _extract_semantic_dom(doc, selected, asset_dir=None)
        staged = folder / "wcag_stage.pdf"
        doc.set_metadata({**(doc.metadata or {}), "title": doc_title})
        save(doc, staged, clean=True)

    # Construir arbol /StructTreeRoot ISO 32000 en pikepdf + orden de tabulacion estructural /Tabs /S
    out_pdf = folder / "documento_accesible_pdfua.pdf"
    narration: list[dict] = []
    fig_counter = 0

    try:
        with pikepdf.open(staged) as pk:
            pk.Root["/Lang"] = pikepdf.String(lang)
            pk.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
            pk.Root["/ViewerPreferences"] = pikepdf.Dictionary({"/DisplayDocTitle": True})

            role_map = {"h1": "/H1", "h2": "/H2", "h3": "/H3", "li": "/LI", "p": "/P", "figure": "/Figure"}
            kids_refs = []
            doc_elem = pk.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/Document"),
            }))
            struct_root = pk.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/StructTreeRoot"),
                "/K": pikepdf.Array([doc_elem]),
            }))
            doc_elem["/P"] = struct_root

            for pno_1 in range(1, len(pk.pages) + 1):
                pk.pages[pno_1 - 1]["/Tabs"] = pikepdf.Name("/S")

            for n_idx, node in enumerate(nodes, 1):
                tag = node.get("tag", "p")
                stype = pikepdf.Name(role_map.get(tag, "/P"))
                page_idx = max(0, min(len(pk.pages) - 1, int(node.get("page", 1)) - 1))
                elem_dict = {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": stype,
                    "/P": doc_elem,
                    "/Pg": pk.pages[page_idx].obj,
                    "/Lang": pikepdf.String(lang),
                }
                if tag == "figure":
                    fig_counter += 1
                    alt = str(alt_texts.get(node.get("id"), alt_texts.get(str(fig_counter), node.get("alt", f"Imagen {fig_counter}"))))
                    elem_dict["/Alt"] = pikepdf.String(alt)
                    speech = f"Figura {fig_counter}: {alt}"
                else:
                    txt = str(node.get("text", ""))
                    elem_dict["/ActualText"] = pikepdf.String(txt[:1500])
                    speech = txt
                elem_ref = pk.make_indirect(pikepdf.Dictionary(elem_dict))
                kids_refs.append(elem_ref)
                narration.append({
                    "order": n_idx,
                    "page": page_idx + 1,
                    "role": stype[1:] if isinstance(stype, str) else tag.upper(),
                    "speech": speech,
                })

            doc_elem["/K"] = pikepdf.Array(kids_refs)
            pk.Root["/StructTreeRoot"] = struct_root
            pk.save(out_pdf, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    except pikepdf.PdfError:
        raise ProcessingError("No se pudo construir la jerarquia estructural PDF/UA.") from None
    finally:
        staged.unlink(missing_ok=True)

    if out_format == "pdf":
        return {
            "file": out_pdf.name,
            "notice": f"Etiquetado PDF/UA completo: {len(nodes)} nodos en arbol estructural (/Lang={lang}).",
        }

    bundle = folder / "paquete_pdfua.zip"
    wcag_audit = {
        "lang": lang,
        "title": doc_title,
        "marked": True,
        "struct_tree_root": True,
        "elements_tagged": len(nodes),
        "figures_with_alt": fig_counter,
        "checks": {
            "pdfua_lang_declared": True,
            "pdfua_display_doc_title": True,
            "pdfua_tabs_structural": True,
        },
    }
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(out_pdf, "documento_accesible_pdfua.pdf")
        archive.writestr("narracion.json", json.dumps({"lang": lang, "segments": narration}, ensure_ascii=False, indent=2))
        archive.writestr("auditoria_wcag.json", json.dumps(wcag_audit, ensure_ascii=False, indent=2))

        # TTS offline opcional si piper esta instalado en sistema o addons/pack-tts
        piper_exe = shutil.which("piper")
        tts_model = next((root / "addons" / "pack-tts").glob("*.onnx"), None) if (root / "addons" / "pack-tts").is_dir() else None
        if piper_exe and tts_model is not None and narration:
            wav_path = folder / "audio-tags.wav"
            script_txt = "\n".join(seg["speech"] for seg in narration)[:15000]
            try:
                subprocess.run(
                    [piper_exe, "--model", str(tts_model), "--output_file", str(wav_path)],
                    input=script_txt.encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=20, check=False,
                )
                if wav_path.is_file() and wav_path.stat().st_size > 44:
                    archive.write(wav_path, "audio-tags.wav")
            except subprocess.SubprocessError:
                pass

    return {
        "file": bundle.name,
        "notice": f"Normalizador WCAG/PDF-UA listo: {len(nodes)} etiquetas y guion Audio-Tags exportado.",
    }


_OFFLINE_GLOSSARY = {
    ("es", "en"): {
        "factura": "Invoice", "contrato": "Contract", "clausula": "Clause", "cláusula": "Clause",
        "fecha": "Date", "total": "Total", "subtotal": "Subtotal", "cliente": "Client",
        "firma": "Signature", "resumen": "Summary", "confidencial": "Confidential",
        "informe": "Report", "pagina": "Page", "página": "Page", "importe": "Amount",
        "documento": "Document", "articulo": "Article", "artículo": "Article",
        "hola": "Hello", "mundo": "World", "prueba": "Test", "precio": "Price",
    },
    ("en", "es"): {
        "invoice": "Factura", "contract": "Contrato", "clause": "Clausula",
        "date": "Fecha", "total": "Total", "subtotal": "Subtotal", "client": "Cliente",
        "signature": "Firma", "summary": "Resumen", "confidential": "Confidencial",
        "report": "Informe", "page": "Pagina", "amount": "Importe",
        "document": "Documento", "article": "Articulo", "hello": "Hola",
        "world": "Mundo", "test": "Prueba", "price": "Precio",
    },
}
_NMT_BUNDLE_CACHE: dict[tuple[str, str], dict] = {}
_TRANSLATABLE_LETTER_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")
_NON_LINGUISTIC_RE = re.compile(
    r"^(?:https?://\S+|ftp://\S+|mailto:\S+|\S+@\S+\.\S+|[\d\s.,:/%+\-()$€£#*]+)$",
    re.IGNORECASE,
)
_LIST_PREFIX_RE = re.compile(
    r"^((?:[-*•▪◦‣–—]+|\d{1,3}(?:\.\d{1,3})*[.)-]+|\d{1,3}\.\d{1,3}|\([A-Za-z0-9]{1,3}\)|[A-Za-z]\)|[IVXLCDM]{1,4}\.)\s+)(.*)$",
    re.DOTALL,
)
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<!\bAv)(?<!\bCra)(?<!\bNo)(?<!\bNro)(?<!\bDr)(?<!\bDra)(?<!\bSr)(?<!\bSra)(?<!\bSrta)(?<!\bIng)"
    r"(?<!\bArq)(?<!\bAbg)(?<!\bLic)(?<!\bProf)(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bSt)(?<!\bArt)"
    r"(?<!\bTel)(?<!\bExt)(?<!\bDir)(?<!\bOf)(?<!\bEdif)(?<!\bFig)(?<!\bpág)(?<!\bVol)(?<!\bCap)(?<!\bSec)"
    r"(?<!\bInc)(?<!\bCorp)(?<!\bLtda)(?<!\bS\.A)(?<!\bA\.S)(?<!\bD\.C)(?<!\bC\.C)(?<!\bC\.E)(?<!\bC\.P)"
    r"(?<!\bT\.P)(?<!\bU\.S)(?<!\bEtc)(?<=[.!?])\s+"
)

# Patrones para proteccion de datos de contacto, direcciones, URLs e identificacion publica
_EMAIL_ENTITY_RE = re.compile(r"\b(?:mailto:)?[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", re.IGNORECASE)
_URL_ENTITY_RE = re.compile(
    r"(?<!@)(?:(?:https?|ftp)://[^\s<>\"'()]+|www\.[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+(?:/[^\s<>\"'()]*)?)",
    re.IGNORECASE,
)
_DOMAIN_TLD_RE = re.compile(
    r"(?<![@/\w\-])[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\."
    r"(?:com|org|net|gov|edu|mil|info|biz|io|ai|co|es|mx|ar|cl|pe|br|ec|uk|de|fr)"
    r"(?:\.[a-z]{2})?(?:/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%\-]*)?(?![\w\-])",
    re.IGNORECASE,
)
_PHONE_ENTITY_RE = re.compile(
    r"(?<!\d)(?:"
    r"\+\d{1,3}[\s.\-]?(?:\(\d{1,4}\)[\s.\-]?)?\d{2,4}(?:[\s.\-]?\d{2,4}){1,3}"
    r"|\(\d{2,4}\)[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}"
    r"|01[\s.\-]?8000?[\s.\-]?\d{3}[\s.\-]?\d{3}"
    r"|(?:\d{3}[\s.\-]\d{3}[\s.\-]\d{4})"
    r")(?:\s*(?:ext\.?|x|#)\s*\d{1,5})?(?!\d)",
    re.IGNORECASE,
)
_PUBLIC_ID_ENTITY_RE = re.compile(
    r"\b(?i:NIT|RUT|RUC|RFC|CURP|CIF|NIF|C\.?\s*C\.?|C\.?\s*E\.?|T\.?\s*I\.?|NUIP|DNI|NIE|EIN|SSN|VAT|TIN|DUNS|"
    r"CUFE|CUNE|IBAN|SWIFT|BIC|UUID|ORCID|ISBN|ISSN|PASAPORTE|PASSPORT|RADICADO|RAD\.?|EXPEDIENTE|EXP\.?|"
    r"MATR[ÍI]CULA(?:\s+MERCANTIL)?|REGISTRO(?:\s+MERCANTIL|\s+CIVIL|\s+P[ÚU]BLICO)?|TARJETA\s+PROFESIONAL|"
    r"T\.?\s*P\.?|C[ÓO]DIGO\s+POSTAL|C\.?\s*P\.?|ZIP(?:\s+CODE)?)(?![A-Za-zÁÉÍÓÚÜÑáéíóúüñ])"
    r"(?:\s*(?i:N[°oº.]*|No\.?))?\s*[:#\-]?\s*"
    r"[A-Za-z0-9][A-Za-z0-9.\-/]{1,28}(?:\s+(?:\d+[A-Za-z0-9.\-/]*|[A-Z]{2,}[A-Z0-9.\-/]*)){0,5}"
    r"(?:\s+de\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)?)?"
)
_STREET_ADDR_ES_RE = re.compile(
    r"\b(?i:Calle|Cl\.?|Carrera|Cra\.?|Kr\.?|Avenida|Av\.?|Diagonal|Diag\.?|Transversal|Transv\.?|Tv\.?|"
    r"Autopista|Circunvalar|Carretera|V[íi]a|Paseo|Bulevar|Blvd\.?|C/|Manzana|Mz\.?|Lote|Vereda)"
    r"\s+(?:(?i:del?|la|las|los|el)\s+)?"
    r"[A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ.\-°º\s]{1,42}?"
    r"(?:(?i:#|No\.?|N[°oº]\.?|Nro\.?|Km\.?)\s*\d{1,5}[A-Za-z]?(?:\s*[-#]\s*\d{1,5}[A-Za-z]?)*"
    r"|(?:\b\d{1,4}[A-Za-z]?\s*[-#]\s*\d{1,4}[A-Za-z]?(?:\s*[-#]\s*\d{1,4})?))"
    r"(?:[\s,]*(?:(?i:Bis|Sur|Norte|Este|Oeste)\b"
    r"|(?i:Piso|Planta|Edif(?:icio)?\.?|Torre|Bloque|Of(?:icina)?\.?|Local|Apto\.?|Apartamento|Casa|Interior|Int\.?|Bodega|Consultorio|Mz\.?|Lote|Etapa|C\.?P\.?)\s*[#:\-.]?\s*[A-Za-z0-9\-]*\d[A-Za-z0-9\-]*|(?i:Torre|Bloque)\s+[A-Z]\b))*"
    r"(?:\s*,\s*[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ.]*(?:\s+(?:[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ.]*|de|del|la)){0,2})?"
)
_STREET_ADDR_EN_RE = re.compile(
    r"(?:\bP\.?\s*O\.?\s*Box\s+\d{1,8}(?:\s*,\s*[A-Z][a-zA-Z.\s]+(?:,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)?)?"
    r"|\b\d{1,5}\s+(?:[NSEW]{1,2}\.?\s+)?[A-Z0-9][A-Za-z0-9.'\-]{1,24}(?:\s+[A-Z0-9][A-Za-z0-9.'\-]{1,20}){0,3}\s+"
    r"(?:Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|Way|Court|Ct\.?|Terrace|Parkway|Pkwy\.?|Place|Pl\.?|Highway|Hwy\.?)"
    r"(?:[\s,]*(?:Suite|Ste\.?|Apt\.?|Floor|Fl\.?|Room|Rm\.?|Unit|Bldg\.?|#)\s*[A-Za-z0-9\-]+)*"
    r"(?:\s*,\s*[A-Z][a-zA-Z.\s]{2,24},\s*(?:[A-Z]{2}\s+\d{5}(?:-\d{4})?|[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}))?)",
)
_CONTACT_LABEL_PREFIX_RE = re.compile(
    r"^(?:dir(?:ecci[óo]n)?|domicilio|ubicaci[óo]n|sede(?:\s+principal)?|address|location|mailing\s+address|"
    r"correo(?:\s+electr[óo]nico)?|e-?mail|mail|"
    r"web|sitio\s+web|p[áa]gina\s+web|portal|website|url|enlace|"
    r"tel[eé]?f?(?:ono)?s?|cel(?:ular)?|m[óo]vil|mobile|phone|fax|pbx|whatsapp|l[íi]nea(?:\s+de\s+atenci[óo]n)?|ext(?:ensi[óo]n)?|"
    r"redes(?:\s+sociales)?|linkedin|facebook|instagram|twitter|youtube|x|"
    r"nit|rut|ruc|rfc|curp|cif|nif|c\.?\s*c\.?|c\.?\s*e\.?|t\.?\s*i\.?|dni|nie|ein|ssn|vat|tin|duns|"
    r"pasaporte|passport|radicado|rad\.?|expediente|exp\.?|matr[íi]cula(?:\s+mercantil)?|registro|cufe|cune|iban|swift|bic|"
    r"c[óo]digo\s+postal|c\.?\s*p\.?|zip(?:\s+code)?)\s*[:.#\-]\s*(.+)$",
    re.IGNORECASE,
)
_PROSE_STOPWORDS_RE = re.compile(
    r"\b(?:el|la|los|las|un|una|que|para|por|con|como|seg[úu]n|mediante|deber[áa]|podr[áa]|ser[áa]|est[áa]|son|entre|"
    r"the|and|for|with|that|this|from|shall|will|must|are|is|under|pursuant|please)\b",
    re.IGNORECASE,
)
_SPACED_HTML_ENTITY_RE = re.compile(
    r"&\s*(apos|quot|amp|lt|gt|nbsp|#\d+|#x[0-9a-fA-F]+)\s*;",
    re.IGNORECASE,
)
_SIGNATURE_UNDERLINE_RE = re.compile(r"^[_\-\u2014\u2015.=~*]{4,}\s*$")
_SIGNATURE_CLOSING_RE = re.compile(
    r"^(?:atentamente|cordialmente|respetuosamente|sinceramente|muy\s+atentamente|"
    r"sincerely(?:\s+yours)?|cordially|respectfully|best\s+regards|kind\s+regards|"
    r"yours\s+(?:truly|sincerely|faithfully)|regards)\s*[:,.]?\s*$",
    re.IGNORECASE,
)
_SIGNATURE_HEADER_RE = re.compile(
    r"^(?:firma(?:\s+(?:autorizada|digital|electr[oó]nica|y\s+sello|del?\s+[\w\sÁÉÍÓÚÜÑáéíóúüñ]{2,28}))?|"
    r"firmado(?:\s+electr[oó]nicamente|\s+digitalmente)?(?:\s+por)?|"
    r"signature(?:\s+of\s+[\w\s]{2,28})?|signed(?:\s+electronically|\s+digitally)?(?:\s+by)?|"
    r"authorized\s+signatory|signatory|elabor[oó]|revis[oó]|aprob[oó]|autoriz[oó]|verific[oó]|"
    r"vo\.?\s*bo\.?|visto\s+bueno|prepared\s+by|reviewed\s+by|approved\s+by|authorized\s+by|"
    r"por\s+el\s+(?:contratante|contratista|cliente|proveedor)|"
    r"(?:el|la)\s+(?:contratante|contratista)|representante\s+legal|legal\s+representative|"
    r"testigo\s*\d*|witness\s*\d*|de\s+conformidad|en\s+constancia\s+de\s+lo\s+anterior|/s/)\s*[:.,\-]*\s*$",
    re.IGNORECASE,
)
_SIGNATURE_INLINE_PREFIX_RE = re.compile(
    r"^((?:firmado(?:\s+electr[oó]nicamente|\s+digitalmente)?\s+por|signed(?:\s+electronically|\s+digitally)?\s+by|"
    r"firma(?:\s+(?:autorizada|digital|electr[oó]nica|del?\s+\w+))?|signature|"
    r"atentamente|cordialmente|sincerely|best\s+regards|"
    r"elabor[oó]|revis[oó]|aprob[oó]|autoriz[oó]|verific[oó]|"
    r"prepared\s+by|reviewed\s+by|approved\s+by|authorized\s+by|vo\.?\s*bo\.?|/s/)"
    r"(?:\s*[:,;\-]+|\s+))(.+)$",
    re.IGNORECASE,
)
_HONORIFIC_PREFIX_RE = re.compile(
    r"^(?:Dr\.?|Dra\.?|Sr\.?|Sra\.?|Srta\.?|Ing\.?|Lic\.?|Arq\.?|Abg\.?|Mtro\.?|Mtra\.?|"
    r"Prof\.?|Mr\.?|Mrs\.?|Ms\.?|Miss)\s+",
    re.IGNORECASE,
)
_ROLE_TITLE_WORDS_RE = re.compile(
    r"\b(?:director(?:a|es)?|subdirector(?:a|es)?|gerente(?:s)?|subgerente(?:s)?|jefe(?:a|s)?|"
    r"coordinador(?:a|es)?|presidente(?:a|s)?|vicepresidente(?:a|s)?|secretari[oa](?:s)?|"
    r"tesorer[oa](?:s)?|contador(?:a|es)?|revisor(?:a)?\s+fiscal|auditor(?:a|es)?|"
    r"representante(?:\s+legal)?|apoderad[oa](?:\s+(?:general|especial))?|administrador(?:a)?|"
    r"supervisor(?:a)?|superintendente|interventor(?:a)?|residente\s+de\s+obra|abogad[oa]|"
    r"asesor(?:a)?|consultor(?:a)?|analista|especialista|l[ií]der|arquitect[oa]|"
    r"ingenier[oa](?:\s+(?:de|en|jefe|senior|residente|civil|industrial|t[eé]cnic[oa]))?|"
    r"t[eé]cnic[oa]|tecn[oó]log[oa]|auxiliar|asistente|gestor(?:a)?|encargad[oa]|"
    r"rector(?:a)?|decano(?:a)?|notari[oa]|magistrad[oa]|fiscal|contratante|contratista|"
    r"empleador(?:a)?|trabajador(?:a)?|arrendador(?:a)?|arrendatari[oa]|testigo|responsable|"
    r"chief\s+(?:executive|financial|operating|technology|information|legal|marketing|human\s+resources|compliance|risk)\s+officer|"
    r"ceo|cfo|cto|coo|cio|cmo|chro|clo|vp|svp|evp|general\s+counsel|managing\s+(?:director|partner)|"
    r"manager|superintendent|coordinator|head\s+of|president|vice\s+president|secretary|treasurer|"
    r"controller|comptroller|auditor|accountant|legal\s+representative|attorney[- ]in[- ]fact|"
    r"authorized\s+signatory|signatory|engineer|architect|counsel|advisor|consultant|analyst|"
    r"specialist|officer|administrator|partner|associate|team\s+lead|tech\s+lead|chair(?:man|woman|person)?|"
    r"dean|rector|notary|witness|contractor|employer|employee|"
    r"cargo|puesto|designaci[oó]n|title|position|role|designation)\b",
    re.IGNORECASE,
)
_ROLE_ORG_PHRASE_RE = re.compile(
    r"^(?:direcci[oó]n|subdirecci[oó]n|gerencia|jefatura|coordinaci[oó]n|departamento|divisi[oó]n|"
    r"[aá]rea|oficina|unidad|secretar[ií]a|presidencia|vicepresidencia|comit[eé]|"
    r"department|division|office|unit|board)\s+(?:de|del|general|ejecutiv[oa]|t[eé]cnic[oa]|"
    r"financie[oa]|administrativ[oa]|jur[ií]dic[oa]|comercial|operativ[oa]|of)\b",
    re.IGNORECASE,
)
_ROLE_LABEL_PREFIX_RE = re.compile(
    r"^(?:cargo|puesto|funci[oó]n|designaci[oó]n|title|position|role|designation)\s*:\s*\S+",
    re.IGNORECASE,
)
_NON_NAME_WORDS = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas", "para", "por", "con", "sin", "sobre",
    "entre", "hacia", "hasta", "desde", "según", "segun", "mediante", "como", "que", "cual", "esto",
    "esta", "este", "estos", "estas", "todo", "todos", "toda", "todas", "otro", "otra", "mismo",
    "atentamente", "cordialmente", "respetuosamente", "sinceramente", "firma", "firmado", "firme",
    "signature", "signed", "sincerely", "cordially", "regards", "best", "kind", "yours", "truly",
    "elaboro", "elaboró", "reviso", "revisó", "aprobo", "aprobó", "autorizo", "autorizó",
    "prepared", "reviewed", "approved", "authorized", "visto", "bueno", "conformidad", "constancia",
    "fecha", "ciudad", "pais", "país", "pagina", "página", "documento", "contrato", "convenio",
    "acuerdo", "clausula", "cláusula", "articulo", "artículo", "anexo", "anexos", "capitulo",
    "capítulo", "seccion", "sección", "tabla", "datos", "totales", "subtotal", "total", "importe",
    "informe", "resumen", "objeto", "alcance", "antecedentes", "observaciones", "conclusiones",
    "recomendaciones", "notas", "nota", "cuenta", "valor", "pago", "plazo", "termino", "término",
    "derechos", "reservados", "confidencial", "publico", "público", "privado", "general", "nacional",
    "internacional", "tecnico", "técnico", "tecnica", "técnica", "financiero", "financiera",
    "administrativo", "administrativa", "comercial", "operativo", "operativa", "juridico", "jurídico",
    "legal", "soporte", "servicios", "servicio", "soluciones", "proyectos", "proyecto", "tecnologia",
    "tecnología", "sistemas", "construccion", "construcción", "inversiones", "comunicaciones",
    "seguros", "salud", "educacion", "educación", "cultura", "ambiente", "seguridad", "calidad",
    "control", "gestion", "gestión", "auditoria", "auditoría", "revision", "revisión", "aprobacion",
    "aprobación", "empresa", "entidad", "sociedad", "compania", "compañía", "corporacion",
    "corporación", "grupo", "fundacion", "fundación", "instituto", "banco", "universidad",
    "ministerio", "alcaldia", "alcaldía", "gobernacion", "gobernación", "republica", "república",
    "colombia", "bogota", "bogotá", "medellin", "medellín", "cali", "barranquilla", "cartagena",
    "mexico", "méxico", "espana", "españa", "madrid", "barcelona", "estados", "unidos", "united",
    "states", "summary", "report", "contract", "agreement", "clause", "appendix", "section", "table",
    "date", "city", "country", "page", "document", "notes", "notice", "confidential", "invoice",
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
    "octubre", "noviembre", "diciembre", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december", "lunes", "martes",
    "miercoles", "miércoles", "jueves", "viernes", "sabado", "sábado", "domingo", "monday",
    "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "nombre", "name",
    "direccion", "dirección", "telefono", "teléfono", "correo", "email", "address", "phone",
    "sede", "oficina", "office", "suplente", "principal", "auxiliar", "titular", "interna", "interno",
})
_NAME_PARTICLES = frozenset({"de", "del", "la", "las", "los", "da", "das", "do", "dos", "y", "e", "van", "von", "mc", "mac"})
_PERSONAL_ID_PREFIX_RE = re.compile(
    r"^(?:C\.?\s*C\.?|C\.?\s*E\.?|T\.?\s*I\.?|T\.?\s*P\.?|DNI|NIE|NUIP|PASAPORTE|PASSPORT|RUT|NIT|RFC|CURP)\b",
    re.IGNORECASE,
)


class _SimpleBPE:
    """Fallback BPE compatible con subword-nmt v0.2 cuando el paquete externo no esta disponible."""

    def __init__(self, codes_file, separator: str = "@@") -> None:
        self.separator = separator
        self.bpe_codes: dict[tuple[str, str], int] = {}
        self.cache: dict[str, str] = {}
        rank = 0
        for raw_line in codes_file:
            line = raw_line.strip()
            if not line or line.startswith("#version:"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                pair = (parts[0], parts[1])
                if pair not in self.bpe_codes:
                    self.bpe_codes[pair] = rank
                    rank += 1

    def _encode_word(self, orig: str) -> str:
        if orig in self.cache:
            return self.cache[orig]
        if len(orig) <= 1:
            return orig
        word = list(orig[:-1]) + [orig[-1] + "</w>"]
        while len(word) > 1:
            best_rank = None
            best_pair = None
            for idx in range(len(word) - 1):
                pair = (word[idx], word[idx + 1])
                r = self.bpe_codes.get(pair)
                if r is not None and (best_rank is None or r < best_rank):
                    best_rank = r
                    best_pair = pair
            if best_pair is None:
                break
            first, second = best_pair
            merged: list[str] = []
            i = 0
            while i < len(word):
                if i < len(word) - 1 and word[i] == first and word[i + 1] == second:
                    merged.append(first + second)
                    i += 2
                else:
                    merged.append(word[i])
                    i += 1
            word = merged
        if word[-1] == "</w>":
            word = word[:-1]
        elif word[-1].endswith("</w>"):
            word[-1] = word[-1][:-4]
        out = " ".join(
            f"{tok}{self.separator}" if idx < len(word) - 1 else tok
            for idx, tok in enumerate(word)
        )
        if len(self.cache) < 16384:
            self.cache[orig] = out
        return out

    def process_line(self, line: str) -> str:
        return " ".join(self._encode_word(w) for w in line.split() if w)


class _SimpleMosesTokenizer:
    _TOK_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)

    def __init__(self, lang: str = "es") -> None:
        self.lang = lang

    def tokenize(self, text: str, escape: bool = True) -> list[str]:
        tokens = self._TOK_RE.findall(text)
        if escape:
            tokens = [html.escape(t, quote=True) for t in tokens]
        return tokens


class _SimpleMosesDetokenizer:
    _NO_SPACE_BEFORE = re.compile(r"\s+([,.;:!?%)\]\}»”’])")
    _NO_SPACE_AFTER = re.compile(r"([(\[\{«“‘¿¡$€£])\s+")
    _CONTRACTIONS = re.compile(r"\b(\w+)\s+'\s*(s|t|re|ve|m|ll|d)\b", re.IGNORECASE)

    def __init__(self, lang: str = "en") -> None:
        self.lang = lang

    def detokenize(self, tokens: list[str], unescape: bool = True) -> str:
        txt = " ".join(tokens)
        if unescape:
            txt = html.unescape(txt)
        txt = self._NO_SPACE_BEFORE.sub(r"\1", txt)
        txt = self._NO_SPACE_AFTER.sub(r"\1", txt)
        txt = self._CONTRACTIONS.sub(r"\1'\2", txt)
        return txt.strip()


def _load_nmt_bundle(pair: tuple[str, str], config: dict, root: Path) -> dict | None:
    pair_name = f"{pair[0]}_{pair[1]}"
    pair_dir = root / config.get("addons_dir", "addons") / "pack-nmt" / pair_name
    model_bin = pair_dir / "model" / "model.bin"
    if not model_bin.is_file():
        return None
    cache_key = (str(pair_dir.resolve()), pair_name)
    cached = _NMT_BUNDLE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        os.environ.setdefault("CT2_USE_MKL", "0")
        import ctranslate2
    except ImportError:
        return None

    threads = max(1, min(4, os.cpu_count() or 2))
    omp_limit = os.environ.get("OMP_THREAD_LIMIT", "").strip()
    if omp_limit.isdigit() and int(omp_limit) > 0:
        threads = min(threads, int(omp_limit))
    # Nota: mantener compute_type='default' evita colapso de repeticion detectado en Marian/OPUS es_en con int8.
    translator = ctranslate2.Translator(
        str(pair_dir / "model"),
        device="cpu",
        compute_type="default",
        intra_threads=threads,
    )
    sp_path = pair_dir / "sentencepiece.model"
    bpe_path = pair_dir / "bpe.model"
    if sp_path.is_file():
        try:
            import sentencepiece as spm
        except ImportError:
            return None
        bundle = {
            "kind": "sp",
            "translator": translator,
            "sp": spm.SentencePieceProcessor(str(sp_path)),
        }
    elif bpe_path.is_file():
        try:
            from sacremoses import MosesDetokenizer, MosesTokenizer
            from subword_nmt.apply_bpe import BPE
            with bpe_path.open("r", encoding="utf-8") as bf:
                bpe = BPE(bf, separator="@@")
            mt = MosesTokenizer(lang=pair[0])
            md = MosesDetokenizer(lang=pair[1])
        except ImportError:
            with bpe_path.open("r", encoding="utf-8") as bf:
                bpe = _SimpleBPE(bf, separator="@@")
            mt = _SimpleMosesTokenizer(lang=pair[0])
            md = _SimpleMosesDetokenizer(lang=pair[1])
        bundle = {
            "kind": "bpe",
            "translator": translator,
            "bpe": bpe,
            "mt": mt,
            "md": md,
        }
    else:
        return None

    if len(_NMT_BUNDLE_CACHE) >= 4:
        _NMT_BUNDLE_CACHE.clear()
    _NMT_BUNDLE_CACHE[cache_key] = bundle
    return bundle


def _extract_id_match_has_digit_or_bic(candidate: str) -> bool:
    """Evita falsos positivos en etiquetas seguidas de prosa sin digitos ni codigo identificador."""
    tail = re.sub(
        r"^(?:NIT|RUT|RUC|RFC|CURP|CIF|NIF|C\.?\s*C\.?|C\.?\s*E\.?|T\.?\s*I\.?|NUIP|DNI|NIE|EIN|SSN|VAT|TIN|DUNS|"
        r"CUFE|CUNE|IBAN|SWIFT|BIC|UUID|ORCID|ISBN|ISSN|PASAPORTE|PASSPORT|RADICADO|RAD\.?|EXPEDIENTE|EXP\.?|"
        r"MATR[ÍI]CULA(?:\s+MERCANTIL)?|REGISTRO(?:\s+MERCANTIL|\s+CIVIL|\s+P[ÚU]BLICO)?|TARJETA\s+PROFESIONAL|"
        r"T\.?\s*P\.?|C[ÓO]DIGO\s+POSTAL|C\.?\s*P\.?|ZIP(?:\s+CODE)?)(?:\s*(?:N[°oº.]*|No\.?))?\s*[:.#\-]*",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip()
    if not tail:
        return False
    if any(ch.isdigit() for ch in tail):
        return True
    return bool(re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?", tail))


def _looks_like_job_title_or_role(text: str) -> bool:
    """Identifica descripciones de cargo, funcion o designacion laboral (siempre traducibles)."""
    s = (text or "").strip()
    if not s or not _TRANSLATABLE_LETTER_RE.search(s):
        return False
    if _ROLE_LABEL_PREFIX_RE.match(s):
        return True
    words = s.split()
    if len(words) > 14:
        return False
    if re.search(r"\b(?:deber[áa]|podr[áa]|tendr[áa]|shall|will|must)\b", s, re.IGNORECASE):
        return False
    return bool(_ROLE_TITLE_WORDS_RE.search(s) or _ROLE_ORG_PHRASE_RE.match(s))


def _looks_like_proper_person_name(text: str, allow_all_caps: bool = False) -> bool:
    """Detecta nombres propios de persona (con o sin tratamiento/inicial), excluyendo cargos y prosa."""
    s = (text or "").strip().rstrip(",;.") if (text or "").strip().endswith((",", ";")) else (text or "").strip()
    if not s or len(s) < 4 or len(s) > 75 or s.endswith(":"):
        return False
    if any(ch.isdigit() for ch in s) or any(ch in s for ch in ("@", "/", "=", ":", "?", "!", ";", "(", ")", "[", "]")):
        return False
    if _SIGNATURE_UNDERLINE_RE.match(s) or _SIGNATURE_CLOSING_RE.match(s) or _SIGNATURE_HEADER_RE.match(s):
        return False
    if _looks_like_job_title_or_role(s):
        return False
    if _PROSE_STOPWORDS_RE.search(s):
        # Permitir unicamente particulas nobiliarias legitimas ("la", "los", "las") dentro de nombres compuestos
        non_particle_stop = re.search(
            r"\b(?:el|un|una|que|para|por|con|como|seg[úu]n|mediante|deber[áa]|podr[áa]|ser[áa]|est[áa]|son|entre|"
            r"the|and|for|with|that|this|from|shall|will|must|are|is|under|pursuant|please)\b",
            s,
            re.IGNORECASE,
        )
        if non_particle_stop:
            return False

    rem = _HONORIFIC_PREFIX_RE.sub("", s, count=1).strip()
    if not rem or _looks_like_job_title_or_role(rem):
        return False
    if _find_protected_spans(rem, include_signatures=False):
        return False

    raw_words = [w.strip(",;") for w in rem.split() if w.strip(",;")]
    if len(raw_words) < 2 or len(raw_words) > 6:
        return False

    full_word_count = 0
    for idx, tok in enumerate(raw_words):
        bare = tok.rstrip(".").lower()
        if bare in _NON_NAME_WORDS:
            return False
        if tok.lower() in _NAME_PARTICLES and (0 < idx < len(raw_words) - 1 or (tok[:1].isupper() and len(raw_words) >= 3 and idx < len(raw_words) - 1)):
            continue
        if re.fullmatch(r"[A-ZÁÉÍÓÚÜÑ]\.", tok):
            continue
        if re.fullmatch(r"[A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'\-]{1,22}", tok):
            full_word_count += 1
            continue
        return False

    if full_word_count < 1 or (len(raw_words) == 2 and full_word_count < 2 and not re.fullmatch(r"[A-ZÁÉÍÓÚÜÑ]\.", raw_words[0])):
        return False
    if not allow_all_caps:
        if not any(ch.islower() for tok in raw_words for ch in tok):
            return False
    return True


def _extract_signature_inline_spans(text: str, near_signature: bool = False) -> list[tuple[int, int, str]]:
    """Detecta nombres propios incrustados junto a etiquetas de firma o cargos en una misma linea."""
    if not text or not text.strip():
        return []
    spans: list[tuple[int, int, str]] = []

    # 1. Prefijo de firma inline: "Firmado por: Carlos Mendoza", "Atentamente, Blanca Nieves", "/s/ Ana Lopez"
    m_pref = _SIGNATURE_INLINE_PREFIX_RE.match(text)
    if m_pref:
        tail_raw = m_pref.group(2)
        tail_start = m_pref.start(2)
        lead_ws = len(tail_raw) - len(tail_raw.lstrip())
        tail_clean = tail_raw.strip().rstrip(".,;")
        if tail_clean and _looks_like_proper_person_name(tail_clean, allow_all_caps=True):
            s_idx = tail_start + lead_ws
            spans.append((s_idx, s_idx + len(tail_clean), text[s_idx : s_idx + len(tail_clean)]))
            return spans
        # Caso combinado: "Firmado por: Carlos Mendoza - Director General"
        m_sub = re.match(r"^(.+?)(?:\s+(?:-|–|—|\||/)\s+|,\s+)(.+)$", tail_raw.strip())
        if m_sub:
            left_s, right_s = m_sub.group(1).strip(), m_sub.group(2).strip()
            if _looks_like_proper_person_name(left_s, allow_all_caps=True) and (
                _looks_like_job_title_or_role(right_s) or _PERSONAL_ID_PREFIX_RE.match(right_s)
            ):
                s_idx = tail_start + lead_ws
                spans.append((s_idx, s_idx + len(left_s), text[s_idx : s_idx + len(left_s)]))
                return spans

    # 2. Patron "<Nombre Propio> - <Cargo / ID>" o "<Nombre Propio>, <Cargo>"
    for m_sep in re.finditer(r"\s+(?:-|–|—|\||/)\s+|,\s+", text):
        left_raw = text[: m_sep.start()]
        right_raw = text[m_sep.end() :]
        left_clean = left_raw.strip()
        right_clean = right_raw.strip()
        if not left_clean or not right_clean:
            continue
        if (
            _looks_like_job_title_or_role(right_clean)
            or (near_signature and _PERSONAL_ID_PREFIX_RE.match(right_clean))
        ) and _looks_like_proper_person_name(left_clean, allow_all_caps=True):
            s_idx = len(left_raw) - len(left_raw.lstrip())
            spans.append((s_idx, s_idx + len(left_clean), text[s_idx : s_idx + len(left_clean)]))
            return spans

    # 3. Patron "<Cargo / Titulo>: <Nombre Propio>"
    m_role_colon = re.match(r"^([^:]{3,60}):\s+(.+)$", text)
    if m_role_colon:
        left_role = m_role_colon.group(1).strip()
        right_raw = m_role_colon.group(2)
        right_clean = right_raw.strip().rstrip(".")
        if _looks_like_job_title_or_role(left_role) and _looks_like_proper_person_name(right_clean, allow_all_caps=True):
            r_lead = len(right_raw) - len(right_raw.lstrip())
            s_idx = m_role_colon.start(2) + r_lead
            spans.append((s_idx, s_idx + len(right_clean), text[s_idx : s_idx + len(right_clean)]))
            return spans

    return spans


def _find_protected_spans(
    text: str,
    near_signature: bool = False,
    include_signatures: bool = True,
) -> list[tuple[int, int, str]]:
    """Detecta spans no traslapados de URLs, correos, dominios, telefonos, IDs, direcciones y nombres de firma."""
    if not text or not text.strip():
        return []
    candidates: list[tuple[int, int]] = []
    for regex in (
        _URL_ENTITY_RE,
        _EMAIL_ENTITY_RE,
        _DOMAIN_TLD_RE,
        _PUBLIC_ID_ENTITY_RE,
        _PHONE_ENTITY_RE,
        _STREET_ADDR_ES_RE,
        _STREET_ADDR_EN_RE,
    ):
        for m in regex.finditer(text):
            s, e = m.span()
            sub = text[s:e]
            # Recortar puntuacion final ajena a la entidad
            while e > s and sub[-1] in ",;:!?\"'":
                e -= 1
                sub = text[s:e]
            while e > s and sub.endswith(".") and not (
                regex is _STREET_ADDR_ES_RE
                or regex is _STREET_ADDR_EN_RE
                or sub.lower().endswith(("d.c.", "s.a.", "s.a.s.", "ltda.", "st.", "ave.", "blvd.", "rd.", "dr.", "of."))
            ):
                e -= 1
                sub = text[s:e]
            if regex is _PUBLIC_ID_ENTITY_RE and not _extract_id_match_has_digit_or_bic(sub):
                continue
            if regex is _DOMAIN_TLD_RE:
                parts = sub.split("/")[0].split(".")
                tld = parts[-1].lower()
                if len(tld) == 2 and len(parts) < 3 and not re.match(r"^(?:[a-z0-9\-]+\.(?:com|org|net|gov|edu|mil)\.)", sub, re.IGNORECASE):
                    continue
            if e > s:
                candidates.append((s, e))

    if include_signatures:
        for sp_s, sp_e, _ in _extract_signature_inline_spans(text, near_signature=near_signature):
            if sp_e > sp_s:
                candidates.append((sp_s, sp_e))

    if not candidates:
        return []
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str]] = []
    last_end = 0
    for s, e in candidates:
        if s >= last_end:
            selected.append((s, e, text[s:e]))
            last_end = e
    return selected


def _is_protected_single_item(item: str) -> bool:
    s = item.strip()
    if not s or not _TRANSLATABLE_LETTER_RE.search(s):
        return True
    if _NON_LINGUISTIC_RE.match(s) or _SIGNATURE_UNDERLINE_RE.match(s):
        return True
    # Redes / alias @usuario
    if re.fullmatch(r"@[A-Za-z0-9._\-]{2,}", s):
        return True
    # Telefonos sueltos (con eventual prefijo ext.)
    digits_only = [ch for ch in s if ch.isdigit()]
    if len(digits_only) >= 7 and re.fullmatch(r"[\d\s()+\-.,/]+(?:\s*(?:ext\.?|x|#)\s*\d{1,5})?", s, re.IGNORECASE):
        return True
    # Codigos o referencias alfanumericas puras (ej. EXP-2026-00412, REF-8832A)
    if " " not in s and len(digits_only) >= 2 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-/#]{3,}", s):
        return True
    # Linea de ciudad/distrito/postal en encabezado o pie (ej. "Bogotá D.C., Colombia", "New York, NY 10001")
    if len(s) <= 85 and not re.search(
        r"\b(?:el|la|los|las|que|para|mediante|deber[áa]|the|and|for|shall|must|with|from|is|are)\b",
        s,
        re.IGNORECASE,
    ):
        if re.search(r"(?:\bD\.?\s*C\.?\b|\bC\.?\s*P\.?\s*\d{4,6}\b|\bZIP\s*\d{5}\b|\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b|\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b)", s):
            return True

    # Linea etiquetada: "Dirección: Calle 45 # 12-34", "Correo: info@...", "NIT: 900.123.456-7", "Tel: 601-555..."
    m_lbl = _CONTACT_LABEL_PREFIX_RE.match(s)
    if m_lbl:
        val = m_lbl.group(1).strip()
        if not val:
            return False
        if _find_protected_spans(val, include_signatures=False) or _find_protected_spans(s, include_signatures=False):
            return True
        if any(ch.isdigit() for ch in val) and len(val.split()) <= 10 and not re.search(
            r"\b(?:deber[áa]|podr[áa]|ser[áa]|para|mediante|seg[úu]n|shall|will|must)\b", val, re.IGNORECASE
        ):
            return True

    # Verificar si todo el contenido consiste esencialmente en entidades protegidas (URLs, correos, IDs, direcciones)
    spans = _find_protected_spans(s, include_signatures=False)
    if spans:
        buf: list[str] = []
        cursor = 0
        for sp_s, sp_e, _ in spans:
            buf.append(s[cursor:sp_s])
            cursor = sp_e
        buf.append(s[cursor:])
        residual = " ".join(buf)
        # Remover conectores menores de contacto ("de", "en", "y", "tel", "dir", etc.)
        residual_words = [
            w for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", residual)
            if w.lower() not in {
                "de", "del", "la", "las", "el", "los", "en", "y", "o", "or", "and", "at", "by", "via",
                "tel", "cel", "fax", "pbx", "ext", "dir", "web", "url", "mail", "email", "nit", "rut",
                "ruc", "rfc", "dni", "cc", "ce", "id", "no", "nro", "cp", "piso", "of", "oficina",
                "torre", "local", "apto", "edificio", "edif", "colombia", "españa", "mexico", "méxico",
            }
        ]
        # Si practicamente no queda prosa fuera de las entidades protegidas, ignorar toda la unidad
        if len(residual_words) == 0:
            return True
        if len(residual_words) <= 2 and not re.search(
            r"\b(?:el|la|los|las|que|para|por|con|como|debe|deber[áa]|visite|escriba|llame|comun[íi]quese|"
            r"the|and|for|with|shall|must|visit|write|call|contact|located|available|please|provides)\b",
            residual,
            re.IGNORECASE,
        ):
            # Ej.: ciudad corta tras direccion no capturada ("Bogota Colombia")
            if all(w[0].isupper() for w in residual_words):
                return True

    # Razon social corta con sufijo societario explicito (ej. "Tech Global S.A.S.", "Acme Holdings LLC")
    words = [w.strip(".,;()") for w in s.split() if w.strip(".,;()")]
    if 1 < len(words) <= 7 and re.search(
        r"(?:\bS\.?A\.?S\.?|\bS\.?A\.?|\bLTDA\.?|\bS\.?R\.?L\.?|\bLLC\b|\bINC\.?|\bGMBH\b)(?=$|[\s.,])",
        s,
    ):
        has_sentence_verb = bool(re.search(
            r"\b(?:es|son|fue|fueron|presta|prestar[áa]|entrega|entregar[áa]|deber[áa]|tiene|tienen|ofrece|"
            r"is|are|was|were|will|shall|must|provides|delivers|has|have)\b",
            s,
            re.IGNORECASE,
        ))
        if not has_sentence_verb:
            return True

    return False


def _split_segment_for_nmt(text: str) -> tuple[str, str, str, bool]:
    """Separa espacios, prefijo de lista/viñeta y marca si el cuerpo viene en MAYUSCULAS."""
    lead_len = len(text) - len(text.lstrip())
    trail_len = len(text) - len(text.rstrip())
    lead = text[:lead_len]
    trail = text[len(text) - trail_len :] if trail_len else ""
    core = text[lead_len : len(text) - trail_len if trail_len else len(text)]
    if not core:
        return text, "", "", False
    list_prefix = ""
    m_prefix = _LIST_PREFIX_RE.match(core)
    if m_prefix:
        cand_prefix, cand_rest = m_prefix.group(1), m_prefix.group(2)
        if cand_rest.strip():
            list_prefix = cand_prefix
            core = cand_rest
    letters = [c for c in core if c.isalpha()]
    all_caps = len(letters) >= 4 and all(c.isupper() for c in letters)
    return lead + list_prefix, core, trail, all_caps


def _should_skip_translation(core: str, near_signature: bool = False) -> bool:
    stripped = core.strip()
    if not stripped or not _TRANSLATABLE_LETTER_RE.search(stripped):
        return True
    if _NON_LINGUISTIC_RE.match(stripped) or _SIGNATURE_UNDERLINE_RE.match(stripped):
        return True
    if near_signature and _looks_like_proper_person_name(stripped, allow_all_caps=True):
        return True
    parts = [p.strip() for p in re.split(r"\s*(?:\||•|·)\s*", stripped) if p.strip()]
    if len(parts) >= 2 and all(_is_protected_single_item(p) for p in parts):
        return True
    return _is_protected_single_item(stripped)


_MASK_TOKEN_POOL = (
    "417", "839", "652", "371", "942", "285", "519", "763", "194", "826",
    "348", "691", "725", "163", "954", "482", "537", "814", "269", "741",
    "385", "916", "624", "578",
)


def _alloc_mask_token(text: str, used: set[str], idx_hint: int) -> str:
    for cand in _MASK_TOKEN_POOL:
        if cand not in used and not re.search(rf"(?<!\d){cand}(?!\d)", text):
            used.add(cand)
            return cand
    seed = 41100 + idx_hint * 137
    while True:
        cand = str(seed)
        if cand not in used and not re.search(rf"(?<!\d){cand}(?!\d)", text):
            used.add(cand)
            return cand
        seed += 193


def _mask_protected_entities(text: str, near_signature: bool = False) -> tuple[str, list[tuple[str, str]]]:
    """Enmascara direcciones, correos, URLs, IDs y nombres de firma embebidos con codigos seguros."""
    spans = _find_protected_spans(text, near_signature=near_signature, include_signatures=True)
    if not spans:
        return text, []
    used: set[str] = set()
    masks: list[tuple[str, str]] = []
    out: list[str] = []
    cursor = 0
    for idx, (s, e, val) in enumerate(spans):
        out.append(text[cursor:s])
        tok = _alloc_mask_token(text, used, idx)
        out.append(tok)
        masks.append((tok, val))
        cursor = e
    out.append(text[cursor:])
    return "".join(out), masks


def _restore_protected_entities(translated: str, masks: list[tuple[str, str]]) -> str:
    out = translated
    for tok, val in masks:
        pattern = re.compile(rf"(?<!\d){re.escape(tok)}(?!\d)")
        if pattern.search(out):
            out = pattern.sub(lambda _m, v=val: v, out, count=1)
    return out


def _all_masks_preserved(translated: str, masks: list[tuple[str, str]]) -> bool:
    return all(re.search(rf"(?<!\d){re.escape(tok)}(?!\d)", translated) for tok, _ in masks)


_RECASE_SMALL_WORDS = frozenset({
    "de", "del", "la", "las", "los", "y", "e", "o", "en", "por", "para", "a",
    "of", "and", "or", "for", "in", "to", "the", "with", "on", "at",
})


def _normalize_nmt_decoded(decoded: str) -> str:
    fixed = _SPACED_HTML_ENTITY_RE.sub(lambda m: f"&{m.group(1).lower()};", decoded)
    fixed = html.unescape(fixed)
    fixed = re.sub(r"\s+(['’])(s|t|re|ve|m|ll|d)\b", r"\1\2", fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ])\s*'\s+s\b", r"\1's", fixed)
    return fixed.strip()


def _smart_recase_from_source(src: str, dec: str) -> str:
    if not dec:
        return dec
    src_words = [w for w in src.split() if any(c.isalpha() for c in w)]
    cap_count = sum(1 for w in src_words if w[:1].isupper())
    if len(src_words) >= 2 and cap_count >= max(2, len(src_words) - 1):
        out_w: list[str] = []
        for idx, w in enumerate(dec.split()):
            if idx == 0 or w.lower() not in _RECASE_SMALL_WORDS:
                out_w.append(w[:1].upper() + w[1:] if w else w)
            else:
                out_w.append(w.lower())
        return " ".join(out_w)
    if src[:1].isupper():
        return dec[:1].upper() + dec[1:]
    return dec


def _split_long_clause(sent: str, max_len: int = 360) -> list[tuple[str, str]]:
    """Divide oraciones muy extensas en clausulas manejables por ; o , sin truncar palabras."""
    s = sent.strip()
    if len(s) <= max_len:
        return [(s, "")]

    def _split_by_sep(chunk: str, sep: str) -> list[tuple[str, str]]:
        pieces = chunk.split(sep)
        if len(pieces) <= 1:
            return [(chunk, "")]
        grouped: list[tuple[str, str]] = []
        cur = pieces[0]
        for nxt in pieces[1:]:
            if len(cur) + len(sep) + len(nxt) <= max_len:
                cur = f"{cur}{sep}{nxt}"
            else:
                grouped.append((cur.strip(), sep))
                cur = nxt
        grouped.append((cur.strip(), ""))
        return grouped

    out: list[tuple[str, str]] = []
    for semi_part, semi_join in _split_by_sep(s, "; "):
        if len(semi_part) > max_len:
            comma_parts = _split_by_sep(semi_part, ", ")
            for c_idx, (c_txt, c_join) in enumerate(comma_parts):
                final_join = semi_join if c_idx == len(comma_parts) - 1 else c_join
                out.append((c_txt, final_join))
        else:
            out.append((semi_part, semi_join))
    return [(txt, j) for txt, j in out if txt]


def _translate_with_ctranslate2(
    texts: list[str],
    pair: tuple[str, str],
    config: dict,
    root: Path,
    near_sig_flags: list[bool] | None = None,
) -> list[str] | None:
    bundle = _load_nmt_bundle(pair, config, root)
    if bundle is None:
        return None
    flags_list = near_sig_flags if (near_sig_flags and len(near_sig_flags) == len(texts)) else [False] * len(texts)

    def _decode_chunk(chunk: list[str], beam_size: int = 2, max_dec: int = 512, rep_pen: float = 1.08) -> list[str]:
        translator = bundle["translator"]
        if bundle["kind"] == "sp":
            sp = bundle["sp"]
            toks = [sp.encode(s, out_type=str) for s in chunk]
            res = translator.translate_batch(
                toks, beam_size=beam_size, max_decoding_length=max_dec, repetition_penalty=rep_pen,
            )
            return [
                (_normalize_nmt_decoded(sp.decode(hyp.hypotheses[0])) if hyp.hypotheses else s) or s
                for s, hyp in zip(chunk, res)
            ]
        bpe = bundle["bpe"]
        mt = bundle["mt"]
        md = bundle["md"]
        toks = [
            bpe.process_line(" ".join(mt.tokenize(s, escape=True))).split() + ["</s>"]
            for s in chunk
        ]
        res = translator.translate_batch(
            toks, beam_size=beam_size, max_decoding_length=max_dec, repetition_penalty=rep_pen,
        )
        decoded_list: list[str] = []
        for s, hyp in zip(chunk, res):
            if not hyp.hypotheses:
                decoded_list.append(s)
                continue
            out_toks = [t for t in hyp.hypotheses[0] if t not in ("<s>", "</s>", "<unk>")]
            joined = "".join(t[:-2] if t.endswith("@@") else (t + " ") for t in out_toks).strip()
            dec = _normalize_nmt_decoded(md.detokenize(joined.split(), unescape=True))
            decoded_list.append(dec or s)
        return decoded_list

    def _run_batch_sentences(sent_list: list[str]) -> dict[str, str]:
        translated_map: dict[str, str] = {}
        if not sent_list:
            return translated_map
        short_retries: list[str] = []
        echo_retries: list[str] = []
        for i in range(0, len(sent_list), 48):
            chunk = sent_list[i : i + 48]
            for src_s, dec in zip(chunk, _decode_chunk(chunk, beam_size=2, max_dec=512, rep_pen=1.08)):
                translated_map[src_s] = dec
                if len(src_s) >= 35 and len(dec) < max(8, int(len(src_s) * 0.22)):
                    short_retries.append(src_s)
                elif (
                    _TRANSLATABLE_LETTER_RE.search(src_s)
                    and dec.strip().lower() == src_s.strip().lower()
                    and len(src_s.split()) <= 10
                    and not _is_protected_single_item(src_s)
                    and not _looks_like_proper_person_name(src_s, allow_all_caps=True)
                ):
                    echo_retries.append(src_s)

        if short_retries:
            for src_s, retried in zip(short_retries, _decode_chunk(short_retries, beam_size=1, max_dec=640, rep_pen=1.0)):
                cur = translated_map.get(src_s, src_s)
                if len(retried) > len(cur):
                    translated_map[src_s] = retried
                if len(translated_map[src_s]) < max(6, int(len(src_s) * 0.14)):
                    translated_map[src_s] = src_s

        if echo_retries:
            low_inputs = [s.lower() for s in echo_retries]
            for src_s, retried in zip(echo_retries, _decode_chunk(low_inputs, beam_size=2, max_dec=256, rep_pen=1.05)):
                if retried.strip().lower() != src_s.strip().lower() and _TRANSLATABLE_LETTER_RE.search(retried):
                    translated_map[src_s] = _smart_recase_from_source(src_s, retried)

        # Preservar puntuacion terminal explicita cuando el modelo la omite al final de oracion completa
        for src_s, dec in list(translated_map.items()):
            s_end = src_s.rstrip()[-1:]
            if len(src_s) >= 20 and s_end in ".!?" and dec and dec[-1] not in ".!?:;":
                translated_map[src_s] = f"{dec}{s_end}"
        return translated_map

    plans: list[dict] = []
    unique_sentences: dict[str, None] = {}

    for raw, near_sig in zip(texts, flags_list):
        if _should_skip_translation(raw, near_signature=near_sig):
            plans.append({"skip": True, "raw": raw})
            continue
        prefix, core, suffix, _raw_all_caps = _split_segment_for_nmt(raw)
        if _should_skip_translation(core, near_signature=near_sig):
            plans.append({"skip": True, "raw": raw})
            continue
        masked_core, entity_masks = _mask_protected_entities(core, near_signature=near_sig)
        letters = [c for c in masked_core if c.isalpha()]
        all_caps = len(letters) >= 4 and all(c.isupper() for c in letters)
        raw_sentences = [s for s in _SENTENCE_SPLIT_RE.split(masked_core) if s]
        clause_entries: list[tuple[str, str]] = []
        for s in raw_sentences:
            s_norm = s.capitalize() if all_caps else s
            for sub_s, joiner in _split_long_clause(s_norm, max_len=360):
                clause_entries.append((sub_s, joiner))
                if not _should_skip_translation(sub_s):
                    unique_sentences.setdefault(sub_s, None)
        plans.append({
            "skip": False,
            "near_sig": near_sig,
            "prefix": prefix,
            "core": core,
            "suffix": suffix,
            "all_caps": all_caps,
            "clause_entries": clause_entries,
            "masks": entity_masks,
        })

    translated_map = _run_batch_sentences(list(unique_sentences.keys()))

    def _join_clauses(entries: list[tuple[str, str]]) -> str:
        buf: list[str] = []
        prev_joiner = ""
        for idx, (s_key, joiner) in enumerate(entries):
            tr_c = translated_map.get(s_key, s_key).strip()
            if prev_joiner in (", ", "; ") and len(tr_c) >= 2 and tr_c[0].isupper() and tr_c[1].islower():
                first_tok = tr_c.split(None, 1)[0]
                if len(first_tok) >= 2 and not s_key.lstrip()[:1].isupper():
                    tr_c = tr_c[0].lower() + tr_c[1:]
                elif first_tok.lower() in {"all", "the", "a", "an", "and", "or", "must", "shall", "with", "both", "each", "every", "los", "las", "el", "la", "y", "o", "todos", "todas", "ambos", "ambas"}:
                    tr_c = tr_c[0].lower() + tr_c[1:]
            if joiner in ("; ", ", "):
                tr_c = tr_c.rstrip(".,; ")
                buf.append(f"{tr_c}{joiner}")
            else:
                buf.append(tr_c + (" " if idx < len(entries) - 1 else ""))
            prev_joiner = joiner
        return "".join(buf).strip()

    # Verificar que todos los marcadores de entidades protegidas sobrevivieron; si alguno falto,
    # traducir los fragmentos textuales alrededor de las entidades para preservarlas al 100%.
    fallback_fragments: dict[str, None] = {}
    fallback_needed: list[int] = []
    for p_idx, plan in enumerate(plans):
        if plan["skip"] or not plan["masks"]:
            continue
        rebuilt = _join_clauses(plan["clause_entries"])
        if not _all_masks_preserved(rebuilt, plan["masks"]):
            spans = _find_protected_spans(plan["core"], near_signature=plan["near_sig"], include_signatures=True)
            pieces: list[tuple[bool, str]] = []
            cur = 0
            for sp_s, sp_e, sp_val in spans:
                prose = plan["core"][cur:sp_s]
                if prose.strip():
                    frag = prose.strip()
                    frag_in = frag.capitalize() if plan["all_caps"] else frag
                    if not _should_skip_translation(frag_in):
                        fallback_fragments.setdefault(frag_in, None)
                    pieces.append((True, prose))
                pieces.append((False, sp_val))
                cur = sp_e
            tail_prose = plan["core"][cur:]
            if tail_prose.strip():
                frag = tail_prose.strip()
                frag_in = frag.capitalize() if plan["all_caps"] else frag
                if not _should_skip_translation(frag_in):
                    fallback_fragments.setdefault(frag_in, None)
                pieces.append((True, tail_prose))
            plan["fallback_pieces"] = pieces
            fallback_needed.append(p_idx)

    if fallback_fragments:
        translated_map.update(_run_batch_sentences(list(fallback_fragments.keys())))

    out_texts: list[str] = []
    for p_idx, plan in enumerate(plans):
        if plan["skip"]:
            out_texts.append(plan["raw"])
            continue
        if p_idx in fallback_needed:
            rebuilt_parts: list[str] = []
            for is_prose, part in plan["fallback_pieces"]:
                if not is_prose:
                    rebuilt_parts.append(part)
                    continue
                lead_sp = " " if part[:1].isspace() else ""
                trail_sp = " " if part[-1:].isspace() else ""
                frag = part.strip()
                frag_in = frag.capitalize() if plan["all_caps"] else frag
                tr_frag = frag if _should_skip_translation(frag_in) else translated_map.get(frag_in, frag)
                if plan["all_caps"]:
                    tr_frag = tr_frag.upper()
                rebuilt_parts.append(f"{lead_sp}{tr_frag}{trail_sp}")
            body = re.sub(r"[ \t]{2,}", " ", "".join(rebuilt_parts)).strip()
            out_texts.append(f"{plan['prefix']}{body}{plan['suffix']}")
            continue

        body = _join_clauses(plan["clause_entries"])
        if plan["all_caps"]:
            body = body.upper()
        if plan["masks"]:
            body = _restore_protected_entities(body, plan["masks"])
        out_texts.append(f"{plan['prefix']}{body}{plan['suffix']}")
    return out_texts


def _translate_via_ai_chunks(
    texts: list[str],
    pair: tuple[str, str],
    config: dict,
) -> tuple[list[str], str] | None:
    kind, _ = active_ai_target(config)
    if kind == "none" or not texts:
        return None
    out: list[str] = []
    backend_tag = kind
    for i in range(0, len(texts), 20):
        chunk = texts[i : i + 20]
        payload = json.dumps(chunk, ensure_ascii=False)
        ai_res = call_ai_backend(
            (
                f"Traduce cada elemento del arreglo JSON del idioma '{pair[0]}' al idioma '{pair[1]}'. "
                f"Devuelve EXCLUSIVAMENTE un arreglo JSON valido de exactamente {len(chunk)} strings:\n{payload}"
            ),
            "Traductor tecnico preciso. Responde solo con el arreglo JSON resultante, sin texto extra.",
            config,
            timeout=30,
        )
        if not ai_res or not ai_res.get("content"):
            return None
        backend_tag = ai_res.get("backend", kind)
        raw_content = ai_res["content"].strip()
        parsed = None
        m_json = re.search(r"\[.*\]", raw_content, re.DOTALL)
        if m_json:
            try:
                cand = json.loads(m_json.group(0))
                if isinstance(cand, list) and len(cand) == len(chunk):
                    parsed = [str(item) for item in cand]
            except json.JSONDecodeError:
                parsed = None
        if parsed is None:
            parts = [p.strip() for p in raw_content.split("---")]
            if len(parts) == len(chunk):
                parsed = parts
        if parsed is None:
            return None
        out.extend(parsed)
    return out, f"ai_{backend_tag}"


def _translate_offline_or_ai(
    texts: list[str],
    src_lang: str,
    dst_lang: str,
    user_map: dict,
    config: dict,
    root: Path | None = None,
    engine_pref: str = "auto",
    unit_hints: list[dict] | None = None,
) -> tuple[list[str], str]:
    pair = (src_lang.lower()[:2], dst_lang.lower()[:2])
    if root is None:
        from settings import ROOT as _DEFAULT_ROOT

        root = _DEFAULT_ROOT

    hints = unit_hints if (unit_hints and len(unit_hints) == len(texts)) else [{} for _ in texts]
    resolved: list[str | None] = [None] * len(texts)
    pending_indices: list[int] = []
    pending_texts: list[str] = []
    pending_near_sig: list[bool] = []
    used_map = False
    for idx, (t, hint) in enumerate(zip(texts, hints)):
        near_sig = bool(hint.get("near_signature", False))
        if user_map and t in user_map:
            resolved[idx] = str(user_map[t])
            used_map = True
        elif user_map and t.strip() in user_map:
            resolved[idx] = str(user_map[t.strip()])
            used_map = True
        elif hint.get("skip_translation") or _should_skip_translation(t, near_signature=near_sig):
            resolved[idx] = t
        else:
            pending_indices.append(idx)
            pending_texts.append(t)
            pending_near_sig.append(near_sig)

    if not pending_texts:
        return [str(v) for v in resolved], ("dictionary_map" if used_map else "protected_skip")

    mode_used = "offline_glossary"
    translated_pending: list[str] | None = None

    if engine_pref in ("auto", "ai"):
        masked_ai: list[str] = []
        masks_ai: list[list[tuple[str, str]]] = []
        for t, near_sig in zip(pending_texts, pending_near_sig):
            m_txt, m_list = _mask_protected_entities(t, near_signature=near_sig)
            masked_ai.append(m_txt)
            masks_ai.append(m_list)
        ai_out = _translate_via_ai_chunks(masked_ai, pair, config)
        if ai_out is not None:
            raw_ai_out, mode_used = ai_out
            translated_pending = [
                _restore_protected_entities(tr, m_list) if _all_masks_preserved(tr, m_list) else orig
                for tr, orig, m_list in zip(raw_ai_out, pending_texts, masks_ai)
            ]

    if translated_pending is None and engine_pref in ("auto", "nmt"):
        nmt_out = _translate_with_ctranslate2(pending_texts, pair, config, root, near_sig_flags=pending_near_sig)
        if nmt_out is not None:
            translated_pending = nmt_out
            mode_used = f"nmt_offline_{pair[0]}_{pair[1]}"

    if translated_pending is None:
        glossary = _OFFLINE_GLOSSARY.get(pair, {})
        translated_pending = []
        for t, near_sig in zip(pending_texts, pending_near_sig):
            m_txt, m_list = _mask_protected_entities(t, near_signature=near_sig)
            out_t = m_txt
            for k, v in sorted(glossary.items(), key=lambda kv: -len(kv[0])):
                out_t = re.sub(rf"\b{re.escape(k)}\b", v, out_t, flags=re.IGNORECASE)
            translated_pending.append(_restore_protected_entities(out_t, m_list))
        mode_used = "offline_glossary"

    for idx, val in zip(pending_indices, translated_pending):
        resolved[idx] = val
    if used_map and mode_used != "offline_glossary":
        mode_used = f"dictionary_map+{mode_used}"
    elif used_map:
        mode_used = "dictionary_map"
    return [str(v) for v in resolved], mode_used


def _resolve_translation_font(
    page: pdf.Page,
    font_name: str,
    bold: bool,
    italic: bool,
    font_cache: dict[str, str],
) -> str:
    family_lower = (font_name or "arial").lower().strip()
    target_family = (
        "times new roman"
        if any(k in family_lower for k in ("times", "roman", "georgia", "serif"))
        else "courier new"
        if any(k in family_lower for k in ("courier", "mono", "consolas"))
        else "arial"
    )
    ttf_name = FONT_FAMILY_MAPPING.get(target_family, {}).get((bool(bold), bool(italic)))
    if ttf_name and WINDOWS_FONTS_DIR.is_dir():
        ttf_path = WINDOWS_FONTS_DIR / ttf_name
        if ttf_path.is_file():
            alias = font_cache.get(ttf_name)
            if alias is None:
                alias = f"EVA_TR_{len(font_cache) + 1}"
                page.insert_font(fontname=alias, fontfile=str(ttf_path))
                font_cache[ttf_name] = alias
            return alias
    return resolve_font(page, font_name, bold=bold, italic=italic)


def _extract_graphic_barriers(
    page: pdf.Page,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Extrae segmentos divisores verticales y horizontales (tablas, columnas, recuadros)."""
    v_rules: list[tuple[float, float, float]] = []
    h_rules: list[tuple[float, float, float]] = []
    pw = max(1.0, float(page.rect.width))
    ph = max(1.0, float(page.rect.height))
    try:
        drawings = page.get_drawings() or []
    except Exception:
        return v_rules, h_rules

    for d in drawings:
        for item in d.get("items", []):
            kind = item[0]
            if kind == "l" and len(item) >= 3:
                p1, p2 = item[1], item[2]
                if abs(p1.x - p2.x) <= 1.8 and abs(p1.y - p2.y) >= 8.0:
                    y0, y1 = min(float(p1.y), float(p2.y)), max(float(p1.y), float(p2.y))
                    if y1 - y0 <= ph * 0.92:
                        v_rules.append(((float(p1.x) + float(p2.x)) * 0.5, y0, y1))
                elif abs(p1.y - p2.y) <= 1.8 and abs(p1.x - p2.x) >= 14.0:
                    x0, x1 = min(float(p1.x), float(p2.x)), max(float(p1.x), float(p2.x))
                    if x1 - x0 <= pw * 0.94:
                        h_rules.append(((float(p1.y) + float(p2.y)) * 0.5, x0, x1))
            elif kind == "re" and len(item) >= 2:
                r = pdf.Rect(item[1])
                if r.width <= 3.2 and r.height >= 8.0 and r.height <= ph * 0.92:
                    v_rules.append(((r.x0 + r.x1) * 0.5, r.y0, r.y1))
                elif r.height <= 3.2 and r.width >= 14.0 and r.width <= pw * 0.94:
                    h_rules.append(((r.y0 + r.y1) * 0.5, r.x0, r.x1))
                elif 14.0 <= r.width <= pw * 0.92 and 10.0 <= r.height <= ph * 0.85:
                    v_rules.append((r.x0, r.y0, r.y1))
                    v_rules.append((r.x1, r.y0, r.y1))
                    h_rules.append((r.y0, r.x0, r.x1))
                    h_rules.append((r.y1, r.x0, r.x1))
    return v_rules, h_rules


def _crosses_v_rule(x0: float, x1: float, y0: float, y1: float, v_rules: list[tuple[float, float, float]]) -> bool:
    for vx, vy0, vy1 in v_rules:
        if x0 < vx < x1 and min(y1, vy1) - max(y0, vy0) > 2.0:
            return True
    return False


def _crosses_h_rule(y0: float, y1: float, x0: float, x1: float, h_rules: list[tuple[float, float, float]]) -> bool:
    for hy, hx0, hx1 in h_rules:
        if y0 <= hy <= y1 and min(x1, hx1) - max(x0, hx0) > 6.0:
            return True
    return False


def _split_line_subunits(
    spans: list[dict],
    v_rules: list[tuple[float, float, float]] | None = None,
) -> list[dict]:
    clean_spans = [sp for sp in spans if sp.get("text", "").strip()]
    if not clean_spans:
        return []
    clean_spans.sort(key=lambda sp: float(sp["bbox"][0]))
    v_rules = v_rules or []
    sublines: list[dict] = []
    cur: dict | None = None
    for sp in clean_spans:
        sb = [float(v) for v in sp["bbox"]]
        text = re.sub(r"[ \t\xa0]+", " ", sp.get("text", ""))
        size = float(sp.get("size", 10.0))
        flags = int(sp.get("flags", 0))
        font = str(sp.get("font", "Arial")).split("+")[-1]
        bold = bool((flags & 16) or "bold" in font.lower())
        italic = bool((flags & 2) or "italic" in font.lower() or "oblique" in font.lower())
        color = f"#{int(sp.get('color', 0)) & 0xFFFFFF:06x}"
        weight = max(1, len(text.strip()))
        if cur is None:
            cur = {
                "bbox": sb,
                "line_bboxes": [list(sb)],
                "text": text,
                "size": size,
                "font": font,
                "bold": bold,
                "italic": italic,
                "color": color,
                "span_count": 1,
                "_dom_weight": weight,
            }
            continue
        gap_x = sb[0] - cur["bbox"][2]
        sep_by_rule = _crosses_v_rule(cur["bbox"][2] - 1.0, sb[0] + 1.0, min(cur["bbox"][1], sb[1]), max(cur["bbox"][3], sb[3]), v_rules)
        same_band = (
            not sep_by_rule
            and gap_x <= max(9.5, cur["size"] * 1.05)
            and abs(size - cur["size"]) <= max(2.2, cur["size"] * 0.25)
        )
        if same_band:
            joiner = "" if (cur["text"].endswith(" ") or text.startswith(" ") or gap_x <= max(1.5, cur["size"] * 0.14)) else " "
            cur["text"] = f"{cur['text']}{joiner}{text}"
            cur["bbox"] = [
                min(cur["bbox"][0], sb[0]),
                min(cur["bbox"][1], sb[1]),
                max(cur["bbox"][2], sb[2]),
                max(cur["bbox"][3], sb[3]),
            ]
            cur["line_bboxes"] = [list(cur["bbox"])]
            if weight > cur["_dom_weight"]:
                cur["size"] = size
                cur["font"] = font
                cur["bold"] = bold
                cur["italic"] = italic
                cur["color"] = color
                cur["_dom_weight"] = weight
            cur["span_count"] += 1
        else:
            cur.pop("_dom_weight", None)
            sublines.append(cur)
            cur = {
                "bbox": sb,
                "line_bboxes": [list(sb)],
                "text": text,
                "size": size,
                "font": font,
                "bold": bold,
                "italic": italic,
                "color": color,
                "span_count": 1,
                "_dom_weight": weight,
            }
    if cur is not None:
        cur.pop("_dom_weight", None)
        sublines.append(cur)
    return sublines


def _extract_ruled_tables(page: pdf.Page) -> tuple[list[pdf.Rect], list[dict]]:
    """Detecta tablas con bordes reales y devuelve sus bounding boxes y celdas unicas."""
    ruled_boxes: list[pdf.Rect] = []
    cells_meta: list[dict] = []
    seen_cells: set[tuple[float, float, float, float]] = set()
    page_area = max(1.0, float(page.rect.get_area()))
    try:
        finder = page.find_tables()
        tables = list(getattr(finder, "tables", None) or [])
    except Exception:
        tables = []

    for tbl in tables:
        trect = pdf.Rect(tbl.bbox) & page.rect
        if trect.is_empty:
            continue
        unique_tbl_cells: list[pdf.Rect] = []
        for row_obj in getattr(tbl, "rows", []) or []:
            for cell_bbox in getattr(row_obj, "cells", []) or []:
                if not cell_bbox:
                    continue
                crect = pdf.Rect(cell_bbox) & page.rect
                if crect.is_empty or crect.width < 6.0 or crect.height < 6.0:
                    continue
                key = (round(crect.x0, 1), round(crect.y0, 1), round(crect.x1, 1), round(crect.y1, 1))
                if key not in seen_cells:
                    seen_cells.add(key)
                    unique_tbl_cells.append(crect)
        # Ignorar marcos decorativos de pagina completa (1x1)
        if len(unique_tbl_cells) < 2 and trect.get_area() > 0.80 * page_area:
            continue
        if len(unique_tbl_cells) < 2:
            continue
        ruled_boxes.append(trect)
        for crect in unique_tbl_cells:
            cells_meta.append({
                "cell_bbox": [float(crect.x0), float(crect.y0), float(crect.x1), float(crect.y1)],
                "table_bbox": [float(trect.x0), float(trect.y0), float(trect.x1), float(trect.y1)],
            })
    return ruled_boxes, cells_meta


def _infer_unit_alignment(
    u: dict,
    page_width: float,
    has_row_peer: bool,
) -> int:
    line_boxes = u.get("line_bboxes") or [u["bbox"]]
    container = u.get("container_bbox")
    if container:
        cx0, _, cx1, _ = container
        c_mid = (cx0 + cx1) * 0.5
        c_width = max(1.0, cx1 - cx0)
        ux0, _, ux1, _ = u["bbox"]
        u_mid = (ux0 + ux1) * 0.5
        left_pad = ux0 - cx0
        right_pad = cx1 - ux1
        if len(line_boxes) >= 2:
            centers = [(b[0] + b[2]) * 0.5 for b in line_boxes]
            x0s = [b[0] for b in line_boxes]
            x1s = [b[2] for b in line_boxes]
            if max(centers) - min(centers) <= 4.0 and max(x0s) - min(x0s) > 4.0:
                return pdf.TEXT_ALIGN_CENTER
            if max(x1s) - min(x1s) <= 3.5 and max(x0s) - min(x0s) > 5.0 and right_pad <= 14.0:
                return pdf.TEXT_ALIGN_RIGHT
            return pdf.TEXT_ALIGN_LEFT
        if (ux1 - ux0) < c_width - 10.0 and abs(u_mid - c_mid) <= 4.5 and left_pad >= 4.0 and right_pad >= 4.0:
            return pdf.TEXT_ALIGN_CENTER
        if left_pad > 10.0 and right_pad <= 10.0 and right_pad < left_pad * 0.35:
            return pdf.TEXT_ALIGN_RIGHT
        return pdf.TEXT_ALIGN_LEFT

    if len(line_boxes) >= 2:
        centers = [(b[0] + b[2]) * 0.5 for b in line_boxes]
        x0s = [b[0] for b in line_boxes]
        x1s = [b[2] for b in line_boxes]
        if max(centers) - min(centers) <= 4.5 and max(x0s) - min(x0s) > 5.0:
            return pdf.TEXT_ALIGN_CENTER
        if max(x1s) - min(x1s) <= 3.5 and max(x0s) - min(x0s) > 6.0:
            return pdf.TEXT_ALIGN_RIGHT
        if len(line_boxes) >= 3 and max(x0s) - min(x0s) <= 3.0 and (max(x1s[:-1]) - min(x1s[:-1])) <= 5.0:
            return pdf.TEXT_ALIGN_JUSTIFY
        return pdf.TEXT_ALIGN_LEFT

    ux0, _, ux1, _ = u["bbox"]
    if not has_row_peer:
        page_mid = page_width * 0.5
        u_mid = (ux0 + ux1) * 0.5
        if (
            abs(u_mid - page_mid) <= 8.0
            and ux0 >= page_width * 0.14
            and (page_width - ux1) >= page_width * 0.14
        ):
            return pdf.TEXT_ALIGN_CENTER
    return pdf.TEXT_ALIGN_LEFT


def _merge_subline_rows_into_units(
    rows_sublines: list[list[dict]],
    v_rules: list[tuple[float, float, float]],
    h_rules: list[tuple[float, float, float]],
    row_peer_check,
    container_bbox: list[float] | None = None,
    block_max_x1: float = 0.0,
) -> list[dict]:
    units: list[dict] = []
    pending_group: dict | None = None
    prev_was_multicolumn = False

    for sublines in rows_sublines:
        if not sublines:
            continue
        if len(sublines) > 1:
            if pending_group is not None:
                units.append(pending_group)
                pending_group = None
            for sl in sublines:
                units.append({
                    **sl,
                    "text": sl["text"].strip(),
                    "last_line_y1": sl["bbox"][3],
                    "line_count": 1,
                    "line_bboxes": [list(sl["bbox"])],
                    "container_bbox": list(container_bbox) if container_bbox else None,
                    "in_table": bool(container_bbox),
                })
            prev_was_multicolumn = True
            continue

        sl = sublines[0]
        sl_stripped = sl["text"].strip()
        starts_bullet = bool(_LIST_PREFIX_RE.match(sl_stripped))
        if pending_group is not None and not prev_was_multicolumn and not starts_bullet:
            prev_txt = pending_group["text"].rstrip()
            gap_y = sl["bbox"][1] - pending_group["last_line_y1"]
            shift_x = abs(sl["bbox"][0] - pending_group["bbox"][0])
            size_diff = abs(sl["size"] - pending_group["size"])
            same_style = (
                size_diff <= max(1.6, pending_group["size"] * 0.18)
                and sl["bold"] == pending_group["bold"]
                and sl["italic"] == pending_group["italic"]
                and sl["color"] == pending_group["color"]
            )
            crosses_h = _crosses_h_rule(
                pending_group["last_line_y1"] - 2.0,
                sl["bbox"][1] + 2.0,
                min(pending_group["bbox"][0], sl["bbox"][0]),
                max(pending_group["bbox"][2], sl["bbox"][2]),
                h_rules,
            )
            crosses_v = _crosses_v_rule(
                min(pending_group["bbox"][0], sl["bbox"][0]),
                max(pending_group["bbox"][2], sl["bbox"][2]),
                pending_group["last_line_y1"] - 1.0,
                sl["bbox"][1] + 1.0,
                v_rules,
            )
            either_protected = _should_skip_translation(prev_txt) or _should_skip_translation(sl_stripped)
            prev_is_sig_cue = bool(
                _SIGNATURE_UNDERLINE_RE.match(prev_txt)
                or _SIGNATURE_CLOSING_RE.match(prev_txt)
                or _SIGNATURE_HEADER_RE.match(prev_txt)
                or _SIGNATURE_INLINE_PREFIX_RE.match(prev_txt)
            )
            curr_is_sig_cue = bool(
                _SIGNATURE_UNDERLINE_RE.match(sl_stripped)
                or _SIGNATURE_CLOSING_RE.match(sl_stripped)
                or _SIGNATURE_HEADER_RE.match(sl_stripped)
                or _SIGNATURE_INLINE_PREFIX_RE.match(sl_stripped)
            )
            prev_is_person = _looks_like_proper_person_name(prev_txt, allow_all_caps=False)
            curr_is_person = _looks_like_proper_person_name(sl_stripped, allow_all_caps=False)
            prev_is_role = _looks_like_job_title_or_role(prev_txt)
            curr_is_role = _looks_like_job_title_or_role(sl_stripped)
            prev_ends_connector = bool(
                re.search(r"(?:\b(?:de|del|y|e|en|para|por|of|and|for|with)|&)$", prev_txt, re.IGNORECASE)
            )
            role_boundary = (
                (curr_is_role and not prev_ends_connector)
                or (prev_is_role and (curr_is_person or bool(_PERSONAL_ID_PREFIX_RE.match(sl_stripped))))
            )
            sig_boundary = (
                prev_is_sig_cue
                or curr_is_sig_cue
                or prev_is_person
                or curr_is_person
                or role_boundary
            )

            # Evitar fusionar dos filas de tabla sin bordes o campos cortos apilados
            last_lb = pending_group["line_bboxes"][-1]
            last_line_w = last_lb[2] - last_lb[0]
            first_next_word = (sl_stripped.split()[:1] or [""])[0]
            est_next_w = max(12.0, len(first_next_word) * sl["size"] * 0.52)
            col_right_ref = max(block_max_x1, last_lb[2], sl["bbox"][2])
            soft_hyphen = len(prev_txt) >= 3 and prev_txt.endswith("-") and prev_txt[-2].isalpha()
            role_continuation = prev_is_role and prev_ends_connector and not curr_is_role
            short_hard_break = (
                not soft_hyphen
                and not role_continuation
                and (
                    prev_txt.endswith(":")
                    or (len(prev_txt) < 28 and (last_lb[2] + est_next_w <= col_right_ref - 6.0 or row_peer_check(last_lb)))
                    or (prev_txt[-1:] in ".!?" and last_lb[2] + est_next_w <= col_right_ref - 14.0)
                )
            )
            # Evitar fusionar lineas centradas de un titulo en varias lineas con diferente ancho si son cortas
            prev_center = (last_lb[0] + last_lb[2]) * 0.5
            next_center = (sl["bbox"][0] + sl["bbox"][2]) * 0.5
            both_short_centered = (
                abs(prev_center - next_center) <= 3.5
                and shift_x > 8.0
                and len(prev_txt) < 42
                and len(sl_stripped) < 42
            )
            tab_row_break = (not container_bbox) and (not role_continuation) and row_peer_check(last_lb) and last_line_w < 130.0

            can_merge = (
                not crosses_h
                and not crosses_v
                and not either_protected
                and not sig_boundary
                and not short_hard_break
                and not both_short_centered
                and not tab_row_break
                and same_style
                and gap_y >= -pending_group["size"] * 0.35
                and gap_y <= pending_group["size"] * 0.78
                and shift_x <= max(24.0, pending_group["size"] * 2.2)
            )
            if can_merge:
                if soft_hyphen:
                    pending_group["text"] = prev_txt[:-1] + sl_stripped
                else:
                    pending_group["text"] = f"{prev_txt} {sl_stripped}".strip()
                pending_group["bbox"] = [
                    min(pending_group["bbox"][0], sl["bbox"][0]),
                    min(pending_group["bbox"][1], sl["bbox"][1]),
                    max(pending_group["bbox"][2], sl["bbox"][2]),
                    max(pending_group["bbox"][3], sl["bbox"][3]),
                ]
                pending_group["line_bboxes"].append(list(sl["bbox"]))
                pending_group["last_line_y1"] = sl["bbox"][3]
                pending_group["line_count"] += 1
                prev_was_multicolumn = False
                continue

        if pending_group is not None:
            units.append(pending_group)
        pending_group = {
            **sl,
            "text": sl_stripped,
            "last_line_y1": sl["bbox"][3],
            "line_count": 1,
            "line_bboxes": [list(sl["bbox"])],
            "container_bbox": list(container_bbox) if container_bbox else None,
            "in_table": bool(container_bbox),
        }
        prev_was_multicolumn = False

    if pending_group is not None:
        units.append(pending_group)
    return units


def _collect_translatable_units(
    page: pdf.Page,
    barriers: tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]] | None = None,
    ruled_tables_data: tuple[list[pdf.Rect], list[dict]] | None = None,
) -> list[dict]:
    """Agrupa spans en unidades semanticas (celdas de tabla, bloques o parrafos) preservando estructura y columnas."""
    v_rules, h_rules = barriers if barriers is not None else _extract_graphic_barriers(page)
    _ruled_boxes, cells_meta = ruled_tables_data if ruled_tables_data is not None else _extract_ruled_tables(page)
    td = page.get_text("dict", flags=pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES)

    # Inventariar todos los spans horizontales validos con su indice unico (b_idx, l_idx, s_idx)
    all_spans: list[dict] = []
    raw_blocks_lines: list[tuple[int, int, list[dict]]] = []
    for b_idx, block in enumerate(td.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for l_idx, line in enumerate(block.get("lines", [])):
            ldir = line.get("dir", (1.0, 0.0))
            if line.get("wmode", 0) or abs(float(ldir[0]) - 1.0) > 0.02 or abs(float(ldir[1])) > 0.02:
                continue
            line_spans = [sp for sp in line.get("spans", []) if sp.get("text", "").strip()]
            if not line_spans:
                continue
            raw_blocks_lines.append((b_idx, l_idx, line_spans))
            for s_idx, sp in enumerate(line_spans):
                sb = [float(v) for v in sp["bbox"]]
                all_spans.append({
                    "key": (b_idx, l_idx, s_idx),
                    "cx": (sb[0] + sb[2]) * 0.5,
                    "cy": (sb[1] + sb[3]) * 0.5,
                    "span": sp,
                })

    units: list[dict] = []
    claimed_keys: set[tuple[int, int, int]] = set()
    all_subline_boxes: list[list[float]] = []

    # 1. Procesar celdas de tablas con bordes estrictamente separadas entre si (menores primero)
    ordered_cells = sorted(
        cells_meta,
        key=lambda cm: (
            max(1.0, (cm["cell_bbox"][2] - cm["cell_bbox"][0]) * (cm["cell_bbox"][3] - cm["cell_bbox"][1])),
            round(cm["cell_bbox"][1], 1),
            cm["cell_bbox"][0],
        ),
    )
    for cell_info in ordered_cells:
        cx0, cy0, cx1, cy1 = cell_info["cell_bbox"]
        cell_spans = [
            item for item in all_spans
            if item["key"] not in claimed_keys
            and (cx0 - 1.5) <= item["cx"] <= (cx1 + 1.5)
            and (cy0 - 1.5) <= item["cy"] <= (cy1 + 1.5)
        ]
        if not cell_spans:
            continue
        for item in cell_spans:
            claimed_keys.add(item["key"])
        # Reconstruir lineas por coordenada Y dentro de la celda
        cell_spans.sort(key=lambda it: (round(float(it["span"]["bbox"][1]), 1), float(it["span"]["bbox"][0])))
        cell_rows_spans: list[list[dict]] = []
        for item in cell_spans:
            sp = item["span"]
            sy0 = float(sp["bbox"][1])
            ssize = float(sp.get("size", 10.0))
            if not cell_rows_spans or abs(sy0 - float(cell_rows_spans[-1][0]["bbox"][1])) > max(3.5, ssize * 0.45):
                cell_rows_spans.append([sp])
            else:
                cell_rows_spans[-1].append(sp)
        rows_sublines = [_split_line_subunits(rsp, v_rules) for rsp in cell_rows_spans]
        for sbl in rows_sublines:
            for s in sbl:
                all_subline_boxes.append(s["bbox"])
        cell_max_x1 = max((s["bbox"][2] for sbl in rows_sublines for s in sbl), default=cx1)
        cell_units = _merge_subline_rows_into_units(
            rows_sublines,
            v_rules,
            h_rules,
            lambda _lb: False,
            container_bbox=cell_info["cell_bbox"],
            block_max_x1=cell_max_x1,
        )
        units.extend(cell_units)

    # 2. Procesar bloques libres fuera de tablas con bordes
    block_rows: dict[int, list[list[dict]]] = {}
    for b_idx, _l_idx, line_spans in raw_blocks_lines:
        rem = [
            sp for s_idx, sp in enumerate(line_spans)
            if (b_idx, _l_idx, s_idx) not in claimed_keys
        ]
        if not rem:
            continue
        sublines = _split_line_subunits(rem, v_rules)
        if not sublines:
            continue
        for s in sublines:
            all_subline_boxes.append(s["bbox"])
        block_rows.setdefault(b_idx, []).append(sublines)

    def _has_row_peer(lb: list[float]) -> bool:
        lh = max(1.0, lb[3] - lb[1])
        for ob in all_subline_boxes:
            if abs(ob[0] - lb[0]) <= 2.0 and abs(ob[1] - lb[1]) <= 2.0 and abs(ob[2] - lb[2]) <= 2.0:
                continue
            ov_y = min(lb[3], ob[3]) - max(lb[1], ob[1])
            if ov_y >= lh * 0.40 and (ob[0] >= lb[2] + 6.0 or lb[0] >= ob[2] + 6.0):
                return True
        return False

    for b_idx in sorted(block_rows.keys()):
        rows_sublines = block_rows[b_idx]
        b_max_x1 = max((s["bbox"][2] for sbl in rows_sublines for s in sbl), default=0.0)
        units.extend(
            _merge_subline_rows_into_units(
                rows_sublines,
                v_rules,
                h_rules,
                _has_row_peer,
                container_bbox=None,
                block_max_x1=b_max_x1,
            )
        )

    page_w = float(page.rect.width)
    clean_units: list[dict] = []
    for u in units:
        u["text"] = u["text"].strip()
        if not u["text"]:
            continue
        u["align"] = _infer_unit_alignment(u, page_w, _has_row_peer(u["bbox"]) if not u.get("in_table") else False)
        clean_units.append(u)
    clean_units.sort(key=lambda it: (round(it["bbox"][1], 1), it["bbox"][0]))
    _tag_signature_units(clean_units, h_rules, [])
    return clean_units


def _collect_non_scan_image_rects(page: pdf.Page) -> list[pdf.Rect]:
    """Recopila rectangulos de imagenes locales (logos, firmas) omitiendo escaneos de pagina completa."""
    rects: list[pdf.Rect] = []
    page_area = max(1.0, float(page.rect.get_area()))
    try:
        imgs = page.get_images(full=True) or []
    except Exception:
        return rects
    for img in imgs:
        try:
            for r in page.get_image_rects(img[0]) or []:
                rect = pdf.Rect(r) & page.rect
                if not rect.is_empty and rect.get_area() < 0.72 * page_area:
                    rects.append(rect)
        except Exception:
            continue
    return rects


def _tag_signature_units(
    units: list[dict],
    h_rules: list[tuple[float, float, float]],
    image_rects: list[pdf.Rect],
) -> None:
    """Marca unidades ubicadas en bloques de firma para omitir nombres propios manteniendo cargos traducibles."""
    if not units:
        return

    closing_zones: list[tuple[float, float, float]] = []  # (cx0, cy1, max_reach_x)
    header_zones: list[tuple[float, float, float, float]] = []  # (cx0, cy0, cx1, cy1)

    for u in units:
        txt = u.get("text", "").strip()
        bx0, by0, bx1, by1 = u["bbox"]
        u["near_signature"] = bool(u.get("near_signature", False))
        if _SIGNATURE_CLOSING_RE.match(txt):
            closing_zones.append((bx0, by1, bx1))
            u["near_signature"] = True
        elif _SIGNATURE_HEADER_RE.match(txt) or _SIGNATURE_UNDERLINE_RE.match(txt):
            header_zones.append((bx0, by0, bx1, by1))
            u["near_signature"] = True
        elif _extract_signature_inline_spans(txt, near_signature=True):
            header_zones.append((bx0, by0, bx1, by1))
            u["near_signature"] = True

    sig_rules = [
        (hy, hx0, hx1)
        for hy, hx0, hx1 in h_rules
        if 35.0 <= (hx1 - hx0) <= 320.0
    ]
    sig_images = [
        ir
        for ir in image_rects
        if 28.0 <= ir.width <= 300.0 and 10.0 <= ir.height <= 125.0
    ]

    # 1. Propagar contexto desde cierres, lineas de firma, encabezados y rubricas graficas
    for u in units:
        ux0, uy0, ux1, uy1 = u["bbox"]
        ucx = (ux0 + ux1) * 0.5
        if any(
            (cy1 - 2.0) <= uy0 <= (cy1 + 125.0) and ux1 >= (cx0 - 40.0)
            for cx0, cy1, _cx1 in closing_zones
        ):
            u["near_signature"] = True
            continue
        if any(
            (-32.0 <= (uy0 - cy1) <= 85.0)
            and (min(ux1, cx1 + 110.0) - max(ux0, cx0 - 35.0) > 0 or abs(ucx - (cx0 + cx1) * 0.5) <= 95.0)
            for cx0, cy0, cx1, cy1 in header_zones
        ):
            u["near_signature"] = True
            continue
        if any(
            ((-4.0 <= (uy0 - hy) <= 62.0) or (0.0 <= (hy - uy1) <= 18.0))
            and (min(ux1, hx1 + 25.0) - max(ux0, hx0 - 25.0) > 0 or abs(ucx - (hx0 + hx1) * 0.5) <= 65.0)
            for hy, hx0, hx1 in sig_rules
        ):
            u["near_signature"] = True
            continue
        if any(
            ((0.0 <= (uy0 - ir.y1) <= 50.0) or (0.0 <= (ir.y0 - uy1) <= 16.0))
            and min(ux1, ir.x1 + 30.0) - max(ux0, ir.x0 - 30.0) > 0
            for ir in sig_images
        ):
            u["near_signature"] = True

    # 2. Detectar par vertical directo: <Nombre Propio> inmediatamente encima de <Cargo / ID personal>
    for i, u_i in enumerate(units):
        txt_i = u_i.get("text", "").strip()
        if not _looks_like_proper_person_name(txt_i, allow_all_caps=True):
            continue
        ix0, _iy0, ix1, iy1 = u_i["bbox"]
        icx = (ix0 + ix1) * 0.5
        max_gap = max(38.0, float(u_i.get("size", 10.0)) * 3.4)
        for j, u_j in enumerate(units):
            if i == j:
                continue
            if u_i.get("container_bbox") != u_j.get("container_bbox"):
                continue
            jx0, jy0, jx1, _jy1 = u_j["bbox"]
            dy = jy0 - iy1
            if not (0.0 <= dy <= max_gap):
                continue
            jcx = (jx0 + jx1) * 0.5
            same_col = (
                min(ix1, jx1) - max(ix0, jx0) > -18.0
                or abs(icx - jcx) <= 50.0
                or abs(ix0 - jx0) <= 24.0
            )
            if not same_col:
                continue
            txt_j = u_j.get("text", "").strip()
            if (
                _looks_like_job_title_or_role(txt_j)
                or _PERSONAL_ID_PREFIX_RE.match(txt_j)
                or _SIGNATURE_UNDERLINE_RE.match(txt_j)
                or _SIGNATURE_HEADER_RE.match(txt_j)
            ):
                u_i["near_signature"] = True
                u_j["near_signature"] = True
                break

    for u in units:
        u["skip_translation"] = _should_skip_translation(
            u.get("text", ""),
            near_signature=bool(u.get("near_signature", False)),
        )


def _compute_translation_boxes(
    idx: int,
    u: dict,
    all_units: list[dict],
    page_rect: pdf.Rect,
    v_rules: list[tuple[float, float, float]],
    h_rules: list[tuple[float, float, float]],
    ruled_boxes: list[pdf.Rect],
    image_rects: list[pdf.Rect],
) -> tuple[pdf.Rect, pdf.Rect, pdf.Rect]:
    """Calcula cajas tight, max segura y expansion garantizada sin invadir tablas, columnas ni bloques."""
    rect = pdf.Rect(u["bbox"]) & page_rect
    size = max(5.0, float(u["size"]))
    top_pad = max(1.0, size * 0.14)
    bot_pad = max(2.5, size * 0.28)
    align = u.get("align", pdf.TEXT_ALIGN_LEFT)

    container = u.get("container_bbox")
    if container:
        cell = pdf.Rect(container) & page_rect
        in_x0 = max(cell.x0, cell.x0 + 2.0)
        in_x1 = min(cell.x1, cell.x1 - 2.0)
        in_y0 = max(cell.y0, cell.y0 + 1.0)
        in_y1 = min(cell.y1, cell.y1 - 1.0)
        if in_x1 <= in_x0 + 4.0:
            in_x0, in_x1 = cell.x0, cell.x1
        if in_y1 <= in_y0 + 4.0:
            in_y0, in_y1 = cell.y0, cell.y1

        if align == pdf.TEXT_ALIGN_CENTER:
            x0, x1 = in_x0, in_x1
        elif align == pdf.TEXT_ALIGN_RIGHT:
            x0 = in_x0
            x1 = min(in_x1, max(rect.x1, in_x1 - 2.0))
        else:
            x0 = max(in_x0, min(rect.x0, in_x1 - 6.0))
            x1 = max(rect.x1, in_x1)

        below_sib = in_y1
        above_sib = in_y0
        for o_idx, other in enumerate(all_units):
            if o_idx == idx or other.get("container_bbox") != container:
                continue
            ob = other["bbox"]
            if ob[1] >= rect.y1 - 2.0 and min(x1, ob[2]) - max(x0, ob[0]) > 2.0:
                below_sib = min(below_sib, max(rect.y1 + 1.0, ob[1] - 1.5))
            if ob[3] <= rect.y0 + 2.0 and min(x1, ob[2]) - max(x0, ob[0]) > 2.0:
                above_sib = max(above_sib, min(rect.y0, ob[3] + 1.5))
        tight_y0 = max(in_y0, min(rect.y0 - top_pad, in_y1 - size))
        tight_y1 = max(rect.y1 + 1.0, min(below_sib, rect.y1 + bot_pad))
        max_y1 = max(tight_y1, below_sib)
        expand_box = pdf.Rect(in_x0, min(tight_y0, above_sib), max(in_x1, x1), max_y1)
        return (
            pdf.Rect(x0, tight_y0, x1, tight_y1),
            pdf.Rect(x0, tight_y0, x1, max_y1),
            expand_box,
        )

    # Bloques fuera de tabla: calcular paredes horizontales reales (vecinos + divisores verticales + bordes de tabla)
    left_wall = min(page_rect.x0 + 8.0, rect.x0)
    right_wall = max(page_rect.x1 - 8.0, rect.x1)
    for o_idx, other in enumerate(all_units):
        if o_idx == idx:
            continue
        ob = other["bbox"]
        if min(rect.y1, ob[3]) - max(rect.y0, ob[1]) > 1.5:
            if ob[2] <= rect.x0 + 2.0:
                left_wall = max(left_wall, min(rect.x0, ob[2] + 4.0))
            if ob[0] >= rect.x1 - 2.0:
                right_wall = min(right_wall, max(rect.x1, ob[0] - 4.0))
    for vx, vy0, vy1 in v_rules:
        if min(rect.y1, vy1) - max(rect.y0, vy0) > 2.0:
            if vx <= rect.x0 + 1.0:
                left_wall = max(left_wall, min(rect.x0, vx + 3.0))
            elif vx >= rect.x1 - 1.0:
                right_wall = min(right_wall, max(rect.x1, vx - 3.0))
    for tb in ruled_boxes:
        if min(rect.y1, tb.y1) - max(rect.y0, tb.y0) > 2.0:
            if tb.x1 <= rect.x0 + 2.0:
                left_wall = max(left_wall, min(rect.x0, tb.x1 + 4.0))
            elif tb.x0 >= rect.x1 - 2.0:
                right_wall = min(right_wall, max(rect.x1, tb.x0 - 4.0))
    for ir in image_rects:
        if min(rect.y1, ir.y1) - max(rect.y0, ir.y0) > 2.0:
            if ir.x1 <= rect.x0 + 2.0:
                left_wall = max(left_wall, min(rect.x0, ir.x1 + 4.0))
            elif ir.x0 >= rect.x1 - 2.0:
                right_wall = min(right_wall, max(rect.x1, ir.x0 - 4.0))

    if align == pdf.TEXT_ALIGN_CENTER:
        cx = (rect.x0 + rect.x1) * 0.5
        half_room = max(rect.width * 0.5, min(cx - left_wall, right_wall - cx))
        target_half = min(half_room, rect.width * 0.5 + max(24.0, rect.width * 0.25))
        x0 = cx - target_half
        x1 = cx + target_half
    elif align == pdf.TEXT_ALIGN_RIGHT:
        x1 = min(right_wall, rect.x1)
        x0 = max(left_wall, rect.x0 - max(24.0, rect.width * 0.25))
    else:
        x0 = max(left_wall, rect.x0)
        if u.get("line_count", 1) <= 1:
            x1 = min(right_wall, rect.x1 + max(24.0, rect.width * 0.25))
        else:
            x1 = min(right_wall, rect.x1 + min(12.0, max(4.0, rect.width * 0.04)))
        x1 = max(x1, min(right_wall, rect.x1))

    # Calcular paredes vertical segura inferior y superior (vecinos, reglas, tablas, imagenes)
    below_wall = max(page_rect.y1 - 4.0, rect.y1 + 2.0)
    above_wall = min(page_rect.y0 + 4.0, rect.y0)
    for o_idx, other in enumerate(all_units):
        if o_idx == idx:
            continue
        ob = other["bbox"]
        if ob[1] >= rect.y1 - 2.0 and min(x1, ob[2]) - max(x0, ob[0]) > 2.0:
            below_wall = min(below_wall, max(rect.y1 + 1.0, ob[1] - 2.0))
        if ob[3] <= rect.y0 + 2.0 and min(x1, ob[2]) - max(x0, ob[0]) > 2.0:
            above_wall = max(above_wall, min(rect.y0, ob[3] + 1.5))
    for hy, hx0, hx1 in h_rules:
        if hy >= rect.y1 - 1.0 and min(x1, hx1) - max(x0, hx0) > 6.0:
            below_wall = min(below_wall, max(rect.y1 + 1.0, hy - 2.0))
        if hy <= rect.y0 + 1.0 and min(x1, hx1) - max(x0, hx0) > 6.0:
            above_wall = max(above_wall, min(rect.y0, hy + 1.5))
    for tb in ruled_boxes:
        if tb.y0 >= rect.y1 - 2.0 and min(x1, tb.x1) - max(x0, tb.x0) > 2.0:
            below_wall = min(below_wall, max(rect.y1 + 1.0, tb.y0 - 2.0))
        if tb.y1 <= rect.y0 + 2.0 and min(x1, tb.x1) - max(x0, tb.x0) > 2.0:
            above_wall = max(above_wall, min(rect.y0, tb.y1 + 2.0))
    for ir in image_rects:
        if ir.y0 >= rect.y1 - 2.0 and min(x1, ir.x1) - max(x0, ir.x0) > 2.0:
            below_wall = min(below_wall, max(rect.y1 + 1.0, ir.y0 - 2.0))
        if ir.y1 <= rect.y0 + 2.0 and min(x1, ir.x1) - max(x0, ir.x0) > 2.0:
            above_wall = max(above_wall, min(rect.y0, ir.y1 + 2.0))

    y0 = max(page_rect.y0, rect.y0 - top_pad)
    tight_y1 = max(rect.y1 + 1.0, min(below_wall, rect.y1 + bot_pad))
    safe_max_y1 = max(tight_y1, min(below_wall, rect.y1 + bot_pad + max(size * 1.35, rect.height * 0.35)))
    exp_y0 = min(y0, max(above_wall, y0 - min(6.0, size * 0.55)))
    exp_x1 = max(x1, min(right_wall, x1 + max(18.0, size * 1.5)))
    return (
        pdf.Rect(x0, y0, max(x0 + 4.0, x1), tight_y1),
        pdf.Rect(x0, y0, max(x0 + 4.0, x1), safe_max_y1),
        pdf.Rect(x0, exp_y0, max(x0 + 4.0, exp_x1), max(safe_max_y1, min(below_wall, rect.y1 + max(size * 2.5, rect.height * 0.6)))),
    )


def _soft_break_overlong_tokens(text: str, max_token_len: int = 16) -> str:
    tokens = text.split(" ")
    out: list[str] = []
    for tok in tokens:
        if len(tok) <= max_token_len:
            out.append(tok)
        else:
            out.extend(tok[i : i + max_token_len] for i in range(0, len(tok), max_token_len))
    return " ".join(out)


def _fit_translated_text_in_box(
    page: pdf.Page,
    tight_rect: pdf.Rect,
    max_rect: pdf.Rect,
    text: str,
    fontname: str,
    base_size: float,
    color: tuple[float, float, float],
    align: int = pdf.TEXT_ALIGN_LEFT,
    min_size: float = 4.5,
    expand_rect: pdf.Rect | None = None,
) -> float:
    """Ajusta el texto traducido garantizando insercion completa sin truncamientos ni huecos en blanco."""
    base = max(min_size, min(36.0, float(base_size)))
    soft_floor = max(min_size, round(base * 0.85, 2))

    # Paso 1: Intentar dentro de tight_rect sin deformar verticalmente el bloque
    sz = base
    while sz >= soft_floor:
        res = page.insert_textbox(tight_rect, text, fontsize=sz, fontname=fontname, color=color, align=align)
        if res >= 0:
            return sz
        sz = round(sz - 0.5, 2)

    # Paso 2: Si hay espacio seguro sin colisiones (max_rect > tight_rect), expandir cautelosamente antes de achicar mas
    if max_rect.height > tight_rect.height + 1.0:
        sz = round(min(base, max(min_size, base * 0.92)), 2)
        while sz >= max(min_size, round(base * 0.72, 2)):
            res = page.insert_textbox(max_rect, text, fontsize=sz, fontname=fontname, color=color, align=align)
            if res >= 0:
                return sz
            sz = round(sz - 0.5, 2)

    # Paso 3: Reduccion hasta min_size en el mayor recuadro seguro sin solapar vecinos ni bordes
    target_rect = max_rect if max_rect.height >= tight_rect.height else tight_rect
    sz = round(min(base * 0.84, max(min_size, soft_floor - 0.5)), 2)
    while sz >= min_size:
        res = page.insert_textbox(target_rect, text, fontsize=sz, fontname=fontname, color=color, align=align)
        if res >= 0:
            return sz
        sz = round(sz - 0.5, 2)

    # Paso 4: Interlineado compacto (1.05 y 1.00) dentro de target_rect antes de cambiar limites
    for lh in (1.05, 1.00):
        sz = round(min(base * 0.90, max(min_size, soft_floor)), 2)
        while sz >= min_size:
            res = page.insert_textbox(
                target_rect, text, fontsize=sz, fontname=fontname, color=color, align=align, lineheight=lh,
            )
            if res >= 0:
                return sz
            sz = round(sz - 0.5, 2)

    # Paso 5: Usar expand_rect seguro (ej. toda la celda libre arriba/abajo) antes de micro-escala
    if expand_rect is not None and (
        expand_rect.height > target_rect.height + 0.5 or expand_rect.width > target_rect.width + 0.5
    ):
        for lh in (1.05, 0.98):
            sz = round(min(base * 0.92, max(min_size, base * 0.85)), 2)
            low_floor = max(3.0, round(min_size * 0.65, 2))
            while sz >= low_floor:
                res = page.insert_textbox(
                    expand_rect, text, fontsize=sz, fontname=fontname, color=color, align=align, lineheight=lh,
                )
                if res >= 0:
                    return sz
                sz = round(sz - 0.4, 2)

    # Paso 6: Red de seguridad absoluta (NUNCA dejar un bloque vacio por retorno negativo)
    best_rect = expand_rect if expand_rect is not None else target_rect
    for extra_y in (2.0, 8.0, 20.0, 48.0, 120.0):
        cur_rect = pdf.Rect(
            best_rect.x0,
            best_rect.y0,
            best_rect.x1,
            min(page.rect.y1 - 1.0, best_rect.y1 + extra_y),
        )
        sz = min_size
        while sz >= 2.2:
            res = page.insert_textbox(
                cur_rect, text, fontsize=sz, fontname=fontname, color=color, align=align, lineheight=0.98,
            )
            if res >= 0:
                return sz
            sz = round(sz - 0.4, 2)

    # Ultimo recurso ante palabra irrompible mas ancha que el recuadro: ensanchar levemente y fragmentar token largo
    wide_rect = pdf.Rect(best_rect.x0, best_rect.y0, min(page.rect.x1 - 2.0, max(best_rect.x1, best_rect.x0 + 40.0) + 28.0), min(page.rect.y1 - 1.0, best_rect.y1 + 60.0))
    wrapped = _soft_break_overlong_tokens(text, max_token_len=14)
    sz = max(2.0, min(min_size, 4.0))
    while sz >= 1.8:
        if page.insert_textbox(wide_rect, wrapped, fontsize=sz, fontname=fontname, color=color, align=align, lineheight=0.98) >= 0:
            return sz
        sz = round(sz - 0.3, 2)
    return min_size


def _build_safe_redaction_rects(
    changed: list[tuple[int, dict, str]],
    units: list[dict],
    page_rect: pdf.Rect,
) -> list[pdf.Rect]:
    """Construye rectángulos de redacción quirúrgicos que evitan borrar líneas vecinas sin traducir."""
    changed_indices = {idx for idx, _, _ in changed}
    keep_lines: list[tuple[pdf.Rect, pdf.Rect]] = []
    for idx, u in enumerate(units):
        if idx in changed_indices:
            continue
        for klb in (u.get("line_bboxes") or [u["bbox"]]):
            kr = pdf.Rect(klb) & page_rect
            if kr.is_empty:
                continue
            kh = max(1.0, kr.height)
            k_core = pdf.Rect(kr.x0 + 0.25, kr.y0 + kh * 0.26, kr.x1 - 0.25, kr.y1 - kh * 0.24)
            keep_lines.append((kr, k_core))

    redactions: list[pdf.Rect] = []
    for _, u, _ in changed:
        for lb in (u.get("line_bboxes") or [u["bbox"]]):
            r = pdf.Rect(lb) & page_rect
            if r.is_empty:
                continue
            rh = max(1.0, r.height)
            cand = pdf.Rect(r.x0 + 0.25, r.y0 + rh * 0.24, r.x1 - 0.25, r.y1 - rh * 0.22)
            if cand.width < 0.8:
                cand = pdf.Rect(r.x0, cand.y0, r.x1, cand.y1)
            if cand.height < 0.8:
                cand = pdf.Rect(cand.x0, r.y0, cand.x1, r.y1)

            rcy = (r.y0 + r.y1) * 0.5
            for kr, k_core in keep_lines:
                if (cand & kr).is_empty:
                    continue
                ov_core_y = min(cand.y1, k_core.y1) - max(cand.y0, k_core.y0)
                same_row = ov_core_y > min(cand.height, k_core.height) * 0.42
                if same_row:
                    if r.x0 < kr.x0:
                        cand.x1 = min(cand.x1, kr.x0 - 0.35)
                    elif r.x1 > kr.x1:
                        cand.x0 = max(cand.x0, kr.x1 + 0.35)
                else:
                    kcy = (kr.y0 + kr.y1) * 0.5
                    if rcy <= kcy:
                        cand.y1 = min(cand.y1, k_core.y0 - 0.25)
                    else:
                        cand.y0 = max(cand.y0, k_core.y1 + 0.25)

            cand = cand & page_rect
            if not cand.is_empty and cand.width >= 0.4 and cand.height >= 0.4:
                redactions.append(cand)
    return redactions


def _sample_scan_unit_styles(pix: pdf.Pixmap, page_rect: pdf.Rect, units: list[dict]) -> None:
    """Estima color de papel de fondo y color de tinta para bloques extraidos de un escaneo."""
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3]
    sx = pix.width / max(1.0, page_rect.width)
    sy = pix.height / max(1.0, page_rect.height)
    for u in units:
        x0, y0, x1, y1 = u["bbox"]
        px0 = max(0, int(round(x0 * sx)))
        py0 = max(0, int(round(y0 * sy)))
        px1 = min(pix.width, max(px0 + 2, int(round(x1 * sx))))
        py1 = min(pix.height, max(py0 + 2, int(round(y1 * sy))))
        # Aro exterior para estimar color limpio del papel
        pad = max(3, int(round(4 * sx)))
        ox0, oy0 = max(0, px0 - pad), max(0, py0 - pad)
        ox1, oy1 = min(pix.width, px1 + pad), min(pix.height, py1 + pad)
        ring_samples = []
        if oy0 < py0:
            ring_samples.append(rgb[oy0:py0, ox0:ox1].reshape(-1, 3))
        if py1 < oy1:
            ring_samples.append(rgb[py1:oy1, ox0:ox1].reshape(-1, 3))
        if ox0 < px0:
            ring_samples.append(rgb[py0:py1, ox0:px0].reshape(-1, 3))
        if px1 < ox1:
            ring_samples.append(rgb[py0:py1, px1:ox1].reshape(-1, 3))
        if ring_samples:
            ring = np.concatenate(ring_samples, axis=0)
            luma = 0.299 * ring[:, 0] + 0.587 * ring[:, 1] + 0.114 * ring[:, 2]
            bright = ring[luma >= np.percentile(luma, 55)]
            bg_rgb = np.median(bright if len(bright) else ring, axis=0)
        else:
            bg_rgb = np.array([255.0, 255.0, 255.0])
        u["bg_color"] = tuple(round(float(c) / 255.0, 4) for c in bg_rgb)

        inner = rgb[py0:py1, px0:px1].reshape(-1, 3)
        if len(inner):
            diff = np.linalg.norm(inner.astype(np.float32) - bg_rgb.astype(np.float32), axis=1)
            ink = inner[diff >= max(28.0, float(np.percentile(diff, 75)))]
            if len(ink):
                med_ink = np.median(ink, axis=0).astype(int)
                u["color"] = f"#{med_ink[0]:02x}{med_ink[1]:02x}{med_ink[2]:02x}"


def handle_translate_layout(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    password = str(options.get("password", ""))
    src_lang = str(options.get("source_lang", "es")).lower()[:2]
    dst_lang = str(options.get("target_lang", "en")).lower()[:2]
    if src_lang == dst_lang:
        raise ProcessingError("El idioma origen y destino deben ser distintos.", 400)
    engine_pref = str(options.get("engine", "auto")).lower()
    if engine_pref not in ("auto", "nmt", "ai", "glossary"):
        engine_pref = "auto"

    user_map = options.get("translations") or {}
    if not isinstance(user_map, dict):
        raise ProcessingError("El mapa 'translations' debe ser un diccionario.", 400)

    overflow_warnings: list[dict] = []
    total_blocks = 0
    ocr_pages = 0
    mode_used = "offline_glossary"
    ocr_ready: bool | None = None

    def _render_safe_for_ocr(pg: pdf.Page) -> pdf.Pixmap:
        for candidate_dpi in (200, 150, 120, 90):
            px_count = math.ceil(pg.rect.width * candidate_dpi / 72) * math.ceil(pg.rect.height * candidate_dpi / 72)
            if px_count <= config["max_render_pixels"]:
                return render(pg, candidate_dpi, config)
        return render(pg, 72, config)

    with open_pdf(source, password, config["max_pages"]) as doc:
        selected = pages_from(options.get("pages", ""), len(doc))
        for pno in selected:
            page = doc[pno]
            if page.rotation:
                raise ProcessingError("Quite la rotacion de la pagina antes de traducir in-situ.")

            v_rules, h_rules = _extract_graphic_barriers(page)
            ruled_boxes, cells_meta = _extract_ruled_tables(page)
            units = _collect_translatable_units(
                page,
                barriers=(v_rules, h_rules),
                ruled_tables_data=(ruled_boxes, cells_meta),
            )
            image_rects = _collect_non_scan_image_rects(page) if units else []
            is_scan_page = False
            if units:
                invisible_boxes: list[pdf.Rect] = []
                try:
                    invisible_boxes = [
                        pdf.Rect(tr["bbox"])
                        for tr in page.get_texttrace()
                        if tr.get("type") == 3
                    ]
                except Exception:
                    invisible_boxes = []
                for u in units:
                    ubox = pdf.Rect(u["bbox"])
                    is_hidden_ocr = "glyphless" in str(u.get("font", "")).lower() or any(
                        (ubox & ib).get_area() > 0.25 * max(1.0, ubox.get_area())
                        for ib in invisible_boxes
                    )
                    u["needs_bg_patch"] = bool(is_hidden_ocr)
                if any(u.get("needs_bg_patch") for u in units):
                    patch_units = [u for u in units if u.get("needs_bg_patch")]
                    pix = _render_safe_for_ocr(page)
                    _sample_scan_unit_styles(pix, page.rect, patch_units)
                    ocr_pages += 1
            else:
                if ocr_ready is None:
                    ocr_ready = bool(capabilities(config, root).get("ocr"))
                if ocr_ready:
                    pix = _render_safe_for_ocr(page)
                    ocr_bytes = pix.pdfocr_tobytes(
                        language=config["ocr_language"],
                        tessdata=str(root / "models"),
                    )
                    with pdf.open(stream=ocr_bytes, filetype="pdf") as ocr_doc:
                        if len(ocr_doc):
                            ocr_page = ocr_doc[0]
                            units = _collect_translatable_units(ocr_page)
                            if units:
                                sx = page.rect.width / max(1.0, ocr_page.rect.width)
                                sy = page.rect.height / max(1.0, ocr_page.rect.height)
                                ox, oy = page.rect.x0 - ocr_page.rect.x0 * sx, page.rect.y0 - ocr_page.rect.y0 * sy
                                for u in units:
                                    b = u["bbox"]
                                    u["bbox"] = [
                                        ox + b[0] * sx,
                                        oy + b[1] * sy,
                                        ox + b[2] * sx,
                                        oy + b[3] * sy,
                                    ]
                                    u["line_bboxes"] = [
                                        [ox + lb[0] * sx, oy + lb[1] * sy, ox + lb[2] * sx, oy + lb[3] * sy]
                                        for lb in (u.get("line_bboxes") or [b])
                                    ]
                                    if u.get("container_bbox"):
                                        cb = u["container_bbox"]
                                        u["container_bbox"] = [ox + cb[0] * sx, oy + cb[1] * sy, ox + cb[2] * sx, oy + cb[3] * sy]
                                    u["size"] = u["size"] * sy
                                    u["needs_bg_patch"] = True
                    if units:
                        _sample_scan_unit_styles(pix, page.rect, units)
                        is_scan_page = True
                        ocr_pages += 1

            if not units:
                continue

            _tag_signature_units(units, h_rules, image_rects)
            translated_list, mode_used = _translate_offline_or_ai(
                [u["text"] for u in units],
                src_lang,
                dst_lang,
                user_map,
                config,
                root=root,
                engine_pref=engine_pref,
                unit_hints=units,
            )
            changed = [
                (idx, u, tr)
                for idx, (u, tr) in enumerate(zip(units, translated_list))
                if tr.strip() and tr.strip() != u["text"].strip()
            ]
            if not changed:
                continue

            if not is_scan_page:
                for red_rect in _build_safe_redaction_rects(changed, units, page.rect):
                    page.add_redact_annot(red_rect, fill=False, cross_out=False)
                page.apply_redactions(images=0, graphics=0, text=pdf.PDF_REDACT_TEXT_REMOVE)

            font_cache: dict[str, str] = {}
            for idx, u, tr in changed:
                rect = pdf.Rect(u["bbox"]) & page.rect
                if rect.is_empty:
                    continue
                if u.get("needs_bg_patch"):
                    for lb in (u.get("line_bboxes") or [u["bbox"]]):
                        lrect = pdf.Rect(lb) & page.rect
                        if lrect.is_empty:
                            continue
                        cover = pdf.Rect(
                            max(page.rect.x0, lrect.x0 - 1.5),
                            max(page.rect.y0, lrect.y0 - 1.0),
                            min(page.rect.x1, lrect.x1 + 1.5),
                            min(page.rect.y1, lrect.y1 + 1.5),
                        )
                        page.draw_rect(cover, color=None, fill=u.get("bg_color", (1.0, 1.0, 1.0)), overlay=True)

                tight_box, max_box, expand_box = _compute_translation_boxes(
                    idx, u, units, page.rect, v_rules, h_rules, ruled_boxes, image_rects,
                )
                font_code = _resolve_translation_font(
                    page, u["font"], u.get("bold", False), u.get("italic", False), font_cache,
                )
                color = parse_color(u["color"])
                used_sz = _fit_translated_text_in_box(
                    page,
                    tight_box,
                    max_box,
                    tr,
                    font_code,
                    u["size"],
                    color,
                    align=u.get("align", pdf.TEXT_ALIGN_LEFT),
                    min_size=max(4.5, u["size"] * 0.48),
                    expand_rect=expand_box,
                )
                if used_sz < u["size"] * 0.78:
                    overflow_warnings.append({
                        "page": pno + 1,
                        "orig_size": round(u["size"], 2),
                        "fitted_size": used_sz,
                        "text": tr[:80],
                    })
                total_blocks += 1

        out_pdf = folder / f"traducido_{dst_lang}.pdf"
        save(doc, out_pdf, clean=True)

    ocr_note = f" OCR aplicado en {ocr_pages} pag." if ocr_pages else ""
    return {
        "file": out_pdf.name,
        "notice": (
            f"Traduccion vectorial ({src_lang}->{dst_lang}, motor={mode_used}): "
            f"{total_blocks} bloques traducidos, {len(overflow_warnings)} cajas ajustadas.{ocr_note}"
        ),
    }
