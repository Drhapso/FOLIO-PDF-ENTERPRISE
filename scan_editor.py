from __future__ import annotations

import pymupdf as pdf

from pdf_engine import ProcessingError, render
from settings import ROOT


def scan_blocks(page: pdf.Page, config: dict) -> list[dict]:
    models = ROOT / "models"
    language = config["ocr_language"]
    if not all((models / f"{name}.traineddata").is_file() for name in language.split("+")):
        raise ProcessingError("Faltan los modelos OCR locales para editar este escaneo.", 503)
    render(page, 200, config)
    textpage = page.get_textpage_ocr(language=language, dpi=200, full=True, tessdata=str(models))
    blocks = []
    for index, word in enumerate(page.get_text("words", textpage=textpage)):
        x0, y0, x1, y1, text = word[:5]
        rect = pdf.Rect(x0 - 0.8, y0 - 0.8, x1 + 0.8, y1 + 0.8) & page.rect
        blocks.append({
            "id": f"scan_{index}", "bbox": list(rect), "text": text, "source": "scan",
            "origin": [rect.x0, rect.y1 - 1], "font": "Helvetica",
            "size": max(6, min(72, (y1 - y0) * 0.8)),
            "color": "#000000", "bold": False, "italic": False, "lines_count": 1,
        })
    return blocks


def clean_scan_patch(page: pdf.Page, bbox: list, config: dict) -> bytes:
    """Reconstruye tinta aislada; rechaza bordes, lineas y fondos no uniformes."""
    import cv2
    import numpy as np

    cv2.setNumThreads(1)
    rect = pdf.Rect(bbox)
    if rect.is_empty or not page.rect.contains(rect):
        raise ProcessingError("La zona del escaneo debe estar dentro de la pagina.")
    if rect.width > 180 or rect.height > 40:
        raise ProcessingError("Zona escaneada demasiado grande. Edite una palabra a la vez.")
    pix = page.get_pixmap(matrix=pdf.Matrix(3, 3), clip=rect, colorspace=pdf.csRGB, alpha=False)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if min(gray.shape) < 8:
        raise ProcessingError("Zona escaneada demasiado pequena para reconstruir su fondo.")
    border = np.concatenate((rgb[:2].reshape(-1, 3), rgb[-2:].reshape(-1, 3),
                             rgb[:, :2].reshape(-1, 3), rgb[:, -2:].reshape(-1, 3)))
    background = np.median(border, axis=0)
    if np.percentile(np.max(np.abs(border.astype(float) - background), axis=1), 90) > 18:
        raise ProcessingError("Zona compleja: tinta o bordes tocan el limite. No se modifico el escaneo.")
    distance = np.max(np.abs(rgb.astype(float) - background), axis=2)
    mask = (distance > 28).astype(np.uint8) * 255
    density = np.count_nonzero(mask) / mask.size
    if not 0.005 < density < 0.40:
        raise ProcessingError("No se distingue texto aislado de un fondo uniforme en esta zona.")
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    for _, _, width, height, area in stats[1:count]:
        if ((width > gray.shape[1] * 0.75 and height <= 5)
                or (height > gray.shape[0] * 0.85 and width <= 4)
                or area > mask.size * 0.20):
            raise ProcessingError("Zona compleja: posible linea, sello o grafico. No se modifico el escaneo.")
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    if np.any(mask[:1]) or np.any(mask[-1:]) or np.any(mask[:, :1]) or np.any(mask[:, -1:]):
        raise ProcessingError("La tinta cruza el limite del fragmento. No se modifico el escaneo.")
    cleaned = cv2.inpaint(rgb, mask, 3, cv2.INPAINT_TELEA)
    remaining = np.max(np.abs(cleaned.astype(float) - background), axis=2)
    if np.count_nonzero((remaining > 28) & (mask > 0)) > max(2, np.count_nonzero(mask) * 0.01):
        raise ProcessingError("La reconstruccion dejo restos de tinta. No se modifico el escaneo.")
    image = pdf.Pixmap(pdf.csRGB, pix.width, pix.height, cleaned.tobytes(), False)
    return image.tobytes("png")


def editable_blocks(page: pdf.Page, config: dict) -> list[dict]:
    from acrobat_tools import extract_page_blocks

    traces = page.get_texttrace()
    visible_rects = [pdf.Rect(span["bbox"]) for span in traces
                     if span["type"] != 3 and span["opacity"] > 0]
    native = [block for block in extract_page_blocks(page) if any(
        rect.intersects(pdf.Rect(block["bbox"])) for rect in visible_rects)]
    full_image = any((pdf.Rect(info["bbox"]) & page.rect).get_area() > page.rect.get_area() * 0.9
                     for info in page.get_image_info())
    if page.get_images() and (not visible_rects or full_image):
        recognized = scan_blocks(page, config)
        return native + [block for block in recognized if not any(
            pdf.Rect(block["bbox"]).intersects(pdf.Rect(item["bbox"])) for item in native)]
    return native
