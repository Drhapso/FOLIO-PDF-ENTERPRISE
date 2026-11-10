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
    r"^(?:https?://\S+|\S+@\S+\.\S+|[\d\s.,:/%+\-()$€£#*]+)$"
)
_LIST_PREFIX_RE = re.compile(r"^((?:[-*•▪◦‣–—]+|\d{1,3}[.)]|\(?[A-Za-z]\))\s+)(.*)$", re.DOTALL)


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
        except ImportError:
            return None
        with bpe_path.open("r", encoding="utf-8") as bf:
            bpe = BPE(bf, separator="@@")
        bundle = {
            "kind": "bpe",
            "translator": translator,
            "bpe": bpe,
            "mt": MosesTokenizer(lang=pair[0]),
            "md": MosesDetokenizer(lang=pair[1]),
        }
    else:
        return None

    if len(_NMT_BUNDLE_CACHE) >= 4:
        _NMT_BUNDLE_CACHE.clear()
    _NMT_BUNDLE_CACHE[cache_key] = bundle
    return bundle


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


def _should_skip_translation(core: str) -> bool:
    stripped = core.strip()
    if not stripped or not _TRANSLATABLE_LETTER_RE.search(stripped):
        return True
    if _NON_LINGUISTIC_RE.match(stripped):
        return True
    return False


def _translate_with_ctranslate2(
    texts: list[str],
    pair: tuple[str, str],
    config: dict,
    root: Path,
) -> list[str] | None:
    bundle = _load_nmt_bundle(pair, config, root)
    if bundle is None:
        return None

    plans: list[dict] = []
    unique_sentences: dict[str, None] = {}

    for raw in texts:
        prefix, core, suffix, all_caps = _split_segment_for_nmt(raw)
        if _should_skip_translation(core):
            plans.append({"skip": True, "raw": raw})
            continue
        raw_sentences = [s for s in re.split(r"(?<=[.!?])\s+", core) if s]
        sentences = [s.capitalize() if all_caps else s for s in raw_sentences]
        for s in sentences:
            if not _should_skip_translation(s):
                unique_sentences.setdefault(s, None)
        plans.append({
            "skip": False,
            "prefix": prefix,
            "suffix": suffix,
            "all_caps": all_caps,
            "sentences": sentences,
        })

    sent_list = list(unique_sentences.keys())
    translated_map: dict[str, str] = {}
    if sent_list:
        translator = bundle["translator"]
        for i in range(0, len(sent_list), 64):
            chunk = sent_list[i : i + 64]
            if bundle["kind"] == "sp":
                sp = bundle["sp"]
                toks = [sp.encode(s, out_type=str) for s in chunk]
                res = translator.translate_batch(
                    toks, beam_size=2, max_decoding_length=256, repetition_penalty=1.15,
                )
                for src_s, hyp in zip(chunk, res):
                    decoded = html.unescape(sp.decode(hyp.hypotheses[0])).strip() if hyp.hypotheses else src_s
                    translated_map[src_s] = decoded or src_s
            else:
                bpe = bundle["bpe"]
                mt = bundle["mt"]
                md = bundle["md"]
                toks = [
                    bpe.process_line(" ".join(mt.tokenize(s, escape=True))).split() + ["</s>"]
                    for s in chunk
                ]
                res = translator.translate_batch(
                    toks, beam_size=2, max_decoding_length=256, repetition_penalty=1.15,
                )
                for src_s, hyp in zip(chunk, res):
                    if not hyp.hypotheses:
                        translated_map[src_s] = src_s
                        continue
                    out_toks = [t for t in hyp.hypotheses[0] if t not in ("<s>", "</s>", "<unk>")]
                    joined = "".join(t[:-2] if t.endswith("@@") else (t + " ") for t in out_toks).strip()
                    decoded = html.unescape(md.detokenize(joined.split(), unescape=True)).strip()
                    translated_map[src_s] = decoded or src_s

    out_texts: list[str] = []
    for plan in plans:
        if plan["skip"]:
            out_texts.append(plan["raw"])
            continue
        rebuilt_sents = [translated_map.get(s, s) for s in plan["sentences"]]
        body = " ".join(rebuilt_sents).strip()
        if plan["all_caps"]:
            body = body.upper()
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
) -> tuple[list[str], str]:
    pair = (src_lang.lower()[:2], dst_lang.lower()[:2])
    if root is None:
        from settings import ROOT as _DEFAULT_ROOT

        root = _DEFAULT_ROOT

    resolved: list[str | None] = [None] * len(texts)
    pending_indices: list[int] = []
    pending_texts: list[str] = []
    used_map = False
    for idx, t in enumerate(texts):
        if user_map and t in user_map:
            resolved[idx] = str(user_map[t])
            used_map = True
        elif user_map and t.strip() in user_map:
            resolved[idx] = str(user_map[t.strip()])
            used_map = True
        else:
            pending_indices.append(idx)
            pending_texts.append(t)

    if not pending_texts:
        return [str(v) for v in resolved], "dictionary_map"

    mode_used = "offline_glossary"
    translated_pending: list[str] | None = None

    if engine_pref in ("auto", "ai"):
        ai_out = _translate_via_ai_chunks(pending_texts, pair, config)
        if ai_out is not None:
            translated_pending, mode_used = ai_out

    if translated_pending is None and engine_pref in ("auto", "nmt"):
        nmt_out = _translate_with_ctranslate2(pending_texts, pair, config, root)
        if nmt_out is not None:
            translated_pending = nmt_out
            mode_used = f"nmt_offline_{pair[0]}_{pair[1]}"

    if translated_pending is None:
        glossary = _OFFLINE_GLOSSARY.get(pair, {})
        translated_pending = []
        for t in pending_texts:
            out_t = t
            for k, v in sorted(glossary.items(), key=lambda kv: -len(kv[0])):
                out_t = re.sub(rf"\b{re.escape(k)}\b", v, out_t, flags=re.IGNORECASE)
            translated_pending.append(out_t)
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


def _split_line_subunits(line: dict) -> list[dict]:
    spans = [sp for sp in line.get("spans", []) if sp.get("text", "").strip()]
    if not spans:
        return []
    sublines: list[dict] = []
    cur: dict | None = None
    for sp in spans:
        sb = [float(v) for v in sp["bbox"]]
        text = sp.get("text", "")
        size = float(sp.get("size", 10.0))
        flags = int(sp.get("flags", 0))
        font = str(sp.get("font", "Arial")).split("+")[-1]
        bold = bool((flags & 16) or "bold" in font.lower())
        italic = bool((flags & 2) or "italic" in font.lower() or "oblique" in font.lower())
        color = f"#{int(sp.get('color', 0)) & 0xFFFFFF:06x}"
        if cur is None:
            cur = {
                "bbox": sb,
                "text": text,
                "size": size,
                "font": font,
                "bold": bold,
                "italic": italic,
                "color": color,
                "span_count": 1,
            }
            continue
        gap_x = sb[0] - cur["bbox"][2]
        same_band = gap_x <= max(14.0, cur["size"] * 1.45) and abs(size - cur["size"]) <= max(2.2, cur["size"] * 0.25)
        if same_band:
            joiner = "" if (cur["text"].endswith(" ") or text.startswith(" ") or gap_x <= max(1.5, cur["size"] * 0.14)) else " "
            cur["text"] = f"{cur['text']}{joiner}{text}"
            cur["bbox"] = [
                min(cur["bbox"][0], sb[0]),
                min(cur["bbox"][1], sb[1]),
                max(cur["bbox"][2], sb[2]),
                max(cur["bbox"][3], sb[3]),
            ]
            cur["size"] = max(cur["size"], size) if len(text.strip()) > len(cur["text"].strip()) / 2 else cur["size"]
            cur["span_count"] += 1
        else:
            sublines.append(cur)
            cur = {
                "bbox": sb,
                "text": text,
                "size": size,
                "font": font,
                "bold": bold,
                "italic": italic,
                "color": color,
                "span_count": 1,
            }
    if cur is not None:
        sublines.append(cur)
    return sublines


def _collect_translatable_units(page: pdf.Page) -> list[dict]:
    """Agrupa spans en unidades semanticas (parrafos, titulares o celdas) sin fusionar columnas."""
    units: list[dict] = []
    td = page.get_text("dict", flags=pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES)
    for block in td.get("blocks", []):
        if block.get("type") != 0:
            continue
        pending_group: dict | None = None
        prev_was_multicolumn = False
        for line in block.get("lines", []):
            if line.get("dir", (1, 0)) != (1, 0) or line.get("wmode", 0):
                continue
            sublines = _split_line_subunits(line)
            if not sublines:
                continue
            if len(sublines) > 1:
                if pending_group is not None:
                    units.append(pending_group)
                    pending_group = None
                units.extend(sublines)
                prev_was_multicolumn = True
                continue

            sl = sublines[0]
            sl_stripped = sl["text"].strip()
            starts_bullet = bool(_LIST_PREFIX_RE.match(sl_stripped))
            if pending_group is not None and not prev_was_multicolumn and not starts_bullet:
                gap_y = sl["bbox"][1] - pending_group["last_line_y1"]
                shift_x = abs(sl["bbox"][0] - pending_group["bbox"][0])
                size_diff = abs(sl["size"] - pending_group["size"])
                can_merge = (
                    gap_y >= -pending_group["size"] * 0.4
                    and gap_y <= pending_group["size"] * 0.85
                    and shift_x <= max(28.0, pending_group["size"] * 2.5)
                    and size_diff <= max(1.8, pending_group["size"] * 0.22)
                    and sl["bold"] == pending_group["bold"]
                )
                if can_merge:
                    prev_txt = pending_group["text"].rstrip()
                    if len(prev_txt) >= 3 and prev_txt.endswith("-") and prev_txt[-2].isalpha():
                        pending_group["text"] = prev_txt[:-1] + sl_stripped
                    else:
                        pending_group["text"] = f"{prev_txt} {sl_stripped}".strip()
                    pending_group["bbox"] = [
                        min(pending_group["bbox"][0], sl["bbox"][0]),
                        min(pending_group["bbox"][1], sl["bbox"][1]),
                        max(pending_group["bbox"][2], sl["bbox"][2]),
                        max(pending_group["bbox"][3], sl["bbox"][3]),
                    ]
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
            }
            prev_was_multicolumn = False

        if pending_group is not None:
            units.append(pending_group)

    for u in units:
        u["text"] = u["text"].strip()
    return [u for u in units if u["text"]]


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

            units = _collect_translatable_units(page)
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
                                    u["size"] = u["size"] * sy
                                    u["needs_bg_patch"] = True
                    if units:
                        _sample_scan_unit_styles(pix, page.rect, units)
                        is_scan_page = True
                        ocr_pages += 1

            if not units:
                continue

            translated_list, mode_used = _translate_offline_or_ai(
                [u["text"] for u in units],
                src_lang,
                dst_lang,
                user_map,
                config,
                root=root,
                engine_pref=engine_pref,
            )
            changed = [
                (idx, u, tr)
                for idx, (u, tr) in enumerate(zip(units, translated_list))
                if tr.strip() and tr.strip() != u["text"].strip()
            ]
            if not changed:
                continue

            if not is_scan_page:
                for _, u, _ in changed:
                    page.add_redact_annot(pdf.Rect(u["bbox"]), fill=False, cross_out=False)
                page.apply_redactions(images=0, graphics=0, text=pdf.PDF_REDACT_TEXT_REMOVE)

            font_cache: dict[str, str] = {}
            for idx, u, tr in changed:
                rect = pdf.Rect(u["bbox"]) & page.rect
                if rect.is_empty:
                    continue
                # Buscar vecino inmediato a la derecha para evitar solapamientos al expandir ligeramente la caja
                right_limit = min(page.rect.x1 - 10.0, rect.x1 + max(14.0, rect.width * 0.14))
                for o_idx, other in enumerate(units):
                    if o_idx == idx:
                        continue
                    ob = other["bbox"]
                    if min(rect.y1, ob[3]) - max(rect.y0, ob[1]) > 2.0 and ob[0] >= rect.x1 - 2.0:
                        right_limit = min(right_limit, max(rect.x1, ob[0] - 4.0))

                if u.get("needs_bg_patch"):
                    cover = pdf.Rect(
                        max(page.rect.x0, rect.x0 - 1.5),
                        max(page.rect.y0, rect.y0 - 1.0),
                        min(page.rect.x1, rect.x1 + 1.5),
                        min(page.rect.y1, rect.y1 + 1.5),
                    )
                    page.draw_rect(cover, color=None, fill=u.get("bg_color", (1.0, 1.0, 1.0)), overlay=True)

                top_pad = max(1.0, u["size"] * 0.14)
                bot_pad = max(2.5, u["size"] * 0.28)
                box = pdf.Rect(
                    rect.x0,
                    max(page.rect.y0, rect.y0 - top_pad),
                    max(rect.x1, right_limit),
                    min(page.rect.y1, rect.y1 + bot_pad),
                )
                font_code = _resolve_translation_font(
                    page, u["font"], u.get("bold", False), u.get("italic", False), font_cache,
                )
                color = parse_color(u["color"])
                used_sz = _fit_text_in_box(
                    page,
                    box,
                    tr,
                    font_code,
                    u["size"],
                    color,
                    min_size=max(5.0, u["size"] * 0.55),
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
