from __future__ import annotations

import io
import math
from pathlib import Path

import cv2
import numpy as np
import pymupdf as pdf
from PIL import Image, ImageOps, UnidentifiedImageError

from pdf_engine import ProcessingError, open_pdf, render, save


def _order_quad_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def _detect_document_quad(bgr: np.ndarray) -> np.ndarray | None:
    h, w = bgr.shape[:2]
    if h < 40 or w < 40:
        return None
    scale = min(1.0, 900.0 / max(h, w))
    small = cv2.resize(bgr, (int(w * scale), int(h * scale))) if scale < 1.0 else bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
    min_area = (small.shape[0] * small.shape[1]) * 0.25
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            break
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            pts = approx.reshape(4, 2).astype("float32") / scale
            return _order_quad_points(pts)
    return None


def _warp_perspective(bgr: np.ndarray, corners: np.ndarray) -> np.ndarray:
    ordered = _order_quad_points(corners.astype("float32"))
    tl, tr, br, bl = ordered
    width_a = np.hypot(br[0] - bl[0], br[1] - bl[1])
    width_b = np.hypot(tr[0] - tl[0], tr[1] - tl[1])
    max_w = max(32, int(round(max(width_a, width_b))))
    height_a = np.hypot(tr[0] - br[0], tr[1] - br[1])
    height_b = np.hypot(tl[0] - bl[0], tl[1] - bl[1])
    max_h = max(32, int(round(max(height_a, height_b))))
    dst = np.array([[0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]], dtype="float32")
    matrix = cv2.getPerspectiveTransform(ordered, dst)
    return cv2.warpPerspective(bgr, matrix, (max_w, max_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _dewarp_book_curvature(bgr: np.ndarray) -> tuple[np.ndarray, bool]:
    """Compensa curvatura vertical suave tipica de lomo de libro usando proyeccion de trazos."""
    h, w = bgr.shape[:2]
    if h < 120 or w < 120:
        return bgr, False
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # Resaltar trazos de texto horizontales
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    strips = 16
    strip_w = max(8, w // strips)
    xs = []
    offsets = []
    mid_y = h / 2.0
    for s in range(strips):
        x0 = s * strip_w
        x1 = min(w, x0 + strip_w)
        col_ink = np.where(binary[int(h * 0.12):int(h * 0.88), x0:x1] > 0)[0]
        if len(col_ink) > 25:
            xs.append((x0 + x1) / 2.0)
            offsets.append(float(np.median(col_ink)) + h * 0.12 - mid_y)
    if len(xs) < 6:
        return bgr, False
    coeffs = np.polyfit(np.array(xs), np.array(offsets), 2)
    x_grid = np.arange(w, dtype=np.float32)
    curve = np.polyval(coeffs, x_grid).astype(np.float32)
    curve -= float(np.median(curve))
    amp = float(np.max(np.abs(curve)))
    if not (2.0 <= amp <= min(60.0, h * 0.12)):
        return bgr, False
    map_x = np.tile(x_grid, (h, 1))
    base_y = np.arange(h, dtype=np.float32)[:, None]
    map_y = (base_y + curve[None, :]).astype(np.float32)
    remapped = cv2.remap(bgr, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return remapped, True


def _normalize_illumination(bgr: np.ndarray) -> np.ndarray:
    """Elimina sombras de lomo y dedos normalizando cada canal contra la envolvente de fondo."""
    h, w = bgr.shape[:2]
    k = max(15, (min(h, w) // 25) | 1)
    k = min(k, 81)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    out_channels = []
    for ch in cv2.split(bgr):
        dilated = cv2.dilate(ch, kernel)
        bg = cv2.GaussianBlur(dilated, (k, k), 0)
        norm = cv2.divide(ch.astype(np.float32), np.maximum(bg.astype(np.float32), 1.0), scale=255.0)
        out_channels.append(np.clip(norm, 0, 255).astype(np.uint8))
    return cv2.merge(out_channels)


def _assemble_mrc_page(out_doc: pdf.Document, bgr: np.ndarray, mrc_enabled: bool, dpi: int) -> pdf.Page:
    h, w = bgr.shape[:2]
    pt_w = max(72.0, w * 72.0 / dpi)
    pt_h = max(72.0, h * 72.0 / dpi)
    page = out_doc.new_page(width=pt_w, height=pt_h)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    if not mrc_enabled:
        pil_img = Image.fromarray(rgb)
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=85)
        page.insert_image(page.rect, stream=buf.getvalue())
        return page

    # Capa 1: fondo cromático suavizado y submuestreado 0.5x
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    fg_thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 11)
    fg_thresh = cv2.medianBlur(fg_thresh, 3)

    inpaint_mask = cv2.dilate(fg_thresh, np.ones((3, 3), np.uint8), iterations=1)
    bg_clean = cv2.inpaint(rgb, inpaint_mask, 3, cv2.INPAINT_TELEA) if np.any(fg_thresh) else rgb
    bg_small = cv2.resize(bg_clean, (max(16, w // 2), max(16, h // 2)), interpolation=cv2.INTER_AREA)
    bg_buf = io.BytesIO()
    Image.fromarray(bg_small).save(bg_buf, format="JPEG", quality=55, optimize=True)
    page.insert_image(page.rect, stream=bg_buf.getvalue())

    # Capa 2: tinta bitonal nitida lossless CCITT Group 4 como mascara sobre color oscuro dominante
    if np.count_nonzero(fg_thresh) > 20:
        ink_rgb = Image.new("RGB", (w, h), (15, 18, 24))
        fg_buf = io.BytesIO()
        ink_rgb.save(fg_buf, format="PNG")
        mask_img = Image.fromarray(fg_thresh, mode="L").convert("1")
        mask_buf = io.BytesIO()
        mask_img.save(mask_buf, format="TIFF", compression="group4")
        page.insert_image(page.rect, stream=fg_buf.getvalue(), mask=mask_buf.getvalue(), overlay=True)

    return page


def handle_scan_enhance_3d(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    from pdf_engine import capabilities

    password = str(options.get("password", ""))
    dpi = int(options.get("dpi", 200))
    dpi = max(100, min(300, dpi))
    perspective = bool(options.get("perspective", True))
    dewarp = bool(options.get("dewarp", True))
    illumination_clean = bool(options.get("illumination_clean", True))
    mrc_enabled = bool(options.get("mrc", True))
    add_ocr = bool(options.get("add_ocr", False))
    corners_opt = options.get("corners")

    raw_frames: list[np.ndarray] = []
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass

    for src in sources:
        if src.suffix.lower() == ".pdf":
            with open_pdf(src, password, config["max_pages"]) as doc:
                for page in doc:
                    pix = render(page, dpi, config)
                    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
                    raw_frames.append(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        else:
            try:
                with Image.open(src) as img:
                    if img.width * img.height > config["max_render_pixels"]:
                        raise ProcessingError("Imagen demasiado grande para procesar en 3D.")
                    img = ImageOps.exif_transpose(img).convert("RGB")
                    raw_frames.append(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR))
            except (UnidentifiedImageError, OSError):
                raise ProcessingError("Imagen escaneada no valida o danada.") from None

    if not raw_frames or (config["max_pages"] and len(raw_frames) > config["max_pages"]):
        raise ProcessingError("Numero de paginas escaneadas fuera de rango.")

    warped_count = 0
    dewarped_count = 0
    ocr_ready = add_ocr and bool(capabilities(config, root).get("ocr"))
    out_pdf = folder / "escaneo_3d_mrc.pdf"

    try:
        with pdf.open() as out_doc:
            for idx, frame in enumerate(raw_frames):
                img = frame
                if corners_opt and isinstance(corners_opt, list) and len(corners_opt) == 4 and idx == 0:
                    pts = []
                    h, w = img.shape[:2]
                    for pt in corners_opt:
                        if isinstance(pt, (list, tuple)) and len(pt) == 2:
                            px = float(pt[0]) * w if 0.0 <= float(pt[0]) <= 1.0 and float(pt[1]) <= 1.0 else float(pt[0])
                            py = float(pt[1]) * h if 0.0 <= float(pt[0]) <= 1.0 and float(pt[1]) <= 1.0 else float(pt[1])
                            pts.append([px, py])
                    if len(pts) == 4:
                        img = _warp_perspective(img, np.array(pts, dtype="float32"))
                        warped_count += 1
                elif perspective:
                    quad = _detect_document_quad(img)
                    if quad is not None:
                        img = _warp_perspective(img, quad)
                        warped_count += 1

                if dewarp:
                    img, did_dewarp = _dewarp_book_curvature(img)
                    if did_dewarp:
                        dewarped_count += 1

                if illumination_clean:
                    img = _normalize_illumination(img)

                if ocr_ready:
                    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    pix = pdf.Pixmap(pdf.csRGB, img.shape[1], img.shape[0], rgb.tobytes(), False)
                    raw_ocr = pix.pdfocr_tobytes(language=config["ocr_language"], tessdata=str(root / "models"))
                    with pdf.open(stream=raw_ocr, filetype="pdf") as rdoc:
                        out_doc.insert_pdf(rdoc)
                else:
                    _assemble_mrc_page(out_doc, img, mrc_enabled=mrc_enabled, dpi=dpi)
            save(out_doc, out_pdf, clean=True)
    except cv2.error as err:
        raise ProcessingError(f"Error fotometrico en OpenCV: {err}") from None

    return {
        "file": out_pdf.name,
        "notice": (
            f"Escaneo 3D/MRC completado: {len(raw_frames)} pagina(s), "
            f"perspectiva={warped_count}, dewarped={dewarped_count}, MRC={'CCITT-G4+JPEG' if mrc_enabled else 'JPEG'}."
        ),
    }
