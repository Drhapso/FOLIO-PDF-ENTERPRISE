from __future__ import annotations

import difflib
import io
import json
import math
import textwrap
import zipfile
from contextlib import ExitStack
from html.parser import HTMLParser
from pathlib import Path

import pikepdf
import pymupdf as pdf
from PIL import Image, ImageChops

from pdf_engine import ProcessingError, check_size, integer, open_pdf, pages_from, render, save

EXTENDED_OPERATIONS = {
    "extract_pages", "delete_pages", "number_pages", "extract_images", "crop",
    "resize", "nup", "overlay", "compare", "remove_metadata", "grayscale",
    "rasterize", "flatten", "repair", "web_optimize", "blank_report",
    "remove_blank", "form_fields", "fill_form", "dossier", "stamp",
    "html_to_pdf", "pdf_to_svg",
}
MULTIPLE = {"overlay", "compare", "dossier", "stamp"}


def number(options: dict, key: str, default: float, low: float, high: float) -> float:
    value = options.get(key, default)
    if isinstance(value, bool):
        raise ProcessingError(f"Valor no valido: {key}.")
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ProcessingError(f"Valor no valido: {key}.") from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ProcessingError(f"{key}: valor fuera de rango ({low}-{high}).")
    return result


def box(options: dict, page: pdf.Page) -> pdf.Rect:
    x = number(options, "x", 10, 0, 99) / 100
    y = number(options, "y", 10, 0, 99) / 100
    w = number(options, "width", 80, 0.1, 100) / 100
    h = number(options, "height", 80, 0.1, 100) / 100
    if x + w > 1.00001 or y + h > 1.00001:
        raise ProcessingError("La caja debe quedar dentro de la pagina.")
    return pdf.Rect(x * page.rect.width, y * page.rect.height,
                    (x + w) * page.rect.width, (y + h) * page.rect.height)


def unrotated(page: pdf.Page):
    if page.rotation:
        raise ProcessingError("Quite la rotacion antes de recortar o insertar una firma/imagen.")


def report_pdf(lines: list[str], path: Path, config: dict):
    with pdf.open() as doc:
        y = 0
        for line in lines:
            # Fuente base WinAnsi: sustituye solo caracteres no representables en el informe.
            text = str(line).encode("cp1252", errors="replace").decode("cp1252")
            for fragment in textwrap.wrap(text, 95, replace_whitespace=False) or [""]:
                if not y or y > 790:
                    if config["max_pages"] and len(doc) >= config["max_pages"]:
                        raise ProcessingError("El informe excede el limite de paginas.")
                    page = doc.new_page()
                    y = 45
                page.insert_text((35, y), fragment, fontsize=9)
                y += 13
        if not len(doc):
            doc.new_page()
        save(doc, path)


class LocalHTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object", "svg"}:
            self.blocked += 1
        if not self.blocked and tag in {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object", "svg"} and self.blocked:
            self.blocked -= 1
        if not self.blocked and tag in {"p", "div", "tr", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def blank_candidates(doc: pdf.Document, selected: list[int], config: dict) -> list[int]:
    candidates = []
    for index in selected:
        page = doc[index]
        if page.get_text().strip() or list(page.annots() or []) or list(page.widgets() or []):
            continue
        pix = render(page, 72, config)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
        hist = image.histogram()
        dark = sum(hist[:245]) / (image.width * image.height)
        if dark < 0.00005:
            candidates.append(index + 1)
    return candidates


def process_extended(operation: str, sources: list[Path], options: dict,
                     folder: Path, config: dict) -> dict:
    if operation not in EXTENDED_OPERATIONS:
        raise ProcessingError("Herramienta desconocida.", 404)
    if operation == "html_to_pdf":
        if len(sources) != 1 or sources[0].suffix not in {".html", ".htm"}:
            raise ProcessingError("Seleccione un archivo HTML local.")
        if sources[0].stat().st_size > 2 * 1024 * 1024:
            raise ProcessingError("El HTML local no puede superar 2 MB.", 413)
        try:
            source = sources[0].read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raise ProcessingError("Guarde el HTML con codificacion UTF-8.") from None
        parser = LocalHTMLText()
        parser.feed(source)
        text = "".join(parser.parts)
        if not text.strip():
            raise ProcessingError("El HTML no contiene texto legible.")
        output = folder / "texto-html.pdf"
        report_pdf(text.splitlines(), output, config)
        check_size(output, config)
        return {"file": output.name, "notice": "Solo texto HTML local: sin scripts, imagenes, CSS ni recursos externos; no conserva diseno."}
    if operation in {"overlay", "compare", "stamp"} and len(sources) != 2:
        raise ProcessingError("Esta herramienta requiere exactamente dos archivos en el orden indicado.")
    if operation not in MULTIPLE and len(sources) != 1:
        raise ProcessingError("Esta herramienta requiere un solo PDF.")
    if operation == "stamp":
        if sources[0].suffix != ".pdf" or sources[1].suffix not in {".png", ".jpg", ".jpeg"}:
            raise ProcessingError("Primero seleccione el PDF y luego una imagen PNG/JPEG.")
        pdf_sources = sources[:1]
    else:
        if any(path.suffix != ".pdf" for path in sources):
            raise ProcessingError("Esta herramienta solo admite PDF.")
        pdf_sources = sources
    output = folder / "resultado.pdf"
    notice = ""
    if operation in {"repair", "web_optimize"}:
        try:
            with pikepdf.open(sources[0], password=options.get("password", ""),
                              attempt_recovery=operation == "repair", suppress_warnings=True) as doc:
                if not len(doc.pages) or (config["max_pages"] and len(doc.pages) > config["max_pages"]):
                    raise ProcessingError("Numero de paginas fuera del limite.")
                doc.save(output, linearize=operation == "web_optimize",
                         object_stream_mode=pikepdf.ObjectStreamMode.generate)
            with pikepdf.open(output) as verified:
                problems = verified.check_pdf_syntax()
                if operation == "web_optimize" and not verified.is_linearized:
                    raise ProcessingError("No se pudo verificar la linealizacion.", 500)
                if problems:
                    raise ProcessingError("Persisten inconsistencias estructurales; no se entrega como reparado.")
        except (pikepdf.PdfError, pikepdf.PasswordError):
            raise ProcessingError("No se pudo abrir o reparar el PDF. Verifique archivo y clave.") from None
        notice = ("Estructura reescrita y verificada. No recupera contenido perdido ni certifica integridad visual."
                  if operation == "repair" else "PDF linealizado para lectura progresiva; no implica menor peso.")
    else:
        with ExitStack() as stack:
            docs = [stack.enter_context(open_pdf(path, options.get("password", ""), config["max_pages"]))
                    for path in pdf_sources]
            if config["max_pages"] and sum(map(len, docs)) > config["max_pages"]:
                raise ProcessingError("La suma de paginas excede el limite.")
            doc = docs[0]
            selected = pages_from(options.get("pages", ""), len(doc))
            if operation in {"extract_pages", "delete_pages"}:
                if operation == "delete_pages":
                    if not options.get("pages", "").strip():
                        raise ProcessingError("Indique expresamente las paginas que desea eliminar.")
                    selected = [n for n in range(len(doc)) if n not in selected]
                    if not selected:
                        raise ProcessingError("No se pueden eliminar todas las paginas.")
                doc.select(selected)
                save(doc, output)
            elif operation == "number_pages":
                start = integer(options.get("start", 1), 0, 1000000, "Numero inicial")
                size = integer(options.get("size", 11), 6, 36, "Tamano")
                position = options.get("position", "bottom")
                if position not in {"top", "bottom"}:
                    raise ProcessingError("Posicion no valida.")
                for offset, index in enumerate(selected):
                    page = doc[index]
                    unrotated(page)
                    y = 12 if position == "top" else page.rect.height - size * 2 - 12
                    rect = pdf.Rect(10, y, page.rect.width - 10, y + size * 2)
                    label = f"{start + offset} / {start + len(selected) - 1}"
                    if page.insert_textbox(rect, label, fontsize=size, align=1) < 0:
                        raise ProcessingError("No cabe la numeracion en una pagina.")
                save(doc, output)
            elif operation == "extract_images":
                output = folder / "imagenes-originales.zip"
                seen = set()
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                    for index in selected:
                        for item in doc[index].get_images(full=True):
                            xref, mask = item[:2]
                            if not xref or xref in seen:
                                continue
                            seen.add(xref)
                            # Reconstruye la transparencia, no duplica la mascara como otra imagen.
                            if mask:
                                pix = pdf.Pixmap(doc, xref)
                                if pix.width * pix.height > config["max_render_pixels"]:
                                    raise ProcessingError("Imagen incrustada demasiado grande.")
                                if pix.colorspace and pix.colorspace.n not in (1, 3):
                                    pix = pdf.Pixmap(pdf.csRGB, pix)
                                if pix.alpha:
                                    pix = pdf.Pixmap(pix, 0)
                                image = pdf.Pixmap(pix, pdf.Pixmap(doc, mask)).tobytes("png")
                                extension = "png"
                            else:
                                image_info = doc.extract_image(xref)
                                if image_info["width"] * image_info["height"] > config["max_render_pixels"]:
                                    raise ProcessingError("Imagen incrustada demasiado grande.")
                                image, extension = image_info["image"], image_info["ext"]
                            archive.writestr(f"imagen-{len(seen):03}.{extension}", image)
                            check_size(output, config)
                if not seen:
                    raise ProcessingError("No se encontraron imagenes incrustadas; pruebe PDF a imagenes.")
                notice = "Imagenes incrustadas unicas; no extrae trazados vectoriales ni garantiza reconstruir fragmentos."
            elif operation == "pdf_to_svg":
                output = folder / "paginas-svg.zip"
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                    for index in selected:
                        archive.writestr(f"pagina-{index + 1:03}.svg", doc[index].get_svg_image(text_as_path=True))
                        check_size(output, config)
                notice = "SVG por pagina, texto como trazados; no conserva formularios ni enlaces."
            elif operation == "crop":
                for index in selected:
                    page = doc[index]
                    unrotated(page)
                    crop = box(options, page)
                    crop += (page.cropbox.x0, page.cropbox.y0, page.cropbox.x0, page.cropbox.y0)
                    page.set_cropbox(crop)
                save(doc, output)
                notice = "Recorte visual: el contenido fuera de la caja puede seguir en el archivo. No es censura."
            elif operation in {"resize", "nup"}:
                sizes = {"a4": (595.276, 841.89), "letter": (612, 792), "legal": (612, 1008)}
                paper = options.get("paper", "a4")
                if paper not in sizes:
                    raise ProcessingError("Tamano de papel no valido.")
                width, height = sizes[paper]
                count = 1 if operation == "resize" else integer(options.get("per_sheet", 4), 2, 4, "Paginas por hoja")
                if count not in (1, 2, 4):
                    raise ProcessingError("Seleccione 2 o 4 paginas por hoja.")
                if count == 2:
                    width, height = height, width
                cols, rows = ((1, 1) if count == 1 else (2, 1) if count == 2 else (2, 2))
                with pdf.open() as arranged:
                    for offset, index in enumerate(selected):
                        if offset % count == 0:
                            target = arranged.new_page(width=width, height=height)
                        slot = offset % count
                        col, row = slot % cols, slot // cols
                        rect = pdf.Rect(col * width / cols + 12, row * height / rows + 12,
                                        (col + 1) * width / cols - 12, (row + 1) * height / rows - 12)
                        if doc[index].get_contents():
                            target.show_pdf_page(rect, doc, index)
                    save(arranged, output)
                notice = "Contenido visual vectorial ajustado; no conserva formularios, anotaciones ni enlaces interactivos."
            elif operation == "overlay":
                layer = docs[1]
                if len(layer) not in (1, len(doc)):
                    raise ProcessingError("La plantilla debe tener una pagina o tantas paginas como el documento.")
                for index in selected:
                    page = doc[index]
                    if layer[index if len(layer) > 1 else 0].get_contents():
                        page.show_pdf_page(page.rect, layer, index if len(layer) > 1 else 0,
                                           overlay=options.get("layer", "foreground") != "background")
                save(doc, output)
            elif operation == "compare":
                output = compare_documents(docs[0], docs[1], folder, config)
                notice = "ZIP con diferencias de texto y mapas visuales. No es una certificacion de equivalencia."
            elif operation == "remove_metadata":
                doc.set_metadata({})
                doc.del_xml_metadata()
                save(doc, output)
                notice = "Elimina Info y XMP del documento; no elimina texto, anotaciones, adjuntos o datos personales del contenido."
            elif operation in {"grayscale", "rasterize"}:
                dpi = integer(options.get("dpi", 144), 72, 300, "DPI")
                with pdf.open() as result:
                    for index in selected:
                        page = doc[index]
                        pix = render(page, dpi, config)
                        if operation == "grayscale":
                            pix = pdf.Pixmap(pdf.csGRAY, pix)
                        target = result.new_page(width=page.rect.width, height=page.rect.height)
                        target.insert_image(target.rect, stream=pix.tobytes("png"))
                    save(result, output)
                notice = "Paginas rasterizadas: sin texto seleccionable, enlaces, formularios ni estructura accesible."
            elif operation == "flatten":
                doc.bake(annots=True, widgets=True)
                save(doc, output)
                notice = "Apariencia de anotaciones y campos integrada; verifique visualmente el resultado."
            elif operation in {"blank_report", "remove_blank"}:
                candidates = blank_candidates(doc, selected, config)
                if operation == "blank_report":
                    output = folder / "paginas-en-blanco.json"
                    output.write_text(json.dumps({
                        "candidates": candidates, "pages": len(doc),
                        "warning": "Heuristica conservadora, no garantia. Confirme visualmente antes de eliminar.",
                    }), encoding="utf-8")
                else:
                    if not options.get("pages", "").strip():
                        raise ProcessingError("Indique las paginas confirmadas tras revisar el informe.")
                    if set(index + 1 for index in selected) - set(candidates):
                        raise ProcessingError("Una pagina seleccionada no supera la comprobacion conservadora de blanco.")
                    remaining = [index for index in range(len(doc)) if index not in selected]
                    if not remaining:
                        raise ProcessingError("No se pueden eliminar todas las paginas.")
                    doc.select(remaining)
                    save(doc, output)
            elif operation in {"form_fields", "fill_form"}:
                fields = []
                names = set()
                payload = options.get("fields", {})
                if operation == "fill_form" and (not isinstance(payload, dict) or not payload or len(payload) > 200):
                    raise ProcessingError("Indique campos como un objeto JSON no vacio (maximo 200).")
                for page_index, page in enumerate(doc):
                    for widget in page.widgets() or []:
                        names.add(widget.field_name)
                        fields.append({"page": page_index + 1, "name": widget.field_name,
                                       "type": widget.field_type_string, "value": widget.field_value})
                        if operation == "fill_form" and widget.field_name in payload:
                            if widget.field_flags & pdf.PDF_FIELD_IS_READ_ONLY:
                                raise ProcessingError("Uno de los campos es de solo lectura.")
                            if widget.field_type not in (pdf.PDF_WIDGET_TYPE_TEXT, pdf.PDF_WIDGET_TYPE_CHECKBOX,
                                                         pdf.PDF_WIDGET_TYPE_COMBOBOX, pdf.PDF_WIDGET_TYPE_LISTBOX):
                                raise ProcessingError("Tipo de campo no admitido (firmas/radio/XFA).")
                            value = payload[widget.field_name]
                            if not isinstance(value, str) or len(value) > 4000:
                                raise ProcessingError("Los valores de campos deben ser textos de hasta 4000 caracteres.")
                            if widget.field_type == pdf.PDF_WIDGET_TYPE_CHECKBOX and value not in ("Off", widget.on_state()):
                                raise ProcessingError(f"Casilla: use Off o {widget.on_state()}.")
                            if widget.choice_values and value not in widget.choice_values:
                                raise ProcessingError("Valor no disponible en la lista del formulario.")
                            if widget.text_maxlen and len(value) > widget.text_maxlen:
                                raise ProcessingError("Texto demasiado largo para el campo.")
                            widget.field_value = value
                            widget.update()
                if operation == "form_fields":
                    if not fields:
                        raise ProcessingError("No hay campos AcroForm compatibles.")
                    output = folder / "campos.json"
                    output.write_text(json.dumps(fields), encoding="utf-8")
                else:
                    if payload.keys() - names:
                        raise ProcessingError("Se indicaron nombres de campos inexistentes.")
                    save(doc, output)
            elif operation == "dossier":
                include_cover = options.get("include_cover", True)
                if not isinstance(include_cover, bool):
                    raise ProcessingError("Indique si desea incluir la portada con un valor booleano.")
                title = options.get("text", "Expediente documental")
                if include_cover and (not isinstance(title, str) or not title.strip() or len(title) > 100):
                    raise ProcessingError("Titulo de expediente no valido (1-100 caracteres).")
                if config["max_pages"] and sum(map(len, docs)) + int(include_cover) > config["max_pages"]:
                    raise ProcessingError("El expediente excede el limite de paginas.")
                with pdf.open() as combined:
                    if include_cover:
                        page = combined.new_page()
                        if page.insert_textbox(pdf.Rect(50, 100, 545, 500), title, fontsize=24, align=1) < 0:
                            raise ProcessingError("El titulo no cabe en la portada.")
                    for document in docs:
                        combined.insert_pdf(document)
                    save(combined, output)
            elif operation == "stamp":
                with Image.open(sources[1]) as image:
                    if image.width * image.height > config["max_render_pixels"]:
                        raise ProcessingError("Imagen demasiado grande.")
                    image = image.convert("RGBA")
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                for index in selected:
                    page = doc[index]
                    unrotated(page)
                    page.insert_image(box(options, page), stream=buffer.getvalue(), overlay=True)
                save(doc, output)
                notice = "Imagen o firma visual, no firma digital con certificado ni prueba de identidad."
    check_size(output, config)
    return {"file": output.name, "notice": notice}


def compare_documents(left: pdf.Document, right: pdf.Document, folder: Path, config: dict) -> Path:
    output = folder / "comparacion.zip"
    lines = ["COMPARACION DE DOCUMENTOS", "Los mapas comparan apariencia a 96 DPI; revise tambien las diferencias de texto."]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for index in range(max(len(left), len(right))):
            a = left[index] if index < len(left) else None
            b = right[index] if index < len(right) else None
            text_a, text_b = (a.get_text(sort=True) if a else ""), (b.get_text(sort=True) if b else "")
            delta = "\n".join(difflib.unified_diff(text_a.splitlines(), text_b.splitlines(),
                                                  fromfile="original", tofile="comparado", lineterm=""))
            archive.writestr(f"pagina-{index + 1:03}-texto.diff", delta or "Sin diferencias de texto extraido.")
            rendered = []
            for page in (a, b):
                if page is None:
                    rendered.append(None)
                else:
                    pix = render(page, 96, config)
                    rendered.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            width = max(image.width for image in rendered if image is not None)
            height = max(image.height for image in rendered if image is not None)
            if width * height > config["max_render_pixels"]:
                raise ProcessingError("Comparacion visual demasiado grande.")
            canvases = []
            for image in rendered:
                canvas = Image.new("RGB", (width, height), "white")
                if image is not None:
                    canvas.paste(image, (0, 0))
                canvases.append(canvas)
            difference = ImageChops.difference(*canvases)
            changed = difference.getbbox() is not None or (a is None) != (b is None)
            lines.append(f"Pagina {index + 1}: {'CAMBIOS VISUALES' if changed else 'sin cambios visuales'}; "
                         f"{'cambios de texto' if delta else 'sin cambios de texto'}.")
            buffer = io.BytesIO()
            difference.save(buffer, format="PNG")
            archive.writestr(f"pagina-{index + 1:03}-diferencias.png", buffer.getvalue())
            check_size(output, config)
        report = folder / "informe.pdf"
        report_pdf(lines, report, config)
        archive.write(report, "informe.pdf")
        archive.writestr("LEAME.txt", "Mapas: negro = sin diferencias; colores = diferencias. "
                         "Cambios de posicion tambien producen diferencias. No compara semantica ni firmas.")
    return output
