from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import openpyxl
import pymupdf as pdf
from lxml import etree

from acrobat_tools import parse_color, resolve_font
from pdf_engine import ProcessingError, clean_text, excel_text, open_pdf, pages_from, save


def _parse_number(options: dict, key: str, default: float, low: float, high: float) -> float:
    val = options.get(key, default)
    if isinstance(val, bool):
        raise ProcessingError(f"{key}: valor booleano no valido.", 400)
    try:
        num = float(val)
    except (ValueError, TypeError):
        raise ProcessingError(f"{key}: debe ser numerico.", 400) from None
    if not math.isfinite(num) or not low <= num <= high:
        raise ProcessingError(f"{key}: valor fuera de rango ({low}-{high}).", 400)
    return num


def _svg_to_simple_eps(svg_bytes: bytes, width: float, height: float) -> bytes:
    """Genera un EPS ASCII nivel 2 conservando trazados SVG basico y texto sin PostScript peligroso."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    root = etree.fromstring(svg_bytes, parser=parser)
    lines = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%BoundingBox: 0 0 {int(math.ceil(max(1.0, width)))} {int(math.ceil(max(1.0, height)))}",
        "%%Creator: EVA PDF Enterprise Vector Harvester",
        "%%EndComments",
        "gsave",
        f"0 {height:.2f} translate 1 -1 scale",
    ]
    path_count = 0
    for elem in root.iter():
        tag = etree.QName(elem).localname if isinstance(elem.tag, str) else ""
        if tag == "rect":
            try:
                x = float(elem.get("x", 0))
                y = float(elem.get("y", 0))
                w = float(elem.get("width", 0))
                h = float(elem.get("height", 0))
                lines.append(f"newpath {x:.2f} {y:.2f} moveto {w:.2f} 0 rlineto 0 {h:.2f} rlineto {-w:.2f} 0 rlineto closepath stroke")
                path_count += 1
            except ValueError:
                continue
        elif tag == "path":
            d = elem.get("d", "")
            tokens = re.findall(r"[MLHVZCmlhvzc]|-?\d+(?:\.\d+)?", d)
            if tokens:
                lines.append("newpath")
                cx = cy = 0.0
                idx = 0
                cmd = ""
                while idx < len(tokens):
                    t = tokens[idx]
                    if t.isalpha():
                        cmd = t
                        idx += 1
                        if cmd in ("Z", "z"):
                            lines.append("closepath")
                        continue
                    try:
                        if cmd in ("M", "m") and idx + 1 < len(tokens):
                            x, y = float(tokens[idx]), float(tokens[idx + 1])
                            cx, cy = (x, y) if cmd == "M" else (cx + x, cy + y)
                            lines.append(f"{cx:.2f} {cy:.2f} moveto")
                            idx += 2
                            cmd = "L" if cmd == "M" else "l"
                        elif cmd in ("L", "l") and idx + 1 < len(tokens):
                            x, y = float(tokens[idx]), float(tokens[idx + 1])
                            cx, cy = (x, y) if cmd == "L" else (cx + x, cy + y)
                            lines.append(f"{cx:.2f} {cy:.2f} lineto")
                            idx += 2
                        elif cmd in ("H", "h"):
                            x = float(tokens[idx])
                            cx = x if cmd == "H" else cx + x
                            lines.append(f"{cx:.2f} {cy:.2f} lineto")
                            idx += 1
                        elif cmd in ("V", "v"):
                            y = float(tokens[idx])
                            cy = y if cmd == "V" else cy + y
                            lines.append(f"{cx:.2f} {cy:.2f} lineto")
                            idx += 1
                        elif cmd in ("C", "c") and idx + 5 < len(tokens):
                            pts = [float(tokens[idx + k]) for k in range(6)]
                            if cmd == "c":
                                pts = [
                                    cx + pts[0], cy + pts[1],
                                    cx + pts[2], cy + pts[3],
                                    cx + pts[4], cy + pts[5],
                                ]
                            lines.append(
                                f"{pts[0]:.2f} {pts[1]:.2f} {pts[2]:.2f} {pts[3]:.2f} {pts[4]:.2f} {pts[5]:.2f} curveto"
                            )
                            cx, cy = pts[4], pts[5]
                            idx += 6
                        else:
                            idx += 1
                    except ValueError:
                        break
                lines.append("stroke")
                path_count += 1
    if path_count == 0:
        lines.append(f"newpath 0 0 moveto {width:.2f} {height:.2f} lineto stroke")
    lines.extend(["grestore", "%%EOF"])
    return "\n".join(lines).encode("ascii", errors="ignore")


def _structure_svg_layers(svg_text: str, clip_rect: pdf.Rect, group_labels: bool) -> str:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    root = etree.fromstring(svg_text.encode("utf-8"), parser=parser)
    w = max(1.0, float(clip_rect.width))
    h = max(1.0, float(clip_rect.height))
    root.set("viewBox", f"0 0 {w:.2f} {h:.2f}")
    root.set("width", f"{w:.2f}pt")
    root.set("height", f"{h:.2f}pt")
    if not group_labels:
        return etree.tostring(root, encoding="unicode")

    ns = root.nsmap.get(None, "http://www.w3.org/2000/svg")
    g_vectors = etree.Element(f"{{{ns}}}g", id="vectors")
    g_labels = etree.Element(f"{{{ns}}}g", id="labels")

    # Extraer recursivamente nodos <text> manteniendo cualquier transform de grupo padre hacia #labels
    def _partition_node(node, ancestor_transforms: list[str]):
        if not isinstance(node.tag, str):
            return []
        local = etree.QName(node).localname
        if local == "text":
            if ancestor_transforms:
                wrapper = etree.Element(f"{{{ns}}}g")
                wrapper.set("transform", " ".join(ancestor_transforms))
                wrapper.append(node)
                g_labels.append(wrapper)
            else:
                g_labels.append(node)
            return None
        tf = node.get("transform")
        next_tfs = [*ancestor_transforms, tf] if tf else ancestor_transforms
        for sub in list(node):
            local_sub = etree.QName(sub).localname if isinstance(sub.tag, str) else ""
            if local_sub == "text":
                node.remove(sub)
                _partition_node(sub, next_tfs)
            elif local_sub == "g":
                _partition_node(sub, next_tfs)
        return node

    children = list(root)
    for child in children:
        if not isinstance(child.tag, str):
            continue
        local = etree.QName(child).localname
        if local in ("defs", "metadata", "title", "desc"):
            continue
        root.remove(child)
        res = _partition_node(child, [])
        if res is not None:
            g_vectors.append(res)

    if len(g_vectors):
        root.append(g_vectors)
    if len(g_labels):
        root.append(g_labels)
    return etree.tostring(root, encoding="unicode")


def handle_extract_vectors_svg(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    password = str(options.get("password", ""))
    expand_pt = _parse_number(options, "expand_pt", 8.0, 0.0, 48.0)
    group_labels = bool(options.get("group_labels", True))
    include_eps = bool(options.get("include_eps", False)) or str(options.get("format", "svg")).lower() in ("eps", "svg_eps")
    fallback_full_page = bool(options.get("fallback_full_page", True))

    bundle = folder / "vectores.zip"
    manifest: list[dict] = []
    exported = 0

    with open_pdf(source, password, config["max_pages"]) as doc:
        selected = pages_from(options.get("pages", ""), len(doc))
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for pno in selected:
                page = doc[pno]
                clusters = list(page.cluster_drawings() or [])
                clips: list[pdf.Rect] = []
                for rect in clusters:
                    expanded = pdf.Rect(
                        rect.x0 - expand_pt,
                        rect.y0 - expand_pt,
                        rect.x1 + expand_pt,
                        rect.y1 + expand_pt,
                    ) & page.rect
                    if not expanded.is_empty and expanded.width >= 4 and expanded.height >= 4:
                        clips.append(expanded)

                if not clips and fallback_full_page and (page.get_drawings() or page.get_text("dict").get("blocks")):
                    clips = [page.rect]

                for c_idx, clip in enumerate(clips, 1):
                    # page.get_svg_image(clip=...) en PyMuPDF toma la pagina entera o via pagina recortada temporal
                    if clip == page.rect:
                        raw_svg = page.get_svg_image(text_as_path=False)
                    else:
                        with pdf.open() as tmp_doc:
                            tmp_page = tmp_doc.new_page(width=clip.width, height=clip.height)
                            tmp_page.show_pdf_page(tmp_page.rect, doc, pno, clip=clip)
                            raw_svg = tmp_page.get_svg_image(text_as_path=False)
                    structured = _structure_svg_layers(raw_svg, clip, group_labels=group_labels)
                    svg_name = f"grafico-p{pno + 1:03d}-{c_idx:02d}.svg"
                    archive.writestr(svg_name, structured.encode("utf-8"))
                    entry = {
                        "file": svg_name,
                        "page": pno + 1,
                        "bbox": [round(float(v), 2) for v in clip],
                        "width_pt": round(float(clip.width), 2),
                        "height_pt": round(float(clip.height), 2),
                    }
                    if include_eps:
                        eps_name = f"grafico-p{pno + 1:03d}-{c_idx:02d}.eps"
                        eps_bytes = _svg_to_simple_eps(structured.encode("utf-8"), clip.width, clip.height)
                        archive.writestr(eps_name, eps_bytes)
                        entry["eps_file"] = eps_name
                    manifest.append(entry)
                    exported += 1
            if not exported:
                raise ProcessingError("No se encontraron trazos vectoriales ni graficos en las paginas seleccionadas.")
            archive.writestr("manifiesto-vectores.json", json.dumps({"clusters": manifest}, ensure_ascii=False, indent=2))

    return {
        "file": bundle.name,
        "notice": f"Cosecha vectorial completa: {exported} graficos SVG editables extraidos.",
    }


def _parse_typed_cell(text: str) -> dict:
    raw = text.strip()
    if not raw:
        return {"type": "text", "value": "", "currency": None}

    if raw.endswith("%"):
        candidate = raw[:-1].strip().replace(" ", "")
        num = _to_float_locale(candidate)
        if num is not None:
            return {"type": "percent", "value": round(num / 100.0, 6), "currency": None}

    cur_match = re.fullmatch(
        r"([+-])?\s*(USD|EUR|COP|MXN|GBP|JPY|CHF|BRL|ARS|CLP|PEN|\$|€|£)?\s*([+-]?\d[\d.,\s]*)\s*(USD|EUR|COP|MXN|GBP|\$|€|£)?",
        raw,
        re.IGNORECASE,
    )
    if cur_match and (cur_match.group(2) or cur_match.group(4)):
        sign = -1.0 if cur_match.group(1) == "-" else 1.0
        symbol = (cur_match.group(2) or cur_match.group(4) or "").upper()
        num = _to_float_locale(cur_match.group(3))
        if num is not None:
            return {"type": "currency", "value": round(sign * num, 4), "currency": symbol}

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return {"type": "date", "value": dt.strftime("%Y-%m-%d"), "currency": None}
        except ValueError:
            continue

    num = _to_float_locale(raw)
    if num is not None:
        if float(num).is_integer() and "." not in raw and "," not in raw:
            return {"type": "integer", "value": int(num), "currency": None}
        return {"type": "float", "value": num, "currency": None}

    return {"type": "text", "value": raw, "currency": None}


def _to_float_locale(raw: str) -> float | None:
    s = raw.replace(" ", "").strip()
    if not re.fullmatch(r"[+-]?\d+(?:[.,]\d+)*", s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts[-1]) in (1, 2) or len(parts) > 2 and len(parts[-1]) != 3:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        val = float(s)
        return val if math.isfinite(val) else None
    except ValueError:
        return None


def _detect_borderless_tables(page: pdf.Page, ruled_boxes: list[pdf.Rect]) -> list[dict]:
    """Agrupa palabras por bandas Y y columnas X consistentes fuera de tablas con bordes."""
    words = page.get_text("words") or []
    filtered = []
    for w in words:
        x0, y0, x1, y1, text, *_ = w
        rect = pdf.Rect(x0, y0, x1, y1)
        if any(rb.intersects(rect) for rb in ruled_boxes):
            continue
        if text.strip():
            filtered.append((x0, y0, x1, y1, text))
    if len(filtered) < 4:
        return []

    # Agrupar por lineas Y (tolerancia 3.5 pt)
    filtered.sort(key=lambda item: (round(item[1], 1), item[0]))
    rows_words: list[list[tuple]] = []
    for item in filtered:
        if not rows_words or abs(item[1] - rows_words[-1][0][1]) > 4.0:
            rows_words.append([item])
        else:
            rows_words[-1].append(item)

    # Dividir cada fila en celdas cuando hay brecha horizontal >= 14 pt
    row_cells: list[list[tuple[float, float, float, float, str]]] = []
    for rwords in rows_words:
        rwords.sort(key=lambda it: it[0])
        cells_in_row = []
        cur = [rwords[0]]
        for it in rwords[1:]:
            gap = it[0] - cur[-1][2]
            if gap >= 12.0:
                cells_in_row.append((
                    min(c[0] for c in cur),
                    min(c[1] for c in cur),
                    max(c[2] for c in cur),
                    max(c[3] for c in cur),
                    " ".join(c[4] for c in cur),
                ))
                cur = [it]
            else:
                cur.append(it)
        cells_in_row.append((
            min(c[0] for c in cur),
            min(c[1] for c in cur),
            max(c[2] for c in cur),
            max(c[3] for c in cur),
            " ".join(c[4] for c in cur),
        ))
        row_cells.append(cells_in_row)

    # Detectar bloques consecutivos de >= 2 filas con >= 2 celdas por fila
    tables = []
    run: list[list[tuple]] = []
    for rc in row_cells:
        if len(rc) >= 2:
            run.append(rc)
        else:
            if len(run) >= 2:
                tables.append(run)
            run = []
    if len(run) >= 2:
        tables.append(run)

    extracted = []
    for tbl in tables:
        # Column clustering basado en centros/x0
        x_anchors: list[float] = []
        for rc in tbl:
            for x0, *_ in rc:
                if not any(abs(x0 - ax) <= 18.0 for ax in x_anchors):
                    x_anchors.append(x0)
        x_anchors.sort()
        if len(x_anchors) < 2:
            continue
        col_count = len(x_anchors)
        rows_out = []
        min_x = min(c[0] for rc in tbl for c in rc)
        min_y = min(c[1] for rc in tbl for c in rc)
        max_x = max(c[2] for rc in tbl for c in rc)
        max_y = max(c[3] for rc in tbl for c in rc)
        for r_idx, rc in enumerate(tbl):
            row_map = {col: {"text": "", "bbox": None} for col in range(col_count)}
            for x0, y0, x1, y1, txt in rc:
                col_idx = min(range(col_count), key=lambda idx: abs(x0 - x_anchors[idx]))
                existing = row_map[col_idx]
                if existing["text"]:
                    existing["text"] = f"{existing['text']} {txt}"
                    bx = existing["bbox"]
                    existing["bbox"] = [min(bx[0], x0), min(bx[1], y0), max(bx[2], x1), max(bx[3], y1)]
                else:
                    row_map[col_idx] = {"text": txt, "bbox": [x0, y0, x1, y1]}
            # Completar bbox sintetico en celdas vacias
            row_y0 = min(c[1] for c in rc)
            row_y1 = max(c[3] for c in rc)
            row_list = []
            for col in range(col_count):
                cell = row_map[col]
                if cell["bbox"] is None:
                    cx0 = x_anchors[col]
                    cx1 = x_anchors[col + 1] - 4.0 if col + 1 < col_count else max_x
                    cell["bbox"] = [cx0, row_y0, max(cx0 + 10.0, cx1), row_y1]
                row_list.append(cell)
            rows_out.append(row_list)
        extracted.append({
            "mode": "borderless",
            "bbox": [round(min_x, 2), round(min_y, 2), round(max_x, 2), round(max_y, 2)],
            "rows": rows_out,
        })
    return extracted


def _dominant_span_style(page: pdf.Page, rect: pdf.Rect) -> dict:
    style = {"font": "Arial", "size": 10.0, "color": "#000000"}
    best_overlap = 0.0
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if not span.get("text", "").strip():
                    continue
                sb = pdf.Rect(span["bbox"]) & rect
                area = sb.get_area() if not sb.is_empty else 0.0
                if area > best_overlap:
                    best_overlap = area
                    style = {
                        "font": str(span.get("font", "Arial")).split("+")[-1],
                        "size": float(span.get("size", 10.0)),
                        "color": f"#{int(span.get('color', 0)) & 0xFFFFFF:06x}",
                    }
    return style


def _extract_tables_from_doc(doc: pdf.Document, selected: list[int], include_borderless: bool) -> list[dict]:
    tables_out: list[dict] = []
    for pno in selected:
        page = doc[pno]
        ruled_boxes: list[pdf.Rect] = []
        # Tablas con reglas explicitas
        finder = page.find_tables()
        for t in finder.tables:
            trect = pdf.Rect(t.bbox)
            ruled_boxes.append(trect)
            text_rows = t.extract()
            rows_structured = []
            for r_idx, row_obj in enumerate(t.rows):
                cells_structured = []
                row_texts = text_rows[r_idx] if r_idx < len(text_rows) else []
                for c_idx, cell_bbox in enumerate(row_obj.cells):
                    txt = (row_texts[c_idx] or "") if c_idx < len(row_texts) and row_texts[c_idx] else ""
                    txt = " ".join(txt.split())
                    cb = pdf.Rect(cell_bbox) if cell_bbox else trect
                    cells_structured.append({"text": txt, "bbox": [round(float(v), 2) for v in cb]})
                if cells_structured:
                    rows_structured.append(cells_structured)
            if rows_structured:
                tables_out.append({
                    "page": pno + 1,
                    "mode": "ruled",
                    "bbox": [round(float(v), 2) for v in trect],
                    "rows": rows_structured,
                })

        if include_borderless:
            for bt in _detect_borderless_tables(page, ruled_boxes):
                tables_out.append({"page": pno + 1, **bt})

        # Enriquecer cada celda con tipado y estilo dominante
        for t_idx in range(len(tables_out)):
            tbl = tables_out[t_idx]
            if tbl["page"] != pno + 1 or tbl.get("enriched"):
                continue
            tbl["table_id"] = f"T{t_idx + 1:02d}"
            for r_idx, row in enumerate(tbl["rows"]):
                for c_idx, cell in enumerate(row):
                    typed = _parse_typed_cell(cell["text"])
                    style = _dominant_span_style(page, pdf.Rect(cell["bbox"]))
                    cell["cell_id"] = f"{tbl['table_id']}_R{r_idx + 1}_C{c_idx + 1}"
                    cell["typed"] = typed
                    cell["style"] = style
            tbl["enriched"] = True
    return tables_out


def _build_typed_xlsx(tables: list[dict], out_path: Path) -> None:
    wb = openpyxl.Workbook()
    ws_default = wb.active
    coord_ws = wb.create_sheet("_EVA_COORDS")
    coord_ws.sheet_state = "hidden"
    coord_ws.append([
        "sheet", "table_id", "page", "row", "col", "cell_id", "bbox_json",
        "orig_text", "inferred_type", "currency", "font", "size", "color",
    ])
    for idx, tbl in enumerate(tables, 1):
        sheet_name = f"Tabla_{idx:02d}"
        ws = ws_default if idx == 1 else wb.create_sheet(sheet_name)
        ws.title = sheet_name
        for r_idx, row in enumerate(tbl["rows"], 1):
            for c_idx, cell in enumerate(row, 1):
                typed = cell["typed"]
                xl_cell = ws.cell(row=r_idx, column=c_idx)
                tkind = typed["type"]
                if tkind in ("integer", "float"):
                    xl_cell.value = typed["value"]
                elif tkind == "percent":
                    xl_cell.value = typed["value"]
                    xl_cell.number_format = "0.00%"
                elif tkind == "currency":
                    xl_cell.value = typed["value"]
                    xl_cell.number_format = "#,##0.00"
                else:
                    xl_cell.value = excel_text(cell["text"])
                coord_ws.append([
                    sheet_name,
                    tbl["table_id"],
                    tbl["page"],
                    r_idx,
                    c_idx,
                    cell["cell_id"],
                    json.dumps(cell["bbox"]),
                    excel_text(cell["text"]),
                    tkind,
                    typed.get("currency") or "",
                    cell["style"]["font"],
                    cell["style"]["size"],
                    cell["style"]["color"],
                ])
    wb.save(out_path)


def handle_table_bridge_extract(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    source = sources[0]
    password = str(options.get("password", ""))
    include_borderless = bool(options.get("include_borderless", True))
    out_format = str(options.get("format", "xlsx")).lower()
    if out_format not in ("xlsx", "json", "zip"):
        raise ProcessingError("Formato tabular no valido (use xlsx, json o zip).", 400)

    with open_pdf(source, password, config["max_pages"]) as doc:
        selected = pages_from(options.get("pages", ""), len(doc))
        tables = _extract_tables_from_doc(doc, selected, include_borderless=include_borderless)
    if not tables:
        raise ProcessingError("No se detectaron tablas con o sin bordes en las paginas indicadas.")

    payload = {"table_count": len(tables), "tables": tables}
    notice = f"Puente tabular tipado: {len(tables)} tablas extraidas con coordenadas exactas."

    if out_format == "json":
        out_json = folder / "tablas_tipadas.json"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"file": out_json.name, "notice": notice}

    out_xlsx = folder / "tablas_tipadas.xlsx"
    _build_typed_xlsx(tables, out_xlsx)
    if out_format == "xlsx":
        return {"file": out_xlsx.name, "notice": notice}

    bundle = folder / "tablas_tipadas.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(out_xlsx, "tablas_tipadas.xlsx")
        archive.writestr("tablas_tipadas.json", json.dumps(payload, ensure_ascii=False, indent=2))
        for idx, tbl in enumerate(tables, 1):
            buf = io.StringIO()
            writer = csv.writer(buf)
            for row in tbl["rows"]:
                writer.writerow([excel_text(cell["text"]) for cell in row])
            archive.writestr(f"tabla-{idx:02d}.csv", buf.getvalue().encode("utf-8"))
    return {"file": bundle.name, "notice": notice}


def _fit_text_in_box(
    page: pdf.Page,
    rect: pdf.Rect,
    text: str,
    fontname: str,
    base_size: float,
    color: tuple[float, float, float],
    min_size: float = 5.5,
    align: int = pdf.TEXT_ALIGN_LEFT,
) -> float:
    size = max(min_size, min(36.0, float(base_size)))
    while size >= min_size:
        res = page.insert_textbox(rect, text, fontsize=size, fontname=fontname, color=color, align=align)
        if res >= 0:
            return size
        size = round(size - 0.5, 2)
    # Ultimo recurso con recuadro ligeramente ampliado verticalmente
    padded = pdf.Rect(rect.x0, rect.y0 - 1, rect.x1, rect.y1 + 3)
    page.insert_textbox(padded, text, fontsize=min_size, fontname=fontname, color=color, align=align)
    return min_size


def _format_updated_excel_value(val, inferred_type: str, currency: str) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, (int, float)):
        if inferred_type == "percent":
            return f"{val * 100.0:.2f}%"
        if inferred_type == "currency":
            prefix = f"{currency} " if currency and len(currency) > 1 else (currency or "$")
            return f"{prefix}{val:,.2f}"
        if inferred_type == "integer" and float(val).is_integer():
            return str(int(val))
        return f"{val:g}"
    text = str(val)
    if text.startswith("'") and len(text) > 1 and text[1] in "=+-@":
        text = text[1:]
    return text


def handle_table_bridge_apply(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    pdf_src = next((p for p in sources if p.suffix.lower() == ".pdf"), None)
    data_src = next((p for p in sources if p.suffix.lower() in (".xlsx", ".json")), None)
    if pdf_src is None or data_src is None:
        raise ProcessingError("Suba primero el PDF original y luego el archivo .xlsx o .json editado.", 400)

    password = str(options.get("password", ""))
    edits_by_page: dict[int, list[dict]] = {}

    if data_src.suffix.lower() == ".xlsx":
        try:
            wb = openpyxl.load_workbook(data_src, data_only=True)
        except Exception:
            raise ProcessingError("No se pudo abrir el libro Excel editado.") from None
        if "_EVA_COORDS" not in wb.sheetnames:
            raise ProcessingError("El libro Excel no contiene la hoja de coordenadas _EVA_COORDS generada por EVA.")
        coord_ws = wb["_EVA_COORDS"]
        rows_iter = list(coord_ws.iter_rows(values_only=True))
        if len(rows_iter) < 2:
            raise ProcessingError("La hoja _EVA_COORDS esta vacia.")
        for meta_row in rows_iter[1:]:
            sheet_name, _, pno, r_idx, c_idx, _, bbox_json, orig_text, inferred_type, currency, font, fsize, color = meta_row[:13]
            if sheet_name not in wb.sheetnames:
                continue
            cur_val = wb[sheet_name].cell(row=int(r_idx), column=int(c_idx)).value
            orig_cmp = str(orig_text or "")
            if orig_cmp.startswith("'") and len(orig_cmp) > 1 and orig_cmp[1] in "=+-@":
                orig_cmp = orig_cmp[1:]
            new_str = _format_updated_excel_value(cur_val, str(inferred_type or "text"), str(currency or ""))
            # Comparacion numerica tolerante si ambas son cifras
            same = new_str == orig_cmp
            if not same and isinstance(cur_val, (int, float)):
                orig_parsed = _parse_typed_cell(orig_cmp)
                if isinstance(orig_parsed["value"], (int, float)) and abs(float(cur_val) - float(orig_parsed["value"])) < 1e-6:
                    same = True
            if same:
                continue
            edits_by_page.setdefault(int(pno), []).append({
                "bbox": json.loads(bbox_json),
                "text": new_str,
                "font": str(font or "Arial"),
                "size": float(fsize or 10.0),
                "color": str(color or "#000000"),
            })
    else:
        try:
            payload = json.loads(data_src.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProcessingError("JSON tabular no valido.") from None
        updates = payload.get("updates") if isinstance(payload, dict) else payload
        if not isinstance(updates, list):
            raise ProcessingError("El JSON debe incluir una lista de cambios en 'updates'.")
        for u in updates:
            if not isinstance(u, dict) or "page" not in u or "bbox" not in u or "text" not in u:
                raise ProcessingError("Cada actualizacion requiere page, bbox y text.", 400)
            edits_by_page.setdefault(int(u["page"]), []).append({
                "bbox": [float(v) for v in u["bbox"]],
                "text": clean_text(str(u["text"])),
                "font": str(u.get("font", "Arial")),
                "size": float(u.get("size", 10.0)),
                "color": str(u.get("color", "#000000")),
            })

    if not any(edits_by_page.values()):
        raise ProcessingError("No se detectaron celdas modificadas para aplicar al PDF.")

    out_pdf = folder / "tablas_actualizadas.pdf"
    applied = 0
    with open_pdf(pdf_src, password, config["max_pages"]) as doc:
        for pno, cell_edits in edits_by_page.items():
            if not 1 <= pno <= len(doc):
                raise ProcessingError(f"Pagina {pno} fuera de rango.")
            page = doc[pno - 1]
            if page.rotation:
                raise ProcessingError("Quite primero la rotacion de la pagina antes de actualizar celdas.")
            for ed in cell_edits:
                rect = pdf.Rect(ed["bbox"]) & page.rect
                if rect.is_empty:
                    continue
                page.add_redact_annot(rect, fill=False, cross_out=False)
            page.apply_redactions(images=0, graphics=0, text=pdf.PDF_REDACT_TEXT_REMOVE)
            for ed in cell_edits:
                rect = pdf.Rect(ed["bbox"]) & page.rect
                if rect.is_empty:
                    continue
                font_code = resolve_font(page, ed["font"])
                color = parse_color(ed["color"])
                _fit_text_in_box(page, rect, ed["text"], font_code, ed["size"], color)
                applied += 1
        save(doc, out_pdf, clean=True)

    return {
        "file": out_pdf.name,
        "notice": f"Puente tabular aplicado: {applied} celdas reinsertadas sin deformar la tabla.",
    }


def _compile_rule_matcher(rule: dict):
    kind = str(rule.get("kind", "regex")).lower()
    if kind == "literal":
        pat = str(rule.get("pattern") or rule.get("find") or "")
        if not pat:
            raise ProcessingError("Regla literal sin texto a buscar.", 400)
        flags = re.IGNORECASE if rule.get("case_insensitive", False) else 0
        regex = re.compile(re.escape(pat), flags)
        repl = str(rule.get("replacement", rule.get("replace", "")))
        return kind, regex, lambda m: repl

    if kind == "regex":
        pat = str(rule.get("pattern") or rule.get("find") or "")
        if not pat or len(pat) > 300:
            raise ProcessingError("Patron regex vacio o demasiado largo.", 400)
        flags = re.IGNORECASE if rule.get("case_insensitive", False) else 0
        try:
            regex = re.compile(pat, flags)
        except re.error as err:
            raise ProcessingError(f"Regex invalida: {err}", 400) from None
        repl = str(rule.get("replacement", rule.get("replace", "")))
        def _apply_rx(m):
            # Admite sintaxis $1/$2 ademas de \1/\2
            norm_repl = re.sub(r"\$(\d+)", r"\\\1", repl)
            try:
                return m.expand(norm_repl)
            except re.error:
                return repl
        return kind, regex, _apply_rx

    if kind == "date":
        pat = str(rule.get("pattern") or r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b")
        target_fmt = str(rule.get("target_format", "%Y-%m-%d"))
        if target_fmt not in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
            target_fmt = "%Y-%m-%d"
        regex = re.compile(pat)
        def _apply_date(m):
            txt = m.group(0)
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%y"):
                try:
                    return datetime.strptime(txt, fmt).strftime(target_fmt)
                except ValueError:
                    continue
            return txt
        return kind, regex, _apply_date

    if kind == "currency":
        rate = _parse_number(rule, "rate", 1.0, 0.00001, 100000.0)
        decimals = int(_parse_number(rule, "decimals", 2, 0, 6))
        target_cur = str(rule.get("target_currency", "$"))
        pat = str(
            rule.get("pattern")
            or r"(?:(USD|EUR|COP|MXN|GBP|\$|€|£)\s*([+-]?\d[\d.,]*)|([+-]?\d[\d.,]*)\s*(USD|EUR|COP|MXN|GBP))"
        )
        try:
            regex = re.compile(pat, re.IGNORECASE)
        except re.error as err:
            raise ProcessingError(f"Patron de divisa invalido: {err}", 400) from None
        def _apply_cur(m):
            raw_num = next((g for g in m.groups() if g and re.search(r"\d", g)), m.group(0))
            val = _to_float_locale(raw_num)
            if val is None:
                return m.group(0)
            scaled = val * rate
            formatted = f"{scaled:,.{decimals}f}"
            if len(target_cur) <= 1:
                return f"{target_cur}{formatted}"
            return f"{target_cur} {formatted}"
        return kind, regex, _apply_cur

    raise ProcessingError(f"Tipo de regla semantico desconocido: {kind}", 400)


def handle_semantic_replace(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    # Admite ejecucion por lotes delegando a process_batch cuando hay varios PDF
    if len(sources) > 1:
        from pdf_engine import process_batch

        return process_batch(operation, sources, options, folder, config, root)

    source = sources[0]
    password = str(options.get("password", ""))
    raw_rules = options.get("rules")
    if not raw_rules and options.get("find"):
        raw_rules = [{
            "kind": "regex" if options.get("use_regex", False) else "literal",
            "pattern": options["find"],
            "replacement": options.get("replace", ""),
            "case_insensitive": bool(options.get("case_insensitive", False)),
        }]
    if not isinstance(raw_rules, list) or not 1 <= len(raw_rules) <= 40:
        raise ProcessingError("Configure entre 1 y 40 reglas de reemplazo.", 400)

    compiled = [_compile_rule_matcher(r) for r in raw_rules]
    dry_run = bool(options.get("dry_run", False))
    auto_fit = bool(options.get("auto_fit", True))

    changes_preview: list[dict] = []
    replacements = 0
    overflow_warnings = 0

    with open_pdf(source, password, config["max_pages"]) as doc:
        selected = pages_from(options.get("pages", ""), len(doc))
        for pno in selected:
            page = doc[pno]
            if page.rotation and not dry_run:
                raise ProcessingError("Quite la rotacion de la pagina antes de reemplazar texto.")
            page_ops: list[dict] = []
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        orig = span.get("text", "")
                        if not orig.strip():
                            continue
                        updated = orig
                        for _, regex, repl_fn in compiled:
                            updated = regex.sub(repl_fn, updated)
                        if updated != orig:
                            sb = pdf.Rect(span["bbox"])
                            page_ops.append({
                                "page": pno + 1,
                                "bbox": [round(float(v), 2) for v in sb],
                                "before": orig,
                                "after": updated,
                                "font": str(span.get("font", "Helvetica")).split("+")[-1],
                                "size": float(span.get("size", 10.0)),
                                "color": f"#{int(span.get('color', 0)) & 0xFFFFFF:06x}",
                            })
            if dry_run:
                changes_preview.extend(page_ops)
                replacements += len(page_ops)
                continue

            if not page_ops:
                continue
            for item in page_ops:
                rect = pdf.Rect(item["bbox"])
                page.add_redact_annot(rect, fill=False, cross_out=False)
            page.apply_redactions(images=0, graphics=0, text=pdf.PDF_REDACT_TEXT_REMOVE)
            for item in page_ops:
                rect = pdf.Rect(item["bbox"])
                # Expandir ligeramente en ancho si queda margen seguro a la derecha sin invadir margenes
                font_code = resolve_font(page, item["font"])
                color = parse_color(item["color"])
                text_w = pdf.get_text_length(item["after"], fontname=font_code, fontsize=item["size"])
                draw_rect = pdf.Rect(rect.x0, rect.y0 - 1, max(rect.x1, min(page.rect.x1 - 10, rect.x0 + text_w + 4)), rect.y1 + 3)
                if auto_fit:
                    used = _fit_text_in_box(page, draw_rect, item["after"], font_code, item["size"], color)
                    if used < item["size"] - 1.5:
                        overflow_warnings += 1
                else:
                    res = page.insert_textbox(draw_rect, item["after"], fontsize=item["size"], fontname=font_code, color=color)
                    if res < 0:
                        overflow_warnings += 1
                replacements += 1

        if dry_run:
            preview_path = folder / "vista_previa_reemplazo.json"
            preview_path.write_text(
                json.dumps({"dry_run": True, "matches": len(changes_preview), "changes": changes_preview[:2000]},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return {
                "file": preview_path.name,
                "notice": f"Vista previa semantica: {len(changes_preview)} reemplazos potenciales (sin modificar PDF).",
            }

        out_pdf = folder / "reemplazo_semantico.pdf"
        save(doc, out_pdf, clean=True)

    return {
        "file": out_pdf.name,
        "notice": f"Reemplazo semantico aplicado: {replacements} fragmentos actualizados (ajustes de escala: {overflow_warnings}).",
    }
