from __future__ import annotations

import html
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pymupdf as pdf
from PIL import Image, ImageOps

from pdf_engine import ProcessingError, check_size, open_pdf, save

ADVANCED_OPERATIONS = {"heic_to_jpg", "epub_to_pdf", "pdf_to_epub", "verify_signatures"}


def preprocess_scan(pix: pdf.Pixmap, mode: str, dpi: int, max_pixels: int) -> pdf.Pixmap:
    if mode not in {"none", "deskew", "clean"}:
        raise ProcessingError("Preprocesamiento OCR no valido.")
    if mode == "none":
        return pix
    import cv2
    import numpy as np

    cv2.setNumThreads(1)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    scale = min(1, 1200 / max(gray.shape))
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    _, mask = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    angle = 0.0
    best = 0.0
    center = (mask.shape[1] / 2, mask.shape[0] / 2)
    # Proyeccion horizontal acotada: no adivina orientaciones de 90/180 grados.
    for step in range(-10, 11):
        candidate = step / 2
        matrix = cv2.getRotationMatrix2D(center, candidate, 1)
        rotated = cv2.warpAffine(mask, matrix, (mask.shape[1], mask.shape[0]))
        score = float(np.var(rotated.sum(axis=1)))
        if score > best:
            best, angle = score, candidate
    if angle:
        height, width = gray.shape
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
        cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
        new_width = int(width * cosine + height * sine + 1)
        new_height = int(height * cosine + width * sine + 1)
        if new_width * new_height > max_pixels:
            raise ProcessingError("El enderezado excede el limite de pixeles. Reduzca los DPI.")
        matrix[0, 2] += (new_width - width) / 2
        matrix[1, 2] += (new_height - height) / 2
        gray = cv2.warpAffine(gray, matrix, (new_width, new_height), borderValue=255)
    if mode == "clean":
        gray = cv2.adaptiveThreshold(cv2.medianBlur(gray, 3), 255,
                                     cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
    buffer = io.BytesIO()
    Image.fromarray(gray).convert("RGB").save(buffer, "PNG")
    result = pdf.Pixmap(buffer.getvalue())
    result.set_dpi(dpi, dpi)
    return result


def check_epub(source: Path, config: dict):
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(item.file_size for item in entries) > config["max_upload_mb"] * 1024 * 1024:
            raise ProcessingError("El EPUB descomprimido excede los limites.", 413)
        if any(item.flag_bits & 1 for item in entries) or "META-INF/encryption.xml" in archive.namelist():
            raise ProcessingError("No se admiten EPUB cifrados o con DRM.")
        if len({item.filename for item in entries}) != len(entries):
            raise ProcessingError("El EPUB contiene entradas duplicadas.")
        if ("mimetype" not in archive.namelist() or archive.getinfo("mimetype").file_size != 20
                or archive.read("mimetype") != b"application/epub+zip"):
            raise ProcessingError("El archivo no es un EPUB valido.")


def write_epub(doc: pdf.Document, output: Path):
    chapters = [page.get_text(sort=True) for page in doc]
    if not any(text.strip() for text in chapters):
        raise ProcessingError("No hay texto extraible. Ejecute OCR antes de crear el EPUB.")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml",
                         '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                         '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                         '</rootfiles></container>')
        manifest, spine, links = [], [], []
        for index, text in enumerate(chapters, 1):
            filename = f"pagina-{index:03}.xhtml"
            paragraphs = "".join(f"<p>{html.escape(line)}</p>" for line in text.splitlines())
            archive.writestr(f"OEBPS/{filename}",
                             f'<html xmlns="http://www.w3.org/1999/xhtml" lang="es"><head><title>Pagina {index}</title>'
                             f'</head><body><h1>Pagina {index}</h1>{paragraphs}</body></html>')
            manifest.append(f'<item id="p{index}" href="{filename}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="p{index}"/>')
            links.append(f'<li><a href="{filename}">Pagina {index}</a></li>')
        archive.writestr("OEBPS/nav.xhtml",
                         '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
                         '<head><title>Indice</title></head><body><nav epub:type="toc"><ol>'
                         + "".join(links) + '</ol></nav></body></html>')
        identifier = f"urn:uuid:{uuid4()}"
        modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        archive.writestr("OEBPS/content.opf",
                         '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
                         f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">{identifier}</dc:identifier>'
                         '<dc:title>Documento</dc:title><dc:language>es</dc:language>'
                         f'<meta property="dcterms:modified">{modified}</meta></metadata><manifest>'
                         '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
                         + "".join(manifest) + '</manifest><spine>' + "".join(spine) + '</spine></package>')


def signature_report(source: Path) -> dict:
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.pdf_utils.misc import PdfReadError
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko.sign.validation.errors import SignatureValidationError
    from pyhanko_certvalidator import ValidationContext

    results = []
    try:
        with source.open("rb") as stream:
            reader = PdfFileReader(stream)
            if reader.security_handler is not None:
                raise ProcessingError("La comprobacion de firmas no admite PDF cifrados; no los reescriba para comprobarlos.")
            for signature in reader.embedded_signatures:
                context = ValidationContext(trust_roots=[], allow_fetching=False)
                status = validate_pdf_signature(signature, signer_validation_context=context,
                                                ts_validation_context=context)
                results.append({
                    "campo": signature.field_name,
                    "integridad_bytes_firmados": bool(status.intact),
                    "firma_criptografica_correcta": bool(status.valid),
                    "cobertura": status.coverage.name if status.coverage is not None else "DESCONOCIDA",
                    "cambios": status.modification_level.name if status.modification_level is not None else "DESCONOCIDOS",
                    "confianza_identidad": "NO_EVALUADA",
                    "revocacion": "NO_EVALUADA",
                })
    except (PdfReadError, SignatureValidationError, ValueError):
        raise ProcessingError("No se pudieron comprobar las firmas: estructura o algoritmo no compatible.") from None
    return {"modo": "offline", "firmas": results,
            "advertencia": "No certifica identidad, confianza, revocacion ni validez legal. Sin OCSP, CRL ni TSA de red. "
                           "Una firma correcta puede cubrir solo una revision anterior; revise cobertura y cambios."}


def process_advanced(operation: str, sources: list[Path], options: dict, folder: Path, config: dict) -> dict:
    if len(sources) != 1:
        raise ProcessingError("Seleccione un solo archivo.")
    source = sources[0]
    notice = ""
    if operation == "heic_to_jpg":
        if source.suffix not in {".heic", ".heif"}:
            raise ProcessingError("Seleccione una imagen HEIC/HEIF.")
        from pillow_heif import register_heif_opener

        register_heif_opener()
        output = folder / "imagen.jpg"
        with Image.open(source) as image:
            if image.width * image.height > config["max_render_pixels"]:
                raise ProcessingError("Imagen demasiado grande.")
            if getattr(image, "n_frames", 1) != 1:
                raise ProcessingError("Use HEIC/HEIF de un solo fotograma.")
            rgba = ImageOps.exif_transpose(image).convert("RGBA")
            flat = Image.new("RGB", rgba.size, "white")
            flat.paste(rgba, mask=rgba.getchannel("A"))
            flat.save(output, "JPEG", quality=95)
        notice = "JPEG con perdida; no conserva profundidad HDR ni metadatos originales."
    elif operation == "epub_to_pdf":
        if source.suffix != ".epub":
            raise ProcessingError("Seleccione un EPUB sin DRM.")
        check_epub(source, config)
        output = folder / "libro.pdf"
        with pdf.open(source) as book:
            book.layout(width=595, height=842, fontsize=11)
            if not len(book) or (config["max_pages"] and len(book) > config["max_pages"]):
                raise ProcessingError("El EPUB paginado excede el limite de paginas.", 413)
            with pdf.open(stream=book.convert_to_pdf(), filetype="pdf") as converted:
                save(converted, output)
        notice = "EPUB refluido a A4. Revise tipografia, imagenes y saltos; no conserva interactividad."
    else:
        if source.suffix != ".pdf":
            raise ProcessingError("Seleccione un PDF.")
        with open_pdf(source, options.get("password", ""), config["max_pages"]) as doc:
            if operation == "pdf_to_epub":
                output = folder / "libro.epub"
                write_epub(doc, output)
                notice = "EPUB de texto por pagina, sin reconstruir diseno, tablas ni imagenes. Revise orden de lectura."
            elif operation == "verify_signatures":
                output = folder / "firmas.json"
                output.write_text(json.dumps(signature_report(source), ensure_ascii=True, indent=2), encoding="utf-8")
                notice = "Informe criptografico offline; NO certifica identidad, confianza, revocacion ni validez legal."
            else:
                raise ProcessingError("Herramienta desconocida.", 404)
    check_size(output, config)
    return {"file": output.name, "notice": notice}
