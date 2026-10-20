from __future__ import annotations

import io
import json
import math
import os
import secrets
import shutil
from pathlib import Path

import pymupdf as pdf

from pdf_engine import ProcessingError, check_size, open_pdf, save

ACROBAT_OPERATIONS = {"edit_text_pro"}

# Fuentes estándar de Windows y mapeo de fuentes comunes
WINDOWS_FONTS_DIR = Path("C:/Windows/Fonts")

FONT_FAMILY_MAPPING = {
    "arial": {
        (False, False): "arial.ttf",
        (True, False): "arialbd.ttf",
        (False, True): "ariali.ttf",
        (True, True): "arialbi.ttf",
    },
    "calibri": {
        (False, False): "calibri.ttf",
        (True, False): "calibrib.ttf",
        (False, True): "calibrii.ttf",
        (True, True): "calibriz.ttf",
    },
    "times new roman": {
        (False, False): "times.ttf",
        (True, False): "timesbd.ttf",
        (False, True): "timesi.ttf",
        (True, True): "timesbi.ttf",
    },
    "georgia": {
        (False, False): "georgia.ttf",
        (True, False): "georgiab.ttf",
        (False, True): "georgiai.ttf",
        (True, True): "georgiaz.ttf",
    },
    "verdana": {
        (False, False): "verdana.ttf",
        (True, False): "verdanab.ttf",
        (False, True): "verdanai.ttf",
        (True, True): "verdanaz.ttf",
    },
    "tahoma": {
        (False, False): "tahoma.ttf",
        (True, False): "tahomabd.ttf",
        (False, True): "tahoma.ttf",
        (True, True): "tahomabd.ttf",
    },
    "segoe ui": {
        (False, False): "segoeui.ttf",
        (True, False): "segoeuib.ttf",
        (False, True): "segoeuii.ttf",
        (True, True): "segoeuiz.ttf",
    },
    "trebuchet ms": {
        (False, False): "trebuc.ttf",
        (True, False): "trebucbd.ttf",
        (False, True): "trebucit.ttf",
        (True, True): "trebucbi.ttf",
    },
    "courier new": {
        (False, False): "cour.ttf",
        (True, False): "courbd.ttf",
        (False, True): "couri.ttf",
        (True, True): "courbi.ttf",
    },
}


def extract_page_blocks(page: pdf.Page) -> list[dict]:
    """Separa fragmentos por linea y estilo para no agrupar celdas o formatos distintos."""
    text_page = page.get_text("dict", flags=pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES)
    blocks = []
    width = page.rect.width
    height = page.rect.height

    for b_idx, block in enumerate(text_page.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for l_idx, line in enumerate(block.get("lines", [])):
            if line.get("dir", (1, 0)) != (1, 0) or line.get("wmode", 0):
                continue
            for s_idx, span in enumerate(line.get("spans", [])):
                if not span.get("text", "").strip():
                    continue
                x0, y0, x1, y1 = [float(v) for v in span["bbox"]]
                font_name = span.get("font", "Helvetica")
                flags = span.get("flags", 0)
                blocks.append({
                    "id": f"blk_{b_idx}_{l_idx}_{s_idx}",
                    "bbox": [x0, y0, x1, y1],
                    "rel_bbox": [x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height],
                    "origin": list(span["origin"]),
                    "text": span["text"],
                    "font": font_name,
                    "size": float(span.get("size", 12)),
                    "color": f"#{span.get('color', 0):06x}",
                    "bold": bool(flags & 16 or "bold" in font_name.lower()),
                    "italic": bool(flags & 2 or "italic" in font_name.lower() or "oblique" in font_name.lower()),
                    "lines_count": 1,
                })
    return blocks


def text_background(doc: pdf.Document, page_number: int, dpi: int, config: dict) -> str:
    """Renderiza el fondo real sin texto, conservando imagenes y trazos vectoriales."""
    import base64
    from pdf_engine import render

    with pdf.open() as preview:
        preview.insert_pdf(doc, from_page=page_number, to_page=page_number)
        page = preview[0]
        for block in extract_page_blocks(page):
            page.add_redact_annot(pdf.Rect(block["bbox"]), fill=False, cross_out=False)
        page.apply_redactions(images=0, graphics=0, text=pdf.PDF_REDACT_TEXT_REMOVE)
        return base64.b64encode(render(page, dpi, config).tobytes("png")).decode("ascii")


def parse_color(color_val) -> tuple[float, float, float]:
    """Parsea representaciones hex o listas de color a tuplas normalizadas (r, g, b) entre 0.0 y 1.0."""
    if isinstance(color_val, (list, tuple)) and len(color_val) >= 3:
        vals = [float(v) for v in color_val[:3]]
        if any(v > 1.0 for v in vals):
            return tuple(max(0.0, min(1.0, v / 255.0)) for v in vals)
        return tuple(max(0.0, min(1.0, v)) for v in vals)
    if isinstance(color_val, str):
        val = color_val.strip().lstrip("#")
        if len(val) == 6:
            try:
                r = int(val[0:2], 16) / 255.0
                g = int(val[2:4], 16) / 255.0
                b = int(val[4:6], 16) / 255.0
                return (r, g, b)
            except ValueError:
                pass
        elif len(val) == 3:
            try:
                r = int(val[0] * 2, 16) / 255.0
                g = int(val[1] * 2, 16) / 255.0
                b = int(val[2] * 2, 16) / 255.0
                return (r, g, b)
            except ValueError:
                pass
    return (0.0, 0.0, 0.0)


def resolve_font(page: pdf.Page, font_family: str, bold: bool = False, italic: bool = False) -> str:
    """Resuelve la tipografía seleccionada usando las fuentes nativas de alta fidelidad de la especificación PDF."""
    family_lower = (font_family or "helvetica").lower().strip()
    if any(k in family_lower for k in ("times", "roman", "georgia", "serif")):
        return "tibi" if (bold and italic) else "tibo" if bold else "tiit" if italic else "tiro"
    elif any(k in family_lower for k in ("courier", "mono", "consolas")):
        return "cobi" if (bold and italic) else "cobo" if bold else "coit" if italic else "cour"
    else:
        return "hebi" if (bold and italic) else "hebo" if bold else "heit" if italic else "helv"


def get_alignment_code(align_str: str) -> int:
    """Convierte el valor de alineación a la constante de PyMuPDF."""
    align_val = str(align_str).lower().strip()
    if align_val == "center":
        return pdf.TEXT_ALIGN_CENTER
    elif align_val == "right":
        return pdf.TEXT_ALIGN_RIGHT
    elif align_val == "justify":
        return pdf.TEXT_ALIGN_JUSTIFY
    return pdf.TEXT_ALIGN_LEFT


def process_acrobat(operation: str, sources: list[Path], options: dict, folder: Path, config: dict) -> dict:
    """Aplica ediciones directas de texto estilo Adobe Acrobat Pro DC sobre el documento PDF."""
    if operation != "edit_text_pro":
        raise ProcessingError("Herramienta Acrobat no valida.", 404)
    if len(sources) != 1:
        raise ProcessingError("Seleccione exactamente un archivo PDF para editar.")

    source = sources[0]
    password = options.get("password", "")
    changes = options.get("changes", [])
    if not isinstance(changes, list):
        raise ProcessingError("Formato de cambios no valido.", 400)
    if len(changes) > 500:
        raise ProcessingError("Maximo 500 modificaciones por sesion.", 400)

    output = folder / "documento_editado.pdf"

    with open_pdf(source, password, config["max_pages"]) as doc:
        # 1. Accion: Reemplazar todas las ocurrencias (Find & Replace)
        for change in changes:
            if not isinstance(change, dict):
                continue
            if change.get("action") == "replace_all":
                find_str = str(change.get("find", "")).strip()
                replace_str = str(change.get("replace", ""))
                if not find_str:
                    continue
                pages_spec = change.get("pages", "")
                selected_pages = range(len(doc)) if not pages_spec else [
                    p - 1 for p in range(1, len(doc) + 1)
                    if str(p) in pages_spec.split(",")
                ]
                font_name = change.get("font", "helv")
                font_code = resolve_font(doc[0], font_name)

                for page_num in selected_pages:
                    if 0 <= page_num < len(doc):
                        page = doc[page_num]
                        matches = page.search_for(find_str)
                        if matches:
                            for match_rect in matches:
                                page.add_redact_annot(match_rect, fill=False, cross_out=False)
                            page.apply_redactions(images=0, graphics=0, text=pdf.PDF_REDACT_TEXT_REMOVE)
                            for match_rect in matches:
                                est_width = max(match_rect.width, match_rect.width * (len(replace_str) / max(1, len(find_str))))
                                ins_rect = pdf.Rect(match_rect.x0, match_rect.y0 - 1, min(page.rect.x1 - 5, match_rect.x0 + est_width + 4), match_rect.y1 + 3)
                                if replace_str and page.insert_textbox(
                                    ins_rect, replace_str, fontsize=round(match_rect.height * 0.75, 1),
                                    fontname=font_code, color=(0, 0, 0)
                                ) < 0:
                                    raise ProcessingError("El reemplazo no cabe. Edite el fragmento individualmente.")

        # 2. Agrupar acciones por pagina para redaccion limpia sin superposicion
        page_changes: dict[int, list[dict]] = {}
        for change in changes:
            if not isinstance(change, dict) or change.get("action") == "replace_all":
                continue
            p = int(change.get("page", 1)) - 1
            if 0 <= p < len(doc):
                page_changes.setdefault(p, []).append(change)

        # 3. Procesar cada pagina: redaccion limpia previa de todos los bloques originales y luego insercion
        for page_num, p_changes in page_changes.items():
            page = doc[page_num]
            originals = extract_page_blocks(page)

            # Paso A: Redactar TODOS los bloques a modificar o eliminar en esta pagina
            for change in p_changes:
                action = change.get("action", "modify")
                if action in ("delete", "modify"):
                    orig_bbox = change.get("orig_bbox")
                    if orig_bbox and len(orig_bbox) == 4:
                        orig_rect = pdf.Rect(orig_bbox)
                        if not any(all(abs(a - b) < 0.05 for a, b in zip(orig_bbox, block["bbox"]))
                                   for block in originals):
                            raise ProcessingError("El texto seleccionado ya no coincide con el PDF. Recargue la pagina.")
                        page.add_redact_annot(orig_rect, fill=False, cross_out=False)

            # Aplicar todas las redacciones de la pagina de una sola vez
            page.apply_redactions(images=0, graphics=0, text=pdf.PDF_REDACT_TEXT_REMOVE)

            # Paso B: Insertar textos modificados y cuadros nuevos (evita cualquier superposicion)
            for change in p_changes:
                action = change.get("action", "modify")
                if action in ("modify", "add"):
                    text = str(change.get("text", ""))
                    if not text.strip():
                        continue
                    target_bbox = change.get("bbox") or change.get("orig_bbox")
                    if target_bbox and len(target_bbox) == 4:
                        x0, y0, x1, y1 = [float(v) for v in target_bbox]
                        target_rect = pdf.Rect(x0, y0, x1, y1)
                        font_family = str(change.get("font", "Arial"))
                        font_size = float(change.get("size", 12.0))
                        bold = bool(change.get("bold", False))
                        italic = bool(change.get("italic", False))
                        underline = bool(change.get("underline", False))
                        color = parse_color(change.get("color", "#000000"))
                        align = get_alignment_code(change.get("align", "left"))
                        line_spacing = float(change.get("line_spacing", 1.15))
                        rotation = int(change.get("rotation", 0)) % 360

                        font_code = resolve_font(page, font_family, bold=bold, italic=italic)
                        original = next((block for block in originals
                                         if change.get("orig_bbox") and all(
                                             abs(a - b) < 0.05 for a, b in zip(change["orig_bbox"], block["bbox"]))), None)
                        if original and "\n" not in text and rotation == 0 and align == pdf.TEXT_ALIGN_LEFT and not underline:
                            if pdf.get_text_length(text, fontname=font_code, fontsize=font_size) > target_rect.width + 0.1:
                                raise ProcessingError("El texto no cabe en su espacio original. Amplie el ancho o reduzca el tamano.")
                            origin = original["origin"]
                            page.insert_text(
                                (target_rect.x0 + origin[0] - original["bbox"][0],
                                 target_rect.y0 + origin[1] - original["bbox"][1]),
                                text, fontsize=font_size, fontname=font_code, color=color,
                            )
                            continue
                        rc = page.insert_textbox(
                            target_rect, text,
                            fontsize=font_size,
                            fontname=font_code,
                            color=color,
                            align=align,
                            lineheight=line_spacing,
                            rotate=rotation,
                        )
                        if rc < 0:
                            raise ProcessingError("El texto no cabe. Amplie el cuadro o reduzca el tamano; no se expandira sobre otras celdas.")

                        if underline and text.strip():
                            page.draw_line(
                                (target_rect.x0, target_rect.y1),
                                (min(page.rect.x1, target_rect.x1), target_rect.y1),
                                color=color,
                                width=max(0.75, font_size / 16)
                            )

        save(doc, output)

    check_size(output, config)
    count = len(changes)
    notice = (f"Edicion de texto: {count} cambios, sin rellenos de fondo. "
              "Las fuentes se sustituyen por Helvetica, Times o Courier compatibles; revise el resultado. "
              "No reconstruye parrafos ni edita texto dentro de imagenes.")
    if options.get("editor_preview") is True:
        from pdf_engine import process

        preview = process("inspect", [output], {
            "page": options.get("page", 1), "dpi": 130, "text_background": True,
        }, folder, config, folder)
        boundary = secrets.token_hex(24)
        bundle = folder / "edicion.multipart"
        with bundle.open("wb") as destination:
            for field, path, mimetype in (
                ("document", output, "application/pdf"),
                ("preview", folder / preview["file"], "application/json"),
            ):
                destination.write((
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
                    f"Content-Type: {mimetype}\r\n\r\n"
                ).encode("ascii"))
                with path.open("rb") as source_file:
                    shutil.copyfileobj(source_file, destination)
                destination.write(b"\r\n")
            destination.write(f"--{boundary}--\r\n".encode("ascii"))
        check_size(bundle, config)
        return {"file": bundle.name, "notice": notice, "editor_boundary": boundary}
    return {"file": output.name, "notice": notice}
