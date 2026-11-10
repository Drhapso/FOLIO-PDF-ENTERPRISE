"""Motor de reconstruccion editable de PDF/imagenes escaneadas hacia Office y PDF vectorial.

Implementa analisis visual determinista y OCR local estilo Acrobat Pro:
1. Preprocesamiento y estimacion de fondo de papel + limpieza de sombras/inclinacion.
2. Deteccion de tablas rasterizadas con y sin bordes (incluyendo celdas combinadas y relleno RGB).
3. Vectorizacion de diagramas (cajas, rectangulos redondeados, ovalos, rombos, poligonos y conectores/flechas).
4. Reconocimiento OCR local libre de trazos largos de borde, con recuperacion de color de tinta, negrita y tamano.
5. Inpainting / borrado limpio de elementos ya reconstruidos del fondo para evitar texto fantasma duplicado.
"""

from __future__ import annotations

import io
import math
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pymupdf as pdf
from PIL import Image, ImageOps, UnidentifiedImageError

from pdf_engine import IMAGE_TYPES, ProcessingError, capabilities, integer, open_pdf, pages_from, render, save


_SHORT_RULE_NOISE_RE = re.compile(r"^[|_\-—=+\\/()\[\]{}.,:;~^*•·`´]+$")


def _to_hex(bgr_or_rgb: tuple[int, int, int] | np.ndarray, *, is_bgr: bool = True) -> str:
    arr = [int(max(0, min(255, round(v)))) for v in bgr_or_rgb[:3]]
    r, g, b = (arr[2], arr[1], arr[0]) if is_bgr else (arr[0], arr[1], arr[2])
    return f"{r:02X}{g:02X}{b:02X}"


def _normalize_orientation_bgr(
    bgr: np.ndarray, page_rotation: int, pt_w: float, pt_h: float
) -> tuple[np.ndarray, float, float, int]:
    """Corrige orientaciones de 90/180/270 grados (p. ej. paginas escaneadas rotadas)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    scale = min(1.0, 650.0 / max(1, max(h, w)))
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else gray
    _, mask = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    row_var = float(np.var(mask.sum(axis=1))) if mask.size else 0.0
    col_var = float(np.var(mask.sum(axis=0))) if mask.size else 0.0

    rot_deg = 0
    if page_rotation in (90, 180, 270):
        # Si PyMuPDF renderizo girado el escaneo por /Rotate, revertirlo cuando la proyeccion confirma giro
        if page_rotation in (90, 270) and col_var > row_var * 1.15:
            rot_deg = (-page_rotation) % 360
        elif page_rotation == 180:
            rot_deg = 180
    elif col_var > row_var * 1.45:
        rot_deg = 270

    if rot_deg == 90:
        return cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE), pt_h, pt_w, 90
    if rot_deg == 180:
        return cv2.rotate(bgr, cv2.ROTATE_180), pt_w, pt_h, 180
    if rot_deg == 270:
        return cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE), pt_h, pt_w, 270
    return bgr, pt_w, pt_h, 0


def _sample_paper_bgr(bgr: np.ndarray) -> np.ndarray:
    h, w = bgr.shape[:2]
    strip = max(2, min(8, min(h, w) // 20))
    borders = np.concatenate(
        (
            bgr[:strip, :].reshape(-1, 3),
            bgr[-strip:, :].reshape(-1, 3),
            bgr[:, :strip].reshape(-1, 3),
            bgr[:, -strip:].reshape(-1, 3),
        ),
        axis=0,
    )
    luma = 0.114 * borders[:, 0] + 0.587 * borders[:, 1] + 0.299 * borders[:, 2]
    bright = borders[luma >= 190]
    if len(bright) >= max(20, len(borders) // 4):
        return np.median(bright, axis=0).astype(np.uint8)
    # Fallback al percentil 85 global por si los bordes tienen viñeteo oscuro
    flat = bgr[:: max(1, h // 120), :: max(1, w // 120), :].reshape(-1, 3)
    flat_luma = 0.114 * flat[:, 0] + 0.587 * flat[:, 1] + 0.299 * flat[:, 2]
    top_bright = flat[flat_luma >= np.percentile(flat_luma, 75)]
    if len(top_bright):
        return np.median(top_bright, axis=0).astype(np.uint8)
    return np.array([255, 255, 255], dtype=np.uint8)


def _preprocess_bgr(bgr: np.ndarray, mode: str, max_pixels: int) -> tuple[np.ndarray, np.ndarray]:
    cv2.setNumThreads(1)
    if mode not in {"auto", "none", "deskew", "clean"}:
        mode = "auto"
    paper_bgr = _sample_paper_bgr(bgr)
    if mode == "none":
        return bgr, paper_bgr

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    scale = min(1.0, 1100.0 / max(1, max(h, w)))
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else gray
    _, mask = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    center = (mask.shape[1] / 2.0, mask.shape[0] / 2.0)
    zero_score = float(np.var(mask.sum(axis=1))) if mask.size else 0.0
    best_score = zero_score
    best_angle = 0.0
    for step in range(-10, 11):
        if step == 0:
            continue
        candidate = step / 2.0
        mat = cv2.getRotationMatrix2D(center, candidate, 1.0)
        rot = cv2.warpAffine(mask, mat, (mask.shape[1], mask.shape[0]))
        score = float(np.var(rot.sum(axis=1)))
        if score > best_score:
            best_score = score
            best_angle = candidate

    should_rotate = False
    if best_angle != 0.0:
        threshold = 1.08 if mode == "auto" else 1.01
        should_rotate = zero_score <= 0.0 or best_score >= zero_score * threshold

    out = bgr
    if should_rotate:
        mat = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), best_angle, 1.0)
        cos_v, sin_v = abs(mat[0, 0]), abs(mat[0, 1])
        nw = int(w * cos_v + h * sin_v + 1)
        nh = int(h * cos_v + w * sin_v + 1)
        if nw * nh <= max_pixels:
            mat[0, 2] += (nw - w) / 2.0
            mat[1, 2] += (nh - h) / 2.0
            out = cv2.warpAffine(
                out,
                mat,
                (nw, nh),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=tuple(int(x) for x in paper_bgr),
            )
            paper_bgr = _sample_paper_bgr(out)

    if mode == "clean":
        ch, cw = out.shape[:2]
        k = max(21, min(75, (min(ch, cw) // 22) | 1))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        norm_ch = []
        for idx, channel in enumerate(cv2.split(out)):
            bg = cv2.GaussianBlur(cv2.dilate(channel, kernel), (k, k), 0)
            target_tone = max(225.0, float(paper_bgr[idx]))
            ratio = channel.astype(np.float32) / np.maximum(bg.astype(np.float32), 1.0)
            norm = np.clip(ratio * target_tone, 0, 255).astype(np.uint8)
            norm_ch.append(norm)
        out = cv2.merge(norm_ch)
        paper_bgr = _sample_paper_bgr(out)

    return out, paper_bgr


def _build_line_and_ink_masks(bgr: np.ndarray, paper_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Devuelve (ink_mask, horiz_lines, vert_lines, long_rules_mask)."""
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    block = max(11, min(35, (min(h, w) // 20) | 1))
    adap_text = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 9)
    adap_light = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, -10)
    adap_line = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, 5)

    # Contraste cromatico local (pasa-altas): capta texto o trazos finos de cualquier color sin marcar rellenos planos
    blur_k = max(19, min(41, (min(h, w) // 30) | 1))
    local_bg = cv2.GaussianBlur(bgr, (blur_k, blur_k), 0)
    local_stroke = (np.max(np.abs(bgr.astype(np.int16) - local_bg.astype(np.int16)), axis=2) > 22).astype(np.uint8) * 255

    line_src = adap_line
    kh_len = max(20, min(46, w // 28))
    kv_len = max(20, min(46, h // 28))
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (kh_len, 1))
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kv_len))
    horiz = cv2.dilate(cv2.erode(line_src, kh), kh)
    vert = cv2.dilate(cv2.erode(line_src, kv), kv)
    # Cerrar micro-cortes del escaneo a lo largo del eje correspondiente
    horiz = cv2.morphologyEx(horiz, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 1)))
    vert = cv2.morphologyEx(vert, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 7)))

    # Trazos muy largos que conviene ocultar antes del OCR para evitar caracteres "|" o "_" espurios
    long_kh = cv2.getStructuringElement(cv2.MORPH_RECT, (max(32, min(60, w // 20)), 1))
    long_kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(32, min(60, h // 20))))
    long_h = cv2.dilate(cv2.erode(line_src, long_kh), long_kh)
    long_v = cv2.dilate(cv2.erode(line_src, long_kv), long_kv)
    long_rules = cv2.dilate(cv2.bitwise_or(long_h, long_v), np.ones((3, 3), np.uint8), iterations=1)

    ink_mask = cv2.bitwise_or(adap_text, local_stroke)
    ink_mask = cv2.bitwise_or(ink_mask, cv2.bitwise_and(adap_light, cv2.bitwise_not(adap_text)))
    return ink_mask, horiz, vert, long_rules


def _cluster_positions(indices: np.ndarray, gap: int = 5) -> list[int]:
    if len(indices) == 0:
        return []
    clusters: list[list[int]] = [[int(indices[0])]]
    for val in indices[1:]:
        iv = int(val)
        if iv - clusters[-1][-1] <= gap:
            clusters[-1].append(iv)
        else:
            clusters.append([iv])
    return [int(round(sum(c) / len(c))) for c in clusters]


def _sample_region_fill(bgr: np.ndarray, ink_or_text_mask: np.ndarray, box_px: tuple[int, int, int, int], paper_bgr: np.ndarray) -> str | None:
    h, w = bgr.shape[:2]
    x0, y0, x1, y1 = [int(v) for v in box_px]
    pad = 4 if (x1 - x0) > 14 and (y1 - y0) > 14 else 1
    rx0, ry0 = max(0, x0 + pad), max(0, y0 + pad)
    rx1, ry1 = min(w, x1 - pad), min(h, y1 - pad)
    if rx1 <= rx0 or ry1 <= ry0:
        return None
    roi = bgr[ry0:ry1, rx0:rx1]
    fg = ink_or_text_mask[ry0:ry1, rx0:rx1]
    bg_pixels = roi[fg == 0]
    if len(bg_pixels) < max(6, int(roi.shape[0] * roi.shape[1] * 0.1)):
        bg_pixels = roi.reshape(-1, 3)
    med = np.median(bg_pixels, axis=0)
    if float(np.max(np.abs(med - paper_bgr))) <= 12.0:
        return None
    return _to_hex(med, is_bgr=True)


def _sample_stroke_style(bgr: np.ndarray, edge_pixels_bgr: np.ndarray, paper_bgr: np.ndarray) -> str:
    if len(edge_pixels_bgr) == 0:
        return "222222"
    diff = np.max(np.abs(edge_pixels_bgr.astype(np.int16) - paper_bgr.astype(np.int16)), axis=1)
    valid = edge_pixels_bgr[diff > 18]
    if len(valid) == 0:
        valid = edge_pixels_bgr
    # Preferir el cuartil mas oscuro para evitar mezcla anti-aliased con papel
    luma = 0.114 * valid[:, 0] + 0.587 * valid[:, 1] + 0.299 * valid[:, 2]
    dark = valid[luma <= np.percentile(luma, 45)]
    chosen = np.median(dark if len(dark) else valid, axis=0)
    return _to_hex(chosen, is_bgr=True)


def _detect_raster_tables(
    bgr: np.ndarray,
    ink_mask: np.ndarray,
    horiz_lines: np.ndarray,
    vert_lines: np.ndarray,
    paper_bgr: np.ndarray,
    pt_w: float,
    pt_h: float,
) -> tuple[list[dict], np.ndarray]:
    """Detecta tablas vectoriales a partir de cuadricula raster H/V."""
    img_h, img_w = bgr.shape[:2]
    sx, sy = pt_w / img_w, pt_h / img_h
    grid = cv2.bitwise_or(horiz_lines, vert_lines)
    intersections = cv2.bitwise_and(horiz_lines, vert_lines)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(grid, np.ones((3, 3), np.uint8), iterations=1))

    tables: list[dict] = []
    table_mask = np.zeros((img_h, img_w), dtype=np.uint8)

    for label in range(1, num_labels):
        bx, by, bw, bh, area = [int(v) for v in stats[label]]
        if bw < 44 or bh < 28 or (bw > img_w * 0.98 and bh > img_h * 0.98):
            continue
        roi_inter = intersections[by : by + bh, bx : bx + bw]
        if cv2.countNonZero(roi_inter) < 4:
            continue

        roi_h = horiz_lines[by : by + bh, bx : bx + bw]
        roi_v = vert_lines[by : by + bh, bx : bx + bw]
        row_proj = np.count_nonzero(roi_h, axis=1)
        col_proj = np.count_nonzero(roi_v, axis=0)
        ys_local = _cluster_positions(np.where(row_proj >= max(18, int(bw * 0.42)))[0], gap=5)
        xs_local = _cluster_positions(np.where(col_proj >= max(16, int(bh * 0.42)))[0], gap=5)
        if not ys_local or not xs_local:
            continue

        # Asegurar bordes extremos si el trazo abarca cerca del borde
        if ys_local[0] > 8 and np.any(row_proj[:8] >= max(14, int(bw * 0.42))):
            ys_local.insert(0, 0)
        if bh - 1 - ys_local[-1] > 8 and np.any(row_proj[-8:] >= max(14, int(bw * 0.42))):
            ys_local.append(bh - 1)
        if xs_local[0] > 8 and np.any(col_proj[:8] >= max(14, int(bh * 0.42))):
            xs_local.insert(0, 0)
        if bw - 1 - xs_local[-1] > 8 and np.any(col_proj[-8:] >= max(14, int(bh * 0.42))):
            xs_local.append(bw - 1)

        # Una caja simple 1x1 sin divisiones internas pertenece a diagramas, no a tablas
        if len(xs_local) < 2 or len(ys_local) < 2 or (len(xs_local) == 2 and len(ys_local) == 2):
            continue

        # Exigir perimetro exterior consistente para no confundir cajas + flechas o tramas con una tabla real
        def _band_cov_h(y_pos: int) -> float:
            band = roi_h[max(0, y_pos - 3) : min(bh, y_pos + 4), :]
            return float(np.count_nonzero(np.any(band > 0, axis=0))) / max(1, bw)

        def _band_cov_v(x_pos: int) -> float:
            band = roi_v[:, max(0, x_pos - 3) : min(bw, x_pos + 4)]
            return float(np.count_nonzero(np.any(band > 0, axis=1))) / max(1, bh)

        if min(_band_cov_h(ys_local[0]), _band_cov_h(ys_local[-1])) < 0.65:
            continue
        if min(_band_cov_v(xs_local[0]), _band_cov_v(xs_local[-1])) < 0.60:
            continue

        # Descartar imagenes o texturas densas mal interpretadas como rejilla
        inner_gray = cv2.cvtColor(bgr[by + 4 : max(by + 5, by + bh - 4), bx + 4 : max(bx + 5, bx + bw - 4)], cv2.COLOR_BGR2GRAY)
        inner_ink = ink_mask[by + 4 : max(by + 5, by + bh - 4), bx + 4 : max(bx + 5, bx + bw - 4)]
        if inner_ink.size > 0 and float(np.count_nonzero(inner_ink)) / float(inner_ink.size) > 0.58:
            continue
        if inner_gray.size > 0:
            bg_roi = bgr[by + 4 : max(by + 5, by + bh - 4), bx + 4 : max(bx + 5, bx + bw - 4)][inner_ink == 0]
            if len(bg_roi) >= 30 and float(np.max(np.std(bg_roi, axis=0))) > 42.0:
                continue

        xs_px = [bx + x for x in xs_local]
        ys_px = [by + y for y in ys_local]
        nrows = len(ys_px) - 1
        ncols = len(xs_px) - 1
        if nrows < 1 or ncols < 1 or nrows > 80 or ncols > 40:
            continue

        # Mapa de paredes para reconstruir celdas combinadas
        def _has_right_wall(r: int, c: int) -> bool:
            x_cut = xs_px[c + 1]
            y_a, y_b = ys_px[r], ys_px[r + 1]
            margin = max(2, (y_b - y_a) // 6)
            strip = vert_lines[y_a + margin : max(y_a + margin + 1, y_b - margin), max(0, x_cut - 3) : min(img_w, x_cut + 4)]
            covered = np.count_nonzero(np.any(strip > 0, axis=1))
            return covered >= max(3, (y_b - y_a - 2 * margin) * 0.45)

        def _has_bottom_wall(r: int, c: int) -> bool:
            y_cut = ys_px[r + 1]
            x_a, x_b = xs_px[c], xs_px[c + 1]
            margin = max(2, (x_b - x_a) // 6)
            strip = horiz_lines[max(0, y_cut - 3) : min(img_h, y_cut + 4), x_a + margin : max(x_a + margin + 1, x_b - margin)]
            covered = np.count_nonzero(np.any(strip > 0, axis=0))
            return covered >= max(3, (x_b - x_a - 2 * margin) * 0.45)

        visited = [[False] * ncols for _ in range(nrows)]
        cells_pt: list[tuple[int, int, int, int, tuple[float, float, float, float]]] = []
        fills: dict[tuple[int, int], str] = {}

        # Mascara combinada temporal de bordes H/V para medir relleno interno limpio
        clean_fg = cv2.bitwise_or(ink_mask, grid)
        for r in range(nrows):
            for c in range(ncols):
                if visited[r][c]:
                    continue
                end_c = c
                while end_c + 1 < ncols and not visited[r][end_c + 1] and not _has_right_wall(r, end_c):
                    end_c += 1
                end_r = r
                while end_r + 1 < nrows:
                    can_down = all(
                        not visited[end_r + 1][cc] and not _has_bottom_wall(end_r, cc)
                        for cc in range(c, end_c + 1)
                    )
                    if not can_down:
                        break
                    end_r += 1
                for rr in range(r, end_r + 1):
                    for cc in range(c, end_c + 1):
                        visited[rr][cc] = True
                cx0, cy0, cx1, cy1 = xs_px[c], ys_px[r], xs_px[end_c + 1], ys_px[end_r + 1]
                fill_hex = _sample_region_fill(bgr, clean_fg, (cx0, cy0, cx1, cy1), paper_bgr)
                if fill_hex:
                    fills[(r, c)] = fill_hex
                cells_pt.append((r, c, end_r, end_c, (cx0 * sx, cy0 * sy, cx1 * sx, cy1 * sy)))

        border_pixels = bgr[by : by + bh, bx : bx + bw][grid[by : by + bh, bx : bx + bw] > 0]
        border_rgb = _sample_stroke_style(bgr, border_pixels, paper_bgr)
        xs_pt = [round(x * sx, 2) for x in xs_px]
        ys_pt = [round(y * sy, 2) for y in ys_px]
        tx0_pt, ty0_pt, tx1_pt, ty1_pt = xs_pt[0], ys_pt[0], xs_pt[-1], ys_pt[-1]

        tables.append(
            {
                "bbox": (tx0_pt, ty0_pt, tx1_pt, ty1_pt),
                "bbox_px": (xs_px[0], ys_px[0], xs_px[-1], ys_px[-1]),
                "xs": xs_pt,
                "ys": ys_pt,
                "cells": cells_pt,
                "fills": fills,
                "border_rgb": border_rgb,
                "border_pt": 1.0,
                "mode": "ruled",
            }
        )
        cv2.rectangle(
            table_mask,
            (max(0, xs_px[0] - 4), max(0, ys_px[0] - 4)),
            (min(img_w - 1, xs_px[-1] + 4), min(img_h - 1, ys_px[-1] + 4)),
            255,
            -1,
        )

    return tables, table_mask


def _is_diamond(pts: np.ndarray, bx: int, by: int, bw: int, bh: int) -> bool:
    if len(pts) != 4:
        return False
    cx, cy = bx + bw / 2.0, by + bh / 2.0
    # Un rombo tiene 4 vertices cercanos a los puntos medios de los 4 lados
    edge_mids = [(bx + bw / 2.0, by), (bx + bw, by + bh / 2.0), (bx + bw / 2.0, by + bh), (bx, by + bh / 2.0)]
    hits = 0
    for ex, ey in edge_mids:
        dist = min(math.hypot(float(p[0]) - ex, float(p[1]) - ey) for p in pts)
        if dist <= max(8.0, min(bw, bh) * 0.22):
            hits += 1
    return hits >= 3 and abs(cv2.contourArea(pts) / max(1.0, bw * bh) - 0.5) <= 0.22


def _detect_raster_containers(
    bgr: np.ndarray,
    ink_mask: np.ndarray,
    table_mask: np.ndarray,
    paper_bgr: np.ndarray,
    pt_w: float,
    pt_h: float,
) -> tuple[list[dict], np.ndarray]:
    """Detecta formas geometricas cerradas de diagramas antes del OCR usando contraste frente al papel y fondo plano."""
    img_h, img_w = bgr.shape[:2]
    sx, sy = pt_w / img_w, pt_h / img_h
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    color_diff = (np.max(np.abs(bgr.astype(np.int16) - paper_bgr.astype(np.int16)), axis=2) > 18).astype(np.uint8) * 255
    edges = cv2.Canny(gray, 45, 135)
    edge_closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    padded_e = cv2.copyMakeBorder(edge_closed, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    cv2.floodFill(padded_e, None, (0, 0), 255)
    closed_interiors = cv2.bitwise_not(padded_e[1:-1, 1:-1])
    shape_src = cv2.bitwise_or(color_diff, closed_interiors)
    shape_src[table_mask > 0] = 0
    # Apertura rectangular (15x15) despega conectores/flechas que tocan las cajas sin deformar esquinas rectas
    open_k = max(13, min(19, int(round(min(img_h, img_w) * 0.009)) | 1))
    shape_closed = cv2.morphologyEx(
        shape_src, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (open_k, open_k))
    )

    contours, hierarchy = cv2.findContours(shape_closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    shapes: list[dict] = []
    shape_fill_mask = np.zeros((img_h, img_w), dtype=np.uint8)
    page_area = float(img_h * img_w)

    candidates: list[tuple[float, int, np.ndarray]] = []
    if contours and hierarchy is not None:
        hier = hierarchy[0]
        for idx, cnt in enumerate(contours):
            area = float(cv2.contourArea(cnt))
            if area < 1400.0 or area > page_area * 0.85:
                continue
            bx, by, bw, bh = cv2.boundingRect(cnt)
            bw_pt, bh_pt = bw * sx, bh * sy
            # Una figura real de diagrama supera holgadamente el tamano de una sola letra ("O", "0", etc.)
            if bw < 48 or bh < 32 or bw_pt < 36.0 or bh_pt < 22.0:
                continue
            # En diagramas reales el rectangulo no puede ser una barra fina o una sola letra aislada
            if max(bw / max(1, bh), bh / max(1, bw)) > 9.0:
                continue
            parent = int(hier[idx][3])
            if parent >= 0:
                px, py, pw, ph = cv2.boundingRect(contours[parent])
                if abs(pw - bw) <= 18 and abs(ph - bh) <= 18:
                    continue
            candidates.append((area, idx, cnt))

    accepted_boxes_px: list[tuple[int, int, int, int]] = []
    for area, _, cnt in sorted(candidates, key=lambda item: item[0], reverse=True):
        bx, by, bw, bh = cv2.boundingRect(cnt)
        bbox_area = float(bw * bh)
        extent = area / max(1.0, bbox_area)
        if extent < 0.35:
            continue
        duplicate = False
        for ax0, ay0, ax1, ay1 in accepted_boxes_px:
            if abs(ax0 - bx) <= 10 and abs(ay0 - by) <= 10 and abs(ax1 - (bx + bw)) <= 10 and abs(ay1 - (by + bh)) <= 10:
                duplicate = True
                break
        if duplicate:
            continue

        peri = cv2.arcLength(cnt, True)
        if peri <= 0:
            continue
        approx = cv2.approxPolyDP(cnt, 0.025 * peri, True).reshape(-1, 2)
        hull = cv2.convexHull(cnt)
        hull_area = float(cv2.contourArea(hull))
        solidity = area / max(1.0, hull_area)
        if solidity < 0.78:
            continue

        circularity = 4.0 * math.pi * area / (peri * peri)
        kind = "rect"
        if _is_diamond(approx, bx, by, bw, bh):
            kind = "diamond"
        elif circularity >= 0.74 or (len(approx) >= 7 and 0.65 <= extent <= 0.85 and solidity >= 0.90):
            kind = "oval"
        elif len(approx) == 4 and extent >= 0.85:
            kind = "rect"
        elif 4 <= len(approx) <= 12 and extent >= 0.78:
            kind = "round_rect"
        elif 3 <= len(approx) <= 10:
            kind = "polygon"
        else:
            continue

        interior_mask = np.zeros((img_h, img_w), dtype=np.uint8)
        cv2.drawContours(interior_mask, [cnt], -1, 255, thickness=-1)
        interior_eroded = cv2.erode(interior_mask, np.ones((11, 11), np.uint8), iterations=1)
        if cv2.countNonZero(interior_eroded) < 60:
            continue

        # Medir uniformidad del fondo NO tinta para distinguir cajas vectoriales frente a fotos/degradados
        bg_only = cv2.bitwise_and(interior_eroded, cv2.bitwise_not(ink_mask))
        bg_count = cv2.countNonZero(bg_only)
        fill_sample_px = bgr[bg_only > 0] if bg_count >= 25 else bgr[interior_eroded > 0]
        if len(fill_sample_px) < 25:
            continue
        if bg_count >= 25 and float(np.max(np.std(fill_sample_px, axis=0))) > 28.0:
            # Degradado multicolor o fotografia compleja -> conservar en el fondo residual
            continue
        if float(bg_count) / max(1.0, float(cv2.countNonZero(interior_eroded))) < 0.35:
            # Demasiada textura/tinta solida sin interior limpio de caja/etiqueta
            continue

        med_fill = np.median(fill_sample_px, axis=0)
        fill_rgb: str | None = None
        if float(np.max(np.abs(med_fill - paper_bgr))) > 15.0:
            fill_rgb = _to_hex(med_fill, is_bgr=True)

        # Rechazar posibles letras huecas muy grandes ("O"/"0") sin relleno ni etiqueta interna
        if fill_rgb is None and bw * sx < 65.0 and bh * sy < 65.0:
            inner_ink = cv2.countNonZero(cv2.bitwise_and(interior_eroded, ink_mask))
            if inner_ink < 15:
                continue

        contour_mask = np.zeros((img_h, img_w), dtype=np.uint8)
        cv2.drawContours(contour_mask, [cnt], -1, 255, thickness=max(2, int(round(min(bw, bh) * 0.04))))
        border_px = bgr[contour_mask > 0]
        stroke_rgb = _sample_stroke_style(bgr, border_px, paper_bgr)

        if fill_rgb is not None:
            fill_vals = [int(fill_rgb[i : i + 2], 16) for i in (0, 2, 4)]
            stroke_vals = [int(stroke_rgb[i : i + 2], 16) for i in (0, 2, 4)]
            stroke_rgb_out = None if max(abs(a - b) for a, b in zip(fill_vals, stroke_vals)) <= 24 else stroke_rgb
        else:
            stroke_rgb_out = stroke_rgb

        accepted_boxes_px.append((bx, by, bx + bw, by + bh))
        cv2.drawContours(shape_fill_mask, [cnt], -1, 255, thickness=-1)
        cv2.drawContours(shape_fill_mask, [cnt], -1, 255, thickness=5)

        shapes.append(
            {
                "kind": kind,
                "bbox": (round(bx * sx, 2), round(by * sy, 2), round((bx + bw) * sx, 2), round((by + bh) * sy, 2)),
                "bbox_px": (bx, by, bx + bw, by + bh),
                "points_pt": [(round(float(p[0]) * sx, 2), round(float(p[1]) * sy, 2)) for p in approx],
                "contour": cnt,
                "interior_eroded": interior_eroded,
                "fill_bgr": med_fill.astype(np.uint8),
                "fill_rgb": fill_rgb,
                "stroke_rgb": stroke_rgb_out,
                "stroke_pt": 1.25,
                "embedded_lines": [],
            }
        )

    return shapes, shape_fill_mask


def _extract_shape_embedded_ocr(
    bgr: np.ndarray,
    ink_mask: np.ndarray,
    paper_bgr: np.ndarray,
    shapes: list[dict],
    pt_w: float,
    pt_h: float,
    config: dict,
    root: Path,
    ocr_mode: str,
) -> tuple[list[dict], bool]:
    """Lee por OCR exclusivamente el interior limpio de cada caja/ovalo de diagrama sin ruido de bordes."""
    img_h, img_w = bgr.shape[:2]
    languages = config["ocr_language"].split("+")
    ocr_available = all((root / "models" / f"{lang}.traineddata").is_file() for lang in languages)
    if not shapes or ocr_mode == "existing_only" or not ocr_available:
        return [], False

    sx, sy = pt_w / img_w, pt_h / img_h
    extra_words: list[dict] = []
    used = False
    for sh in shapes:
        bx, by, x1, y1 = sh["bbox_px"]
        bw, bh = x1 - bx, y1 - by
        if bw * sx > pt_w * 0.55 or bh * sy > pt_h * 0.45:
            continue
        interior = sh["interior_eroded"][by:y1, bx:x1]
        strict_inner = cv2.erode(interior, np.ones((7, 7), np.uint8), iterations=1)
        if cv2.countNonZero(strict_inner) >= 40:
            interior = strict_inner
        if cv2.countNonZero(interior) < 40:
            continue
        crop = bgr[by:y1, bx:x1].copy()
        fill_bgr = sh["fill_bgr"]
        crop[interior == 0] = fill_bgr

        # Asegurar texto oscuro sobre fondo claro para optima lectura Tesseract
        bg_luma = 0.114 * fill_bgr[0] + 0.587 * fill_bgr[1] + 0.299 * fill_bgr[2]
        if bg_luma < 110:
            crop = 255 - crop
            pad_col = (255 - fill_bgr).tolist()
        else:
            pad_col = [int(c) for c in fill_bgr]

        scale = 2 if bh < 140 else 1
        scaled = cv2.resize(crop, (bw * scale, bh * scale), interpolation=cv2.INTER_CUBIC) if scale > 1 else crop
        pad = 28
        padded = cv2.copyMakeBorder(scaled, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=pad_col)
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        pix = pdf.Pixmap(pdf.csRGB, rgb.shape[1], rgb.shape[0], rgb.tobytes(), False)
        raw_pdf = pix.pdfocr_tobytes(language=config["ocr_language"], tessdata=str(root / "models"))
        used = True
        shape_words: list[dict] = []
        with pdf.open(stream=raw_pdf, filetype="pdf") as od:
            op = od[0]
            px_scale_x = rgb.shape[1] / max(1.0, op.rect.width)
            px_scale_y = rgb.shape[0] / max(1.0, op.rect.height)
            for item in op.get_text("words"):
                txt = str(item[4]).strip()
                if not txt:
                    continue
                wx0 = ((float(item[0]) * px_scale_x) - pad) / scale + bx
                wy0 = ((float(item[1]) * px_scale_y) - pad) / scale + by
                wx1 = ((float(item[2]) * px_scale_x) - pad) / scale + bx
                wy1 = ((float(item[3]) * px_scale_y) - pad) / scale + by
                if wx1 <= wx0 + 2 or wy1 <= wy0 + 4:
                    continue
                bbox_pt = (max(0.0, wx0 * sx), max(0.0, wy0 * sy), min(pt_w, wx1 * sx), min(pt_h, wy1 * sy))
                if bbox_pt[2] - bbox_pt[0] < 1.5 or bbox_pt[3] - bbox_pt[1] < 3.5:
                    continue
                color_int, is_bold = _estimate_word_style(bgr, ink_mask, fill_bgr, bbox_pt, pt_w, pt_h)
                size_pt = max(6.5, min(42.0, round((bbox_pt[3] - bbox_pt[1]) * 0.80 * 2.0) / 2.0))
                w_entry = {
                    "bbox": bbox_pt,
                    "text": txt,
                    "size": size_pt,
                    "color": color_int,
                    "bold": is_bold,
                    "italic": False,
                    "from_shape": True,
                }
                shape_words.append(w_entry)
                extra_words.append(w_entry)
        sh["embedded_lines"] = _words_to_lines(shape_words)
    return extra_words, used


def _detect_photo_artwork_mask(
    bgr: np.ndarray,
    table_mask: np.ndarray,
    shape_fill_mask: np.ndarray,
    paper_bgr: np.ndarray,
) -> np.ndarray:
    """Identifica regiones solidas de fotografia, logotipo o arte rasterizado para conservarlas intactas."""
    img_h, img_w = bgr.shape[:2]
    non_paper = (np.max(np.abs(bgr.astype(np.int16) - paper_bgr.astype(np.int16)), axis=2) > 20).astype(np.uint8) * 255
    non_paper[table_mask > 0] = 0
    non_paper[cv2.dilate(shape_fill_mask, np.ones((7, 7), np.uint8), iterations=1) > 0] = 0

    # La apertura morfologica (13x13) suprime trazos de letras/flechas y deja intactos bloques graficos/fotos
    blobs = cv2.morphologyEx(non_paper, cv2.MORPH_OPEN, np.ones((13, 13), np.uint8))
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(blobs)
    photo_mask = np.zeros((img_h, img_w), dtype=np.uint8)
    core_k = np.ones((5, 5), np.uint8)
    for label in range(1, num_labels):
        bx, by, bw, bh, area = [int(v) for v in stats[label]]
        if area < 450 or bw < 24 or bh < 24:
            continue
        blob_u8 = (labels[by : by + bh, bx : bx + bw] == label).astype(np.uint8) * 255
        # Medir varianza en el nucleo erosionado con borde 0 (ignora bordes anti-aliased de triangulos/simbolos planos)
        core_u8 = cv2.erode(blob_u8, core_k, iterations=1, borderType=cv2.BORDER_CONSTANT, borderValue=0)
        sample_mask = core_u8 > 0 if cv2.countNonZero(core_u8) >= 35 else blob_u8 > 0
        blob_px = bgr[by : by + bh, bx : bx + bw][sample_mask]
        if len(blob_px) == 0:
            continue
        std_max = float(np.max(np.std(blob_px, axis=0)))
        if (std_max > 28.0 and area >= 1400) or area >= 3600:
            cv2.rectangle(
                photo_mask,
                (max(0, bx - 6), max(0, by - 6)),
                (min(img_w - 1, bx + bw + 6), min(img_h - 1, by + bh + 6)),
                255,
                -1,
            )
    return photo_mask


def _detect_raster_connectors(
    bgr: np.ndarray,
    ink_mask: np.ndarray,
    table_mask: np.ndarray,
    shape_fill_mask: np.ndarray,
    photo_mask: np.ndarray,
    words: list[dict],
    paper_bgr: np.ndarray,
    pt_w: float,
    pt_h: float,
) -> list[dict]:
    """Detecta lineas y flechas conectoras fuera de tablas, cajas, fotos y palabras OCR."""
    img_h, img_w = bgr.shape[:2]
    sx, sy = pt_w / img_w, pt_h / img_h
    sx_inv, sy_inv = img_w / pt_w, img_h / pt_h
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    word_mask = np.zeros((img_h, img_w), dtype=np.uint8)
    for w_item in words:
        w_txt = w_item.get("text", "").strip()
        if len(w_txt) <= 4 and not any(ch.isalnum() for ch in w_txt):
            continue
        wx0 = max(0, int(math.floor(w_item["bbox"][0] * sx_inv)))
        wy0 = max(0, int(math.floor(w_item["bbox"][1] * sy_inv)))
        wx1 = min(img_w, int(math.ceil(w_item["bbox"][2] * sx_inv)))
        wy1 = min(img_h, int(math.ceil(w_item["bbox"][3] * sy_inv)))
        if wx1 > wx0 and wy1 > wy0:
            cv2.rectangle(word_mask, (max(0, wx0 - 1), max(0, wy0 - 1)), (min(img_w - 1, wx1 + 1), min(img_h - 1, wy1 + 1)), 255, -1)

    paper_diff = np.max(np.abs(bgr.astype(np.int16) - paper_bgr.astype(np.int16)), axis=2)
    crisp_ink = (
        (paper_diff > 28)
        | (cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 6) > 0)
    ).astype(np.uint8) * 255

    edges = cv2.Canny(gray, 45, 135)
    conn_src = cv2.bitwise_or(crisp_ink, edges)
    conn_src[table_mask > 0] = 0
    conn_src[word_mask > 0] = 0
    conn_src[photo_mask > 0] = 0
    conn_src[cv2.dilate(shape_fill_mask, np.ones((7, 7), np.uint8), iterations=1) > 0] = 0

    min_len = max(18, min(img_w, img_h) // 28)
    raw_lines = cv2.HoughLinesP(conn_src, 1, math.pi / 180.0, threshold=max(16, min_len), minLineLength=min_len, maxLineGap=6)
    connectors: list[dict] = []
    if raw_lines is None:
        return connectors

    segs = sorted(
        [tuple(int(v) for v in line[0]) for line in raw_lines],
        key=lambda s: math.hypot(s[2] - s[0], s[3] - s[1]),
        reverse=True,
    )
    kept: list[tuple[int, int, int, int]] = []
    for x1, y1, x2, y2 in segs:
        length = math.hypot(x2 - x1, y2 - y1)
        if length < min_len:
            continue
        # Verificar que realmente hay tinta a lo largo del segmento (>= 55%) y despeje alrededor sobre papel/fondo limpio
        n_samples = max(6, int(length // 2))
        xs_s = np.clip(np.round(np.linspace(x1, x2, n_samples)).astype(int), 0, img_w - 1)
        ys_s = np.clip(np.round(np.linspace(y1, y2, n_samples)).astype(int), 0, img_h - 1)
        hit_ratio = float(np.count_nonzero(cv2.dilate(ink_mask, np.ones((3, 3), np.uint8))[ys_s, xs_s])) / n_samples
        if hit_ratio < 0.55:
            continue
        if float(np.count_nonzero(photo_mask[ys_s, xs_s])) / n_samples > 0.20:
            continue

        # Exigir despeje uniforme a ambos lados del conector (fuera del espesor del asta; descarta bordes de fotos/texto)
        ux_s, uy_s = (x2 - x1) / max(1.0, length), (y2 - y1) / max(1.0, length)
        nx_s, ny_s = -uy_s, ux_s
        side_off = max(12, int(round(((sx_inv + sy_inv) / 2.0) * 4.5)))
        clear_hits = 0
        side_stds = []
        for frac in (0.25, 0.5, 0.75):
            mx = x1 + (x2 - x1) * frac
            my = y1 + (y2 - y1) * frac
            for sgn in (-1, 1):
                px_c = max(4, min(img_w - 5, int(round(mx + sgn * side_off * nx_s))))
                py_c = max(4, min(img_h - 5, int(round(my + sgn * side_off * ny_s))))
                if float(np.max(np.abs(bgr[py_c, px_c].astype(np.int16) - paper_bgr.astype(np.int16)))) <= 28.0:
                    clear_hits += 1
                side_patch = bgr[py_c - 4 : py_c + 5, px_c - 4 : px_c + 5]
                if side_patch.size:
                    side_stds.append(float(np.max(np.std(side_patch.reshape(-1, 3), axis=0))))
        if clear_hits < 3 or (side_stds and max(side_stds) > 36.0):
            continue

        angle = math.atan2(y2 - y1, x2 - x1)
        merged_dup = False
        for kx1, ky1, kx2, ky2 in kept:
            kangle = math.atan2(ky2 - ky1, kx2 - kx1)
            da = abs((angle - kangle + math.pi) % math.pi)
            if min(da, math.pi - da) < 0.14:
                kl = math.hypot(kx2 - kx1, ky2 - ky1)
                dist = abs((ky2 - ky1) * (x1 + x2) / 2.0 - (kx2 - kx1) * (y1 + y2) / 2.0 + kx2 * ky1 - ky2 * kx1) / max(1.0, kl)
                if dist <= 6.0 and not (max(x1, x2) < min(kx1, kx2) - 10 or min(x1, x2) > max(kx1, kx2) + 10 or max(y1, y2) < min(ky1, ky2) - 10 or min(y1, y2) > max(ky1, ky2) + 10):
                    merged_dup = True
                    break
        if not merged_dup:
            kept.append((x1, y1, x2, y2))

    exclude_mask = cv2.bitwise_or(
        shape_fill_mask,
        cv2.dilate(table_mask, np.ones((3, 3), np.uint8), iterations=1),
    )
    exclude_mask = cv2.bitwise_or(exclude_mask, cv2.bitwise_or(photo_mask, word_mask))
    clean_ink = cv2.bitwise_and(crisp_ink, cv2.bitwise_not(exclude_mask))
    pt_to_px = (sx_inv + sy_inv) / 2.0
    max_half = max(14, int(round(pt_to_px * 11.0)))

    for x1, y1, x2, y2 in kept[:60]:
        seg_len = max(1.0, math.hypot(x2 - x1, y2 - y1))
        ux_tmp, uy_tmp = (x2 - x1) / seg_len, (y2 - y1) / seg_len
        vx_tmp, vy_tmp = -uy_tmp, ux_tmp

        # Recentrar ligeramente el segmento sobre la linea media real del asta (corrige desvios de borde de HoughLinesP)
        off_shifts: list[float] = []
        scan_r = max(6, int(round(pt_to_px * 3.0)))
        for frac in (0.25, 0.40, 0.55, 0.70):
            mx, my = x1 + (x2 - x1) * frac, y1 + (y2 - y1) * frac
            hits = [
                off for off in range(-scan_r, scan_r + 1)
                if 0 <= int(round(mx + off * vx_tmp)) < img_w
                and 0 <= int(round(my + off * vy_tmp)) < img_h
                and clean_ink[int(round(my + off * vy_tmp)), int(round(mx + off * vx_tmp))] > 0
            ]
            if 1 <= len(hits) <= scan_r * 2:
                off_shifts.append(float(sum(hits)) / len(hits))
        if off_shifts:
            med_shift = float(np.median(off_shifts))
            x1 = max(0, min(img_w - 1, int(round(x1 + med_shift * vx_tmp))))
            y1 = max(0, min(img_h - 1, int(round(y1 + med_shift * vy_tmp))))
            x2 = max(0, min(img_w - 1, int(round(x2 + med_shift * vx_tmp))))
            y2 = max(0, min(img_h - 1, int(round(y2 + med_shift * vy_tmp))))
        if abs(y2 - y1) <= max(6, int(round(pt_to_px * 2.5))) and abs(x2 - x1) >= max(40, int(seg_len * 0.6)):
            ymid = int(round((y1 + y2) / 2.0))
            y1 = y2 = ymid
        elif abs(x2 - x1) <= max(6, int(round(pt_to_px * 2.5))) and abs(y2 - y1) >= max(40, int(seg_len * 0.6)):
            xmid = int(round((x1 + x2) / 2.0))
            x1 = x2 = xmid

        seg_len = max(1.0, math.hypot(x2 - x1, y2 - y1))
        ux_raw, uy_raw = (x2 - x1) / seg_len, (y2 - y1) / seg_len
        vx_raw, vy_raw = -uy_raw, ux_raw

        # Medir espesor base del asta en el tramo central
        shaft_samples: list[int] = []
        shaft_max_scan = max(8, int(round(pt_to_px * 4.5)))
        for frac in (0.30, 0.40, 0.50, 0.60, 0.70):
            mx, my = x1 + (x2 - x1) * frac, y1 + (y2 - y1) * frac
            p_c = 0
            for off in range(1, shaft_max_scan):
                tx, ty = int(round(mx + off * vx_raw)), int(round(my + off * vy_raw))
                if 0 <= tx < img_w and 0 <= ty < img_h and clean_ink[ty, tx] > 0:
                    p_c = off
                else:
                    break
            n_c = 0
            for off in range(1, shaft_max_scan):
                tx, ty = int(round(mx - off * vx_raw)), int(round(my - off * vy_raw))
                if 0 <= tx < img_w and 0 <= ty < img_h and clean_ink[ty, tx] > 0:
                    n_c = off
                else:
                    break
            shaft_samples.append(p_c + n_c + 1)
        shaft_span = max(3, int(round(float(np.median(shaft_samples)))))

        def _probe_arrowhead(px: int, py: int, ox: int, oy: int) -> tuple[bool, tuple[int, int]]:
            dx, dy = px - ox, py - oy
            ln = max(1.0, math.hypot(dx, dy))
            ux, uy = dx / ln, dy / ln
            vx, vy = -uy, ux

            probe_back = min(int(ln * 0.35), max(16, int(round(pt_to_px * 22.0))))
            probe_fwd_max = max(24, int(round(pt_to_px * 24.0)))
            fwd_limit = 0
            empty_run = 0
            for d in range(1, probe_fwd_max + 1, 2):
                cx, cy = int(round(px + d * ux)), int(round(py + d * uy))
                if not (0 <= cx < img_w and 0 <= cy < img_h) or exclude_mask[cy, cx] > 0:
                    break
                win_y0, win_y1 = max(0, cy - 2), min(img_h, cy + 3)
                win_x0, win_x1 = max(0, cx - 2), min(img_w, cx + 3)
                if np.any(clean_ink[win_y0:win_y1, win_x0:win_x1] > 0):
                    fwd_limit = d
                    empty_run = 0
                else:
                    empty_run += 2
                    if empty_run > 4:
                        break

            slices: list[tuple[int, int, int, int]] = []
            for d in range(-probe_back, fwd_limit + 1, 2):
                cx, cy = px + d * ux, py + d * uy
                ix, iy = int(round(cx)), int(round(cy))
                if not (0 <= ix < img_w and 0 <= iy < img_h) or exclude_mask[iy, ix] > 0:
                    continue
                win_y0, win_y1 = max(0, iy - 2), min(img_h, iy + 3)
                win_x0, win_x1 = max(0, ix - 2), min(img_w, ix + 3)
                if not np.any(clean_ink[win_y0:win_y1, win_x0:win_x1] > 0):
                    continue
                pos_max = 0
                for off in range(1, max_half + 1):
                    tx, ty = int(round(cx + off * vx)), int(round(cy + off * vy))
                    if not (0 <= tx < img_w and 0 <= ty < img_h) or exclude_mask[ty, tx] > 0:
                        break
                    if clean_ink[ty, tx] > 0:
                        pos_max = off
                neg_max = 0
                for off in range(1, max_half + 1):
                    tx, ty = int(round(cx - off * vx)), int(round(cy - off * vy))
                    if not (0 <= tx < img_w and 0 <= ty < img_h) or exclude_mask[ty, tx] > 0:
                        break
                    if clean_ink[ty, tx] > 0:
                        neg_max = off
                slices.append((d, pos_max, neg_max, pos_max + neg_max + 1))

            if len(slices) < 3:
                return False, (px, py)

            peak_idx = max(range(len(slices)), key=lambda idx: slices[idx][3])
            peak_d, p_off, n_off, peak_span = slices[peak_idx]
            wing_min = max(4, shaft_span // 2 + 2)
            if p_off < wing_min or n_off < wing_min:
                return False, (px, py)
            if min(p_off, n_off) < max(3, int(round(0.45 * max(p_off, n_off)))):
                return False, (px, py)
            if peak_span < max(shaft_span + 6, int(round(shaft_span * 1.9))):
                return False, (px, py)

            after = slices[peak_idx + 1 :]
            if not after:
                return False, (px, py)
            tip_d = after[-1][0]
            min_after_span = min(item[3] for item in after)
            if min_after_span > max(shaft_span + 1, int(round(peak_span * 0.55))):
                return False, (px, py)

            new_tip = (px, py)
            if tip_d > 0:
                tx_end = max(0, min(img_w - 1, int(round(px + tip_d * ux))))
                ty_end = max(0, min(img_h - 1, int(round(py + tip_d * uy))))
                new_tip = (tx_end, ty_end)
            return True, new_tip

        a_start, (ax1, ay1) = _probe_arrowhead(x1, y1, x2, y2)
        a_end, (ax2, ay2) = _probe_arrowhead(x2, y2, x1, y1)

        line_mask = np.zeros((img_h, img_w), dtype=np.uint8)
        cv2.line(line_mask, (ax1, ay1), (ax2, ay2), 255, thickness=3)
        line_px = bgr[line_mask > 0]
        stroke_rgb = _sample_stroke_style(bgr, line_px, paper_bgr)

        # Normalizar flechas simples en sentido p1 -> p2 para emitir a:tailEnd canonico
        if a_start and not a_end:
            ax1, ay1, ax2, ay2 = ax2, ay2, ax1, ay1
            a_start, a_end = False, True

        connectors.append(
            {
                "kind": "connector",
                "p1": (round(ax1 * sx, 2), round(ay1 * sy, 2)),
                "p2": (round(ax2 * sx, 2), round(ay2 * sy, 2)),
                "p1_px": (ax1, ay1),
                "p2_px": (ax2, ay2),
                "stroke_rgb": stroke_rgb,
                "stroke_pt": 1.5,
                "arrow_start": a_start,
                "arrow_end": a_end,
            }
        )
    return connectors


def _estimate_word_style(
    bgr: np.ndarray,
    ink_mask: np.ndarray,
    paper_bgr: np.ndarray,
    bbox_pt: tuple[float, float, float, float],
    pt_w: float,
    pt_h: float,
) -> tuple[int, bool]:
    img_h, img_w = bgr.shape[:2]
    sx_inv, sy_inv = img_w / pt_w, img_h / pt_h
    x0 = max(0, int(math.floor(bbox_pt[0] * sx_inv)))
    y0 = max(0, int(math.floor(bbox_pt[1] * sy_inv)))
    x1 = min(img_w, int(math.ceil(bbox_pt[2] * sx_inv)))
    y1 = min(img_h, int(math.ceil(bbox_pt[3] * sy_inv)))
    if x1 <= x0 or y1 <= y0:
        return 0x111111, False
    roi_bgr = bgr[y0:y1, x0:x1]
    # Estimar fondo local alrededor del perimetro de la palabra (soporta texto claro sobre cajas oscuras)
    bx0, by0, bx1, by1 = max(0, x0 - 2), max(0, y0 - 2), min(img_w, x1 + 2), min(img_h, y1 + 2)
    outer = bgr[by0:by1, bx0:bx1]
    if outer.shape[0] >= 4 and outer.shape[1] >= 4:
        rim = np.concatenate((outer[0, :], outer[-1, :], outer[:, 0], outer[:, -1]), axis=0)
        local_bg = np.median(rim, axis=0)
    else:
        local_bg = paper_bgr

    diff = np.max(np.abs(roi_bgr.astype(np.int16) - local_bg.astype(np.int16)), axis=2)
    fg = roi_bgr[diff > 26]
    if len(fg) == 0:
        fg = roi_bgr[diff > 16]
    if len(fg) == 0:
        color_int = 0x111111
    else:
        # Elegir los pixeles mas contrastados respecto al fondo local
        fg_diff = np.max(np.abs(fg.astype(np.int16) - local_bg.astype(np.int16)), axis=1)
        strong = fg[fg_diff >= np.percentile(fg_diff, 55)]
        med = np.median(strong if len(strong) else fg, axis=0)
        color_int = (int(round(med[2])) << 16) | (int(round(med[1])) << 8) | int(round(med[0]))

    # Deteccion aproximada de negrita usando espesor medio de trazo via DistanceTransform
    roi_bw = (diff > 26).astype(np.uint8) * 255
    is_bold = False
    if cv2.countNonZero(roi_bw) >= 12 and (y1 - y0) >= 8:
        dt = cv2.distanceTransform(roi_bw, cv2.DIST_L2, 3)
        pos = dt[roi_bw > 0]
        if len(pos):
            stroke_diam = 2.0 * float(np.percentile(pos, 75))
            ratio = stroke_diam / max(1.0, float(y1 - y0))
            is_bold = ratio >= 0.145
    return color_int, is_bold


def _extract_ocr_words(
    page: pdf.Page,
    bgr: np.ndarray,
    ink_mask: np.ndarray,
    long_rules_mask: np.ndarray,
    table_mask: np.ndarray,
    photo_mask: np.ndarray,
    paper_bgr: np.ndarray,
    pt_w: float,
    pt_h: float,
    config: dict,
    root: Path,
    ocr_mode: str,
) -> tuple[list[dict], bool, bool]:
    """Extrae palabras OCR limpias con color y peso reales; devuelve (words, ocr_applied, ocr_missing)."""
    img_h, img_w = bgr.shape[:2]
    languages = config["ocr_language"].split("+")
    ocr_available = all((root / "models" / f"{lang}.traineddata").is_file() for lang in languages)
    has_hidden_ocr = any(t.get("type") == 3 for t in page.get_texttrace())

    raw_words: list[tuple[float, float, float, float, str]] = []
    ocr_applied = False
    ocr_missing = False

    if ocr_mode != "existing_only" and ocr_available:
        # Limpiar trazos de cuadricula largos antes del OCR para evitar caracteres "|" / "_" espurios
        ocr_input = bgr.copy()
        ocr_input[long_rules_mask > 0] = paper_bgr
        rgb = cv2.cvtColor(ocr_input, cv2.COLOR_BGR2RGB)
        pix = pdf.Pixmap(pdf.csRGB, img_w, img_h, rgb.tobytes(), False)
        raw_pdf = pix.pdfocr_tobytes(language=config["ocr_language"], tessdata=str(root / "models"))
        with pdf.open(stream=raw_pdf, filetype="pdf") as ocr_doc:
            ocr_page = ocr_doc[0]
            opw, oph = ocr_page.rect.width, ocr_page.rect.height
            fx, fy = pt_w / max(1.0, opw), pt_h / max(1.0, oph)
            for w_item in ocr_page.get_text("words"):
                x0, y0, x1, y1, txt = float(w_item[0]) * fx, float(w_item[1]) * fy, float(w_item[2]) * fx, float(w_item[3]) * fy, str(w_item[4]).strip()
                if txt:
                    raw_words.append((x0, y0, x1, y1, txt))
        ocr_applied = True
    elif has_hidden_ocr:
        for w_item in page.get_text("words"):
            x0, y0, x1, y1, txt = float(w_item[0]), float(w_item[1]), float(w_item[2]), float(w_item[3]), str(w_item[4]).strip()
            if txt:
                raw_words.append((x0, y0, x1, y1, txt))
    elif not ocr_available:
        ocr_missing = True

    sx_inv, sy_inv = img_w / pt_w, img_h / pt_h
    cleaned_words: list[dict] = []
    for x0, y0, x1, y1, txt in raw_words:
        if x1 - x0 < 1.5 or y1 - y0 < 3.5:
            continue
        px0 = max(0, int(math.floor(x0 * sx_inv)))
        py0 = max(0, int(math.floor(y0 * sy_inv)))
        px1 = min(img_w, int(math.ceil(x1 * sx_inv)))
        py1 = min(img_h, int(math.ceil(y1 * sy_inv)))
        if px1 <= px0 or py1 <= py0:
            continue
        # Descartar ruido corto de puntuacion pegado a una regla de tabla
        if _SHORT_RULE_NOISE_RE.match(txt) and len(txt) <= 3:
            rule_overlap = cv2.countNonZero(long_rules_mask[py0:py1, px0:px1]) / max(1, (px1 - px0) * (py1 - py0))
            if rule_overlap > 0.35:
                continue
        # Descartar basura OCR esporadica sobre texturas/fotos altamente cromaticas (dilatando tinta 3x3 para evitar halos)
        patch_bgr = bgr[py0:py1, px0:px1]
        patch_fg = cv2.dilate(ink_mask[py0:py1, px0:px1], np.ones((3, 3), np.uint8), iterations=1)
        patch_bg = patch_bgr[patch_fg == 0]
        if len(patch_bg) >= 16 and float(np.max(np.std(patch_bg, axis=0))) > 42.0:
            continue
        photo_overlap = float(np.count_nonzero(photo_mask[py0:py1, px0:px1])) / max(1, (px1 - px0) * (py1 - py0))
        if photo_overlap > 0.35:
            patch_std = float(np.max(np.std(patch_bgr.reshape(-1, 3), axis=0))) if patch_bgr.size else 0.0
            bg_std = float(np.max(np.std(patch_bg, axis=0))) if len(patch_bg) >= 8 else patch_std
            if bg_std > 28.0 or patch_std > 35.0:
                continue
        color_int, is_bold = _estimate_word_style(bgr, ink_mask, paper_bgr, (x0, y0, x1, y1), pt_w, pt_h)
        h_pt = y1 - y0
        size_pt = max(6.5, min(54.0, round(h_pt * 0.78 * 2.0) / 2.0))
        cleaned_words.append(
            {
                "bbox": (x0, y0, x1, y1),
                "text": txt,
                "size": size_pt,
                "color": color_int,
                "bold": is_bold,
                "italic": False,
            }
        )

    return cleaned_words, ocr_applied, ocr_missing


def _words_to_lines(words: list[dict]) -> list[dict]:
    """Agrupa palabras por banda vertical Y en lineas compatibles con office_export."""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: ((w["bbox"][1] + w["bbox"][3]) / 2.0, w["bbox"][0]))
    row_groups: list[list[dict]] = []
    for word in ordered:
        wy0, wy1 = word["bbox"][1], word["bbox"][3]
        wymid = (wy0 + wy1) / 2.0
        wh = max(4.0, wy1 - wy0)
        placed = False
        for grp in reversed(row_groups[-6:]):
            gy0 = min(item["bbox"][1] for item in grp)
            gy1 = max(item["bbox"][3] for item in grp)
            gymid = (gy0 + gy1) / 2.0
            gh = max(4.0, gy1 - gy0)
            if abs(wymid - gymid) <= max(wh, gh) * 0.45 and min(wh, gh) / max(wh, gh) >= 0.45:
                grp.append(word)
                placed = True
                break
        if not placed:
            row_groups.append([word])

    # Estabilizar tamaños tipograficos cercanos para evitar fluctuaciones entre renglones vecinos
    lines_out: list[dict] = []
    for grp in row_groups:
        grp.sort(key=lambda w: w["bbox"][0])
        median_size = float(np.median([w["size"] for w in grp]))
        # Dividir una misma banda Y en segmentos independientes si existe gran salto horizontal (>= 2.8 * size)
        segments: list[list[dict]] = [[grp[0]]]
        for w in grp[1:]:
            prev = segments[-1][-1]
            gap = w["bbox"][0] - prev["bbox"][2]
            if gap > max(18.0, median_size * 2.5):
                segments.append([w])
            else:
                segments[-1].append(w)

        for seg in segments:
            spans: list[dict] = []
            # Unir palabras contiguas del mismo estilo en un mismo span limpio
            cur_words: list[dict] = [seg[0]]
            for w in seg[1:]:
                prev_w = cur_words[-1]
                same_style = (w["bold"] == prev_w["bold"] and w["color"] == prev_w["color"] and abs(w["size"] - prev_w["size"]) <= 2.5)
                if same_style:
                    cur_words.append(w)
                else:
                    spans.append(_words_to_span(cur_words, median_size))
                    cur_words = [w]
            spans.append(_words_to_span(cur_words, median_size))
            lx0 = min(sp["bbox"][0] for sp in spans)
            ly0 = min(sp["bbox"][1] for sp in spans)
            lx1 = max(sp["bbox"][2] for sp in spans)
            ly1 = max(sp["bbox"][3] for sp in spans)
            lines_out.append({"bbox": (lx0, ly0, lx1, ly1), "dir": (1.0, 0.0), "spans": spans})

    lines_out.sort(key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
    return lines_out


def _words_to_span(words: list[dict], line_size: float) -> dict:
    x0 = min(w["bbox"][0] for w in words)
    y0 = min(w["bbox"][1] for w in words)
    x1 = max(w["bbox"][2] for w in words)
    y1 = max(w["bbox"][3] for w in words)
    text = " ".join(w["text"] for w in words)
    size = max(w["size"] for w in words) if len(words) == 1 else line_size
    flags = 16 if any(w["bold"] for w in words) else 0
    return {
        "bbox": (x0, y0, x1, y1),
        "origin": (x0, y1 - max(1.0, (y1 - y0) * 0.18)),
        "text": text,
        "font": "Arial-Bold" if flags & 16 else "Arial",
        "size": float(round(size * 2.0) / 2.0),
        "flags": flags,
        "color": words[0]["color"],
        "chars": [],
    }


def _detect_borderless_ocr_tables(
    words: list[dict],
    ruled_tables: list[dict],
    diagram_shapes: list[dict],
    pt_w: float,
    pt_h: float,
) -> list[dict]:
    """Detecta tablas sin bordes a partir de alineacion columnar de palabras OCR."""
    def _center_in_any(box: tuple[float, float, float, float], targets: list[dict]) -> bool:
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
        for item in targets:
            bx0, by0, bx1, by1 = item["bbox"]
            if bx0 <= cx <= bx1 and by0 <= cy <= by1:
                return True
        return False

    free_words = [
        w for w in words
        if not _center_in_any(w["bbox"], ruled_tables) and not _center_in_any(w["bbox"], diagram_shapes)
    ]
    if len(free_words) < 4:
        return []

    free_words.sort(key=lambda w: (round(w["bbox"][1], 1), w["bbox"][0]))
    rows_words: list[list[dict]] = []
    for w in free_words:
        wy = (w["bbox"][1] + w["bbox"][3]) / 2.0
        if not rows_words:
            rows_words.append([w])
        else:
            prev_y = np.mean([(it["bbox"][1] + it["bbox"][3]) / 2.0 for it in rows_words[-1]])
            if abs(wy - prev_y) <= max(5.0, (w["bbox"][3] - w["bbox"][1]) * 0.55):
                rows_words[-1].append(w)
            else:
                rows_words.append([w])

    row_cells: list[list[tuple[float, float, float, float]]] = []
    for rwords in rows_words:
        rwords.sort(key=lambda w: w["bbox"][0])
        cells: list[tuple[float, float, float, float]] = []
        cur = [rwords[0]]
        for w in rwords[1:]:
            if w["bbox"][0] - cur[-1]["bbox"][2] >= 16.0:
                cells.append((
                    min(it["bbox"][0] for it in cur),
                    min(it["bbox"][1] for it in cur),
                    max(it["bbox"][2] for it in cur),
                    max(it["bbox"][3] for it in cur),
                ))
                cur = [w]
            else:
                cur.append(w)
        cells.append((
            min(it["bbox"][0] for it in cur),
            min(it["bbox"][1] for it in cur),
            max(it["bbox"][2] for it in cur),
            max(it["bbox"][3] for it in cur),
        ))
        row_cells.append(cells)

    def _row_gap_ok(prev_rc: list[tuple[float, float, float, float]], next_rc: list[tuple[float, float, float, float]]) -> bool:
        prev_bot = max(c[3] for c in prev_rc)
        prev_top = min(c[1] for c in prev_rc)
        next_top = min(c[1] for c in next_rc)
        row_h = max(8.0, prev_bot - prev_top)
        if next_top - prev_bot > max(38.0, row_h * 2.8):
            return False
        # No agrupar filas a ambos lados de una tabla con bordes o figura intermedia
        for blk in ruled_tables + diagram_shapes:
            bx0, by0, bx1, by1 = blk["bbox"]
            bmid_y = (by0 + by1) / 2.0
            if prev_bot <= bmid_y <= next_top:
                return False
        return True

    runs: list[list[list[tuple[float, float, float, float]]]] = []
    cur_run: list[list[tuple[float, float, float, float]]] = []
    for rc in row_cells:
        if len(rc) >= 2:
            if cur_run and not _row_gap_ok(cur_run[-1], rc):
                if len(cur_run) >= 2:
                    runs.append(cur_run)
                cur_run = [rc]
            else:
                cur_run.append(rc)
        else:
            if len(cur_run) >= 2:
                runs.append(cur_run)
            cur_run = []
    if len(cur_run) >= 2:
        runs.append(cur_run)

    out_tables: list[dict] = []
    for run in runs:
        anchors: list[float] = []
        anchor_hits: list[int] = []
        for rc in run:
            seen_row: set[int] = set()
            for cbox in rc:
                matched = next((idx for idx, ax in enumerate(anchors) if abs(cbox[0] - ax) <= 22.0), None)
                if matched is None:
                    anchors.append(cbox[0])
                    anchor_hits.append(1)
                    seen_row.add(len(anchors) - 1)
                elif matched not in seen_row:
                    anchor_hits[matched] += 1
                    seen_row.add(matched)
        order = sorted(range(len(anchors)), key=lambda i: anchors[i])
        anchors = [anchors[i] for i in order if anchor_hits[i] >= 2]
        if len(anchors) < 2 or len(anchors) > 12:
            continue
        # Confirmar que al menos 2 filas llenan columnas compatibles
        x_min = max(0.0, min(c[0] for rc in run for c in rc) - 4.0)
        x_max = min(pt_w, max(c[2] for rc in run for c in rc) + 4.0)
        xs = [round(x_min, 2)]
        for col_idx in range(1, len(anchors)):
            prev_right = [
                max(c[2] for c in rc if min(range(len(anchors)), key=lambda i: abs(c[0] - anchors[i])) == col_idx - 1)
                for rc in run if any(min(range(len(anchors)), key=lambda i: abs(c[0] - anchors[i])) == col_idx - 1 for c in rc)
            ]
            split_x = ((max(prev_right) if prev_right else anchors[col_idx] - 8.0) + anchors[col_idx]) / 2.0
            split_x = max(xs[-1] + 8.0, min(anchors[col_idx], split_x))
            xs.append(round(split_x, 2))
        xs.append(round(max(xs[-1] + 12.0, x_max), 2))

        ys = [round(max(0.0, min(c[1] for c in run[0]) - 3.0), 2)]
        for r_idx in range(1, len(run)):
            prev_bot = max(c[3] for c in run[r_idx - 1])
            next_top = min(c[1] for c in run[r_idx])
            ys.append(round(max(ys[-1] + 6.0, (prev_bot + next_top) / 2.0), 2))
        ys.append(round(min(pt_h, max(ys[-1] + 8.0, max(c[3] for c in run[-1]) + 3.0)), 2))

        grid_cells = []
        for r in range(len(ys) - 1):
            for c in range(len(xs) - 1):
                grid_cells.append((r, c, r, c, (xs[c], ys[r], xs[c + 1], ys[r + 1])))

        out_tables.append(
            {
                "bbox": (xs[0], ys[0], xs[-1], ys[-1]),
                "xs": xs,
                "ys": ys,
                "cells": grid_cells,
                "fills": {},
                "border_rgb": "CCCCCC",
                "border_pt": 0.5,
                "mode": "borderless",
            }
        )
    return out_tables


def _group_paragraphs(lines: list[dict], exclude_rects: list[pdf.Rect]) -> list[dict]:
    """Agrupa renglones contiguos fuera de tablas/figuras embebidas en bloques de parrafo editables."""
    free_lines = [
        ln for ln in lines
        if not any(rect.contains((pdf.Rect(ln["bbox"]).tl + pdf.Rect(ln["bbox"]).br) / 2) for rect in exclude_rects)
    ]
    if not free_lines:
        return []

    paragraphs: list[dict] = []
    for ln in free_lines:
        lb = ln["bbox"]
        lh = max(6.0, lb[3] - lb[1])
        lsize = float(np.median([sp["size"] for sp in ln["spans"]]))
        placed = False
        if paragraphs:
            prev = paragraphs[-1]
            pb = prev["bbox"]
            psize = prev["size"]
            vgap = lb[1] - pb[3]
            h_aligned = abs(lb[0] - pb[0]) <= max(18.0, lsize * 1.8)
            h_centered = abs(((lb[0] + lb[2]) / 2.0) - ((pb[0] + pb[2]) / 2.0)) <= 16.0
            same_tier = abs(lsize - psize) <= max(2.0, lsize * 0.22)
            # No combinar lineas de columnas totalmente independientes separadas horizontalmente
            x_overlap = min(lb[2], pb[2]) - max(lb[0], pb[0]) > -20.0
            if -3.0 <= vgap <= max(10.0, max(lh, prev["line_h"]) * 0.85) and (h_aligned or h_centered) and same_tier and x_overlap:
                prev["lines"].append(ln)
                prev["bbox"] = (min(pb[0], lb[0]), min(pb[1], lb[1]), max(pb[2], lb[2]), max(pb[3], lb[3]))
                prev["line_h"] = (prev["line_h"] + lh) / 2.0
                placed = True
        if not placed:
            paragraphs.append({"bbox": lb, "lines": [ln], "size": lsize, "line_h": lh})
    return paragraphs


def _build_clean_backdrop(
    bgr: np.ndarray,
    paper_bgr: np.ndarray,
    words: list[dict],
    tables: list[dict],
    shapes: list[dict],
    connectors: list[dict],
    pt_w: float,
    pt_h: float,
) -> bytes | None:
    """Construye fondo residual sin texto ni tablas ni diagramas ya vectorizados."""
    img_h, img_w = bgr.shape[:2]
    sx_inv, sy_inv = img_w / pt_w, img_h / pt_h

    clean = bgr.copy()
    erase_mask = np.zeros((img_h, img_w), dtype=np.uint8)

    # 1. Borrar tablas reconstruidas por completo sobre tono papel (elimina trazos y rellenos duplicados)
    for tbl in tables:
        bx0, by0, bx1, by1 = tbl["bbox"]
        px0 = max(0, int(math.floor(bx0 * sx_inv)) - 3)
        py0 = max(0, int(math.floor(by0 * sy_inv)) - 3)
        px1 = min(img_w, int(math.ceil(bx1 * sx_inv)) + 4)
        py1 = min(img_h, int(math.ceil(by1 * sy_inv)) + 4)
        clean[py0:py1, px0:px1] = paper_bgr
        erase_mask[py0:py1, px0:px1] = 255

    # 2. Borrar formas y conectores vectorizados
    for sh in shapes:
        bx0, by0, bx1, by1 = sh.get("bbox_px") or (
            int(math.floor(sh["bbox"][0] * sx_inv)),
            int(math.floor(sh["bbox"][1] * sy_inv)),
            int(math.ceil(sh["bbox"][2] * sx_inv)),
            int(math.ceil(sh["bbox"][3] * sy_inv)),
        )
        px0, py0 = max(0, bx0 - 3), max(0, by0 - 3)
        px1, py1 = min(img_w, bx1 + 4), min(img_h, by1 + 4)
        clean[py0:py1, px0:px1] = paper_bgr
        erase_mask[py0:py1, px0:px1] = 255

    for conn in connectors:
        p1x, p1y = conn.get("p1_px", (int(conn["p1"][0] * sx_inv), int(conn["p1"][1] * sy_inv)))
        p2x, p2y = conn.get("p2_px", (int(conn["p2"][0] * sx_inv), int(conn["p2"][1] * sy_inv)))
        cv2.line(clean, (p1x, p1y), (p2x, p2y), tuple(int(c) for c in paper_bgr), thickness=9)
        cv2.line(erase_mask, (p1x, p1y), (p2x, p2y), 255, thickness=9)
        ln_px = max(1.0, math.hypot(p2x - p1x, p2y - p1y))
        ux, uy = (p2x - p1x) / ln_px, (p2y - p1y) / ln_px
        vx, vy = -uy, ux
        head_len = max(14.0, (sx_inv + sy_inv) * 10.0)
        head_half = max(10.0, (sx_inv + sy_inv) * 5.5)
        for is_head, (tx, ty), d_sgn in (
            (conn.get("arrow_start"), (p1x, p1y), -1.0),
            (conn.get("arrow_end"), (p2x, p2y), 1.0),
        ):
            if not is_head:
                continue
            bx, by = tx - head_len * ux * d_sgn, ty - head_len * uy * d_sgn
            tri = np.array(
                [
                    [int(round(tx + 3 * ux * d_sgn)), int(round(ty + 3 * uy * d_sgn))],
                    [int(round(bx + head_half * vx)), int(round(by + head_half * vy))],
                    [int(round(bx - head_half * vx)), int(round(by - head_half * vy))],
                ],
                dtype=np.int32,
            )
            cv2.fillConvexPoly(clean, tri, tuple(int(c) for c in paper_bgr))
            cv2.fillConvexPoly(erase_mask, tri, 255)

    # 3. Inpainting de palabras OCR sobre fondo local para preservar fotos cercanas sin halos
    text_mask = np.zeros((img_h, img_w), dtype=np.uint8)
    for w in words:
        bx0, by0, bx1, by1 = w["bbox"]
        px0 = max(0, int(math.floor(bx0 * sx_inv)) - 2)
        py0 = max(0, int(math.floor(by0 * sy_inv)) - 2)
        px1 = min(img_w, int(math.ceil(bx1 * sx_inv)) + 3)
        py1 = min(img_h, int(math.ceil(by1 * sy_inv)) + 3)
        cv2.rectangle(text_mask, (px0, py0), (px1, py1), 255, -1)
    text_mask[erase_mask > 0] = 0
    if cv2.countNonZero(text_mask) > 0:
        clean = cv2.inpaint(clean, text_mask, 3, cv2.INPAINT_TELEA)

    # Verificar si sobreviven graficos / fotografias genuinas no vectorizadas respecto al tono papel
    residual_diff = np.max(np.abs(clean.astype(np.int16) - paper_bgr.astype(np.int16)), axis=2)
    residual_mask = (residual_diff > 24).astype(np.uint8) * 255
    residual_mask = cv2.morphologyEx(residual_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    residual_count = cv2.countNonZero(residual_mask)
    if residual_count < max(120, int(img_w * img_h * 0.0025)):
        return None

    rgb = cv2.cvtColor(clean, cv2.COLOR_BGR2RGB)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


def _analyze_bgr_region(
    bgr_raw: np.ndarray,
    pt_w: float,
    pt_h: float,
    config: dict,
    root: Path,
    *,
    page: pdf.Page | None = None,
    preprocess: str = "auto",
    vectorize_tables: bool = True,
    vectorize_diagrams: bool = True,
    ocr_mode: str = "auto",
) -> dict[str, Any]:
    """Ejecuta analisis visual + OCR completo sobre un recorte o pagina rasterizada."""
    bgr, paper_bgr = _preprocess_bgr(bgr_raw, preprocess, config["max_render_pixels"])

    ink_mask, horiz_lines, vert_lines, long_rules = _build_line_and_ink_masks(bgr, paper_bgr)
    ruled_tables: list[dict] = []
    table_mask = np.zeros(bgr.shape[:2], dtype=np.uint8)
    if vectorize_tables:
        ruled_tables, table_mask = _detect_raster_tables(bgr, ink_mask, horiz_lines, vert_lines, paper_bgr, pt_w, pt_h)

    diagram_shapes: list[dict] = []
    shape_fill_mask = np.zeros(bgr.shape[:2], dtype=np.uint8)
    if vectorize_diagrams:
        diagram_shapes, shape_fill_mask = _detect_raster_containers(
            bgr, ink_mask, table_mask, paper_bgr, pt_w, pt_h
        )

    photo_mask = _detect_photo_artwork_mask(bgr, table_mask, shape_fill_mask, paper_bgr)

    # Enmascarar trazos largos y formas ya extraidas antes del OCR global para lectura nitida sin bordes
    ocr_erase = cv2.bitwise_or(long_rules, shape_fill_mask)
    if page is not None:
        words, ocr_applied, ocr_missing = _extract_ocr_words(
            page, bgr, ink_mask, ocr_erase, table_mask, photo_mask, paper_bgr, pt_w, pt_h, config, root, ocr_mode
        )
    else:
        with pdf.open() as tmp_doc:
            tmp_page = tmp_doc.new_page(width=pt_w, height=pt_h)
            words, ocr_applied, ocr_missing = _extract_ocr_words(
                tmp_page, bgr, ink_mask, ocr_erase, table_mask, photo_mask, paper_bgr, pt_w, pt_h, config, root, ocr_mode
            )

    shape_words, shape_ocr_used = _extract_shape_embedded_ocr(
        bgr, ink_mask, paper_bgr, diagram_shapes, pt_w, pt_h, config, root, ocr_mode
    )
    ocr_applied = ocr_applied or shape_ocr_used

    diagram_connectors: list[dict] = []
    if vectorize_diagrams:
        # Limpiar cualquier artefacto binario que haya quedado de formas/tablas pero excluyendo letras genuinas
        free_and_shape_words = words + shape_words
        diagram_connectors = _detect_raster_connectors(
            bgr, ink_mask, table_mask, shape_fill_mask, photo_mask, free_and_shape_words, paper_bgr, pt_w, pt_h
        )
        # Limpiar posibles tokens residuales de flechas ("->", ">", ">=") que solapen conectores detectados
        if diagram_connectors and words:
            filtered_words: list[dict] = []
            for w in words:
                wb = pdf.Rect(w["bbox"])
                txt = w["text"].strip()
                near_conn = any(
                    pdf.Rect(
                        min(c["p1"][0], c["p2"][0]) - 10,
                        min(c["p1"][1], c["p2"][1]) - 10,
                        max(c["p1"][0], c["p2"][0]) + 10,
                        max(c["p1"][1], c["p2"][1]) + 10,
                    ).intersects(wb)
                    for c in diagram_connectors
                )
                if near_conn and len(txt) <= 5 and not any(ch.isalnum() for ch in txt):
                    continue
                filtered_words.append(w)
            words = filtered_words

    if ocr_missing and not (words or shape_words) and not ruled_tables and not diagram_shapes:
        raise ProcessingError(
            "Faltan los modelos OCR locales (models/*.traineddata). Ejecute deploy\\install-ocr.ps1.",
            503,
        )

    borderless_tables: list[dict] = []
    if vectorize_tables and words:
        borderless_tables = _detect_borderless_ocr_tables(words, ruled_tables, diagram_shapes, pt_w, pt_h)

    all_tables = ruled_tables + borderless_tables
    all_lines = _words_to_lines(words)

    # Asociar lineas adicionales si alguna linea suelta cayo dentro de una figura grande de diagrama
    table_rects = [pdf.Rect(t["bbox"]) for t in all_tables]
    assigned_line_ids: set[int] = set()
    for shape in diagram_shapes:
        if shape.get("embedded_lines"):
            continue
        srect = pdf.Rect(shape["bbox"])
        if srect.width > pt_w * 0.55 or srect.height > pt_h * 0.45:
            continue
        padded_srect = srect + (-3, -3, 3, 3)
        inner = []
        for idx, ln in enumerate(all_lines):
            if idx in assigned_line_ids:
                continue
            lrect = pdf.Rect(ln["bbox"])
            center = (lrect.tl + lrect.br) / 2.0
            if srect.contains(center) and padded_srect.contains(lrect) and not any(tr.contains(center) for tr in table_rects):
                inner.append(ln)
                assigned_line_ids.add(idx)
        shape["embedded_lines"] = inner

    remaining_lines = [ln for idx, ln in enumerate(all_lines) if idx not in assigned_line_ids]
    paragraphs = _group_paragraphs(remaining_lines, table_rects)

    backdrop_png = _build_clean_backdrop(
        bgr, paper_bgr, words + shape_words, ruled_tables, diagram_shapes, diagram_connectors, pt_w, pt_h
    )

    # Eliminar campos temporales pesados (arrays NumPy) de shapes antes de serializar
    for sh in diagram_shapes:
        sh.pop("contour", None)
        sh.pop("interior_eroded", None)
        sh.pop("fill_bgr", None)

    return {
        "native": False,
        "fallback": False,
        "width_pt": pt_w,
        "height_pt": pt_h,
        "paper_rgb": _to_hex(paper_bgr, is_bgr=True),
        "lines": remaining_lines,
        "tables": all_tables,
        "diagrams": diagram_shapes,
        "connectors": diagram_connectors,
        "paragraphs": paragraphs,
        "backdrop_png": backdrop_png,
        "ocr_applied": ocr_applied,
        "ocr_missing": ocr_missing,
    }


def analyze_scanned_page_for_office(
    page: pdf.Page,
    dpi: int,
    config: dict,
    root: Path,
    *,
    preprocess: str = "auto",
    vectorize_tables: bool = True,
    vectorize_diagrams: bool = True,
    ocr_mode: str = "auto",
) -> dict[str, Any]:
    """Analiza una pagina escaneada (o hibrida) extrayendo texto OCR, tablas y diagramas vectoriales."""
    visible = [t["bbox"] for t in page.get_texttrace() if t.get("type") != 3 and t.get("opacity", 1) > 0]
    drawings = page.get_drawings()
    pt_w, pt_h = float(page.rect.width), float(page.rect.height)

    # Si es pagina vectorial nativa sin rotacion y no se fuerza OCR ni vectorizacion raster
    full_img = any((pdf.Rect(info["bbox"]) & page.rect).get_area() > page.rect.get_area() * 0.85 for info in page.get_image_info())
    is_scan_like = (not visible) or bool(page.rotation) or (full_img and len(drawings) < 4) or ocr_mode == "force"
    if not is_scan_like:
        from office_export import page_layout

        native = page_layout(page, config)
        if not native["fallback"]:
            exclude = [pdf.Rect(t["bbox"]) for t in native["tables"]]
            return {
                "native": True,
                "fallback": False,
                "width_pt": pt_w,
                "height_pt": pt_h,
                "paper_rgb": "FFFFFF",
                "lines": native["lines"],
                "tables": native["tables"],
                "diagrams": [],
                "connectors": [],
                "paragraphs": _group_paragraphs(
                    [ln for ln in native["lines"] if tuple(ln["dir"]) == (1.0, 0.0)],
                    exclude,
                ),
                "backdrop_png": None,
                "ocr_applied": False,
                "ocr_missing": False,
            }

    max_working_pixels = min(config["max_render_pixels"], 4_500_000)
    est_pixels = math.ceil(pt_w * dpi / 72.0) * math.ceil(pt_h * dpi / 72.0)
    eff_dpi = dpi
    if est_pixels > max_working_pixels:
        eff_dpi = max(110, int(dpi * math.sqrt(max_working_pixels / max(1, est_pixels))))

    pix = render(page, eff_dpi, config)
    raw_rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
    bgr_raw = cv2.cvtColor(raw_rgb, cv2.COLOR_RGB2BGR)
    bgr_norm, upright_w, upright_h, _ = _normalize_orientation_bgr(bgr_raw, int(page.rotation or 0), pt_w, pt_h)
    return _analyze_bgr_region(
        bgr_norm,
        upright_w,
        upright_h,
        config,
        root,
        page=page,
        preprocess=preprocess,
        vectorize_tables=vectorize_tables,
        vectorize_diagrams=vectorize_diagrams,
        ocr_mode=ocr_mode,
    )


def _hex_to_rgb_unit(hex_color: str) -> tuple[float, float, float]:
    clean = hex_color.strip().lstrip("#")
    if len(clean) != 6:
        return (0.1, 0.1, 0.1)
    return tuple(int(clean[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _draw_vector_analysis_on_pdf_page(
    target_page: pdf.Page,
    analysis: dict[str, Any],
    stats: dict[str, int],
    *,
    ox: float = 0.0,
    oy: float = 0.0,
    paint_paper_bg: bool = True,
) -> None:
    """Dibuja fondo residual, diagramas, conectores, tablas y texto OCR en una pagina PDF."""
    paper = _hex_to_rgb_unit(analysis["paper_rgb"])
    region_rect = pdf.Rect(ox, oy, ox + analysis["width_pt"], oy + analysis["height_pt"])
    if paint_paper_bg:
        bg_shape = target_page.new_shape()
        bg_shape.draw_rect(region_rect)
        bg_shape.finish(color=None, fill=paper)
        bg_shape.commit()

    if analysis["backdrop_png"]:
        target_page.insert_image(region_rect, stream=analysis["backdrop_png"], overlay=True)

    # Formas vectoriales de diagramas
    for sh in analysis["diagrams"]:
        shape = target_page.new_shape()
        bx0, by0, bx1, by1 = sh["bbox"]
        rect = pdf.Rect(ox + bx0, oy + by0, ox + bx1, oy + by1)
        fill_u = _hex_to_rgb_unit(sh["fill_rgb"]) if sh.get("fill_rgb") else None
        stroke_u = _hex_to_rgb_unit(sh["stroke_rgb"]) if sh.get("stroke_rgb") else None
        if sh["kind"] == "oval":
            shape.draw_oval(rect)
        elif sh["kind"] == "round_rect":
            shape.draw_rect(rect, radius=0.12)
        elif sh["kind"] in ("diamond", "polygon") and len(sh.get("points_pt", [])) >= 3:
            shape.draw_polyline([pdf.Point(ox + x, oy + y) for x, y in sh["points_pt"]])
            shape.finish(color=stroke_u, fill=fill_u, width=sh.get("stroke_pt", 1.25), closePath=True)
            shape.commit()
            stats["diagrams"] += 1
            continue
        else:
            shape.draw_rect(rect)
        shape.finish(color=stroke_u, fill=fill_u, width=sh.get("stroke_pt", 1.25))
        shape.commit()
        stats["diagrams"] += 1

    # Conectores / flechas vectoriales
    for conn in analysis["connectors"]:
        shape = target_page.new_shape()
        p1 = pdf.Point(ox + conn["p1"][0], oy + conn["p1"][1])
        p2 = pdf.Point(ox + conn["p2"][0], oy + conn["p2"][1])
        shape.draw_line(p1, p2)
        stroke_u = _hex_to_rgb_unit(conn["stroke_rgb"])
        shape.finish(color=stroke_u, width=conn.get("stroke_pt", 1.5))
        if conn.get("arrow_end") or conn.get("arrow_start"):
            dx, dy = p2.x - p1.x, p2.y - p1.y
            ln = max(1.0, math.hypot(dx, dy))
            ux, uy = dx / ln, dy / ln
            px, py = -uy, ux
            for tip, dir_s in ([(p2, 1.0)] if conn.get("arrow_end") else []) + ([(p1, -1.0)] if conn.get("arrow_start") else []):
                base = pdf.Point(tip.x - 7.0 * ux * dir_s, tip.y - 7.0 * uy * dir_s)
                w1 = pdf.Point(base.x + 3.5 * px, base.y + 3.5 * py)
                w2 = pdf.Point(base.x - 3.5 * px, base.y - 3.5 * py)
                shape.draw_polyline([tip, w1, w2])
                shape.finish(color=stroke_u, fill=stroke_u, closePath=True)
        shape.commit()
        stats["connectors"] += 1

    # Tablas vectoriales con relleno y rejilla limpia (respetando celdas combinadas)
    for tbl in analysis["tables"]:
        for row, col, _, _, crect in tbl["cells"]:
            fill_hex = tbl.get("fills", {}).get((row, col))
            if fill_hex:
                f_shape = target_page.new_shape()
                f_shape.draw_rect(pdf.Rect(ox + crect[0], oy + crect[1], ox + crect[2], oy + crect[3]))
                f_shape.finish(color=None, fill=_hex_to_rgb_unit(fill_hex))
                f_shape.commit()
        if tbl.get("mode") == "ruled":
            stroke_u = _hex_to_rgb_unit(tbl.get("border_rgb", "222222"))
            border_w = tbl.get("border_pt", 1.0)
            segs: set[tuple[float, float, float, float]] = set()
            for _, _, _, _, crect in tbl["cells"]:
                x0, y0, x1, y1 = [round(v, 2) for v in crect]
                segs.add((x0, y0, x1, y0))
                segs.add((x0, y1, x1, y1))
                segs.add((x0, y0, x0, y1))
                segs.add((x1, y0, x1, y1))
            for sx0, sy0, sx1, sy1 in sorted(segs):
                l_shape = target_page.new_shape()
                l_shape.draw_line(pdf.Point(ox + sx0, oy + sy0), pdf.Point(ox + sx1, oy + sy1))
                l_shape.finish(color=stroke_u, width=border_w)
                l_shape.commit()
        stats["tables"] += 1

    # Texto OCR reconstruido como texto real vectorial editable/buscable
    all_text_lines = list(analysis["lines"])
    for sh in analysis["diagrams"]:
        all_text_lines.extend(sh.get("embedded_lines", []))
    for ln in all_text_lines:
        for sp in ln["spans"]:
            txt = sp["text"].strip()
            if not txt:
                continue
            c_int = int(sp.get("color", 0))
            col_u = (((c_int >> 16) & 255) / 255.0, ((c_int >> 8) & 255) / 255.0, (c_int & 255) / 255.0)
            font_code = "hebo" if (sp.get("flags", 0) & 16) else "helv"
            spx, spy = sp.get("origin", (sp["bbox"][0], sp["bbox"][3] - 1.5))
            target_page.insert_text((ox + spx, oy + spy), txt, fontname=font_code, fontsize=sp["size"], color=col_u)
    if analysis["ocr_applied"] or all_text_lines:
        stats["ocr_pages"] += 1


def refine_pdf_scans_to_vector(
    doc: pdf.Document,
    selected: list[int],
    output: Path,
    config: dict,
    root: Path,
    options: dict,
) -> dict[str, Any]:
    """Reconstruye paginas escaneadas a un PDF vectorial limpio con OCR buscable y trazos editables."""
    raw_dpi = options.get("ocr_dpi", options.get("dpi", 200))
    dpi = integer(200 if raw_dpi in (None, "") else raw_dpi, 100, 300, "DPI")
    preprocess = str(options.get("preprocess", "auto"))
    vec_tables = bool(options.get("vectorize_tables", True))
    vec_diagrams = bool(options.get("vectorize_diagrams", True))
    ocr_mode = str(options.get("ocr_mode", "auto"))
    refine_embedded = bool(options.get("refine_embedded_images", False))

    stats = {"pages": len(selected), "tables": 0, "diagrams": 0, "connectors": 0, "ocr_pages": 0}
    with pdf.open() as out_doc:
        for pno in selected:
            page = doc[pno]
            analysis = analyze_scanned_page_for_office(
                page,
                dpi,
                config,
                root,
                preprocess=preprocess,
                vectorize_tables=vec_tables,
                vectorize_diagrams=vec_diagrams,
                ocr_mode=ocr_mode,
            )
            if analysis["native"]:
                out_doc.insert_pdf(doc, from_page=pno, to_page=pno)
                if refine_embedded:
                    dest_page = out_doc[-1]
                    visible = [t["bbox"] for t in dest_page.get_texttrace() if t.get("type") != 3 and t.get("opacity", 1) > 0]
                    for info in dest_page.get_image_info():
                        irec = pdf.Rect(info["bbox"]) & dest_page.rect
                        if irec.width < 90 or irec.height < 60:
                            continue
                        if any(pdf.Rect(tb).intersects(irec) for tb in visible):
                            continue
                        pixels = math.ceil(irec.width * dpi / 72) * math.ceil(irec.height * dpi / 72)
                        if pixels > config["max_render_pixels"]:
                            continue
                        pix = dest_page.get_pixmap(clip=irec, dpi=dpi, colorspace=pdf.csRGB, alpha=False)
                        raw_rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
                        bgr_crop = cv2.cvtColor(raw_rgb, cv2.COLOR_RGB2BGR)
                        sub = _analyze_bgr_region(
                            bgr_crop,
                            irec.width,
                            irec.height,
                            config,
                            root,
                            page=None,
                            preprocess="none" if preprocess == "auto" else preprocess,
                            vectorize_tables=vec_tables,
                            vectorize_diagrams=vec_diagrams,
                            ocr_mode=ocr_mode,
                        )
                        if sub["tables"] or sub["diagrams"] or sub["lines"]:
                            dest_page.add_redact_annot(irec, fill=False)
                            dest_page.apply_redactions(
                                images=pdf.PDF_REDACT_IMAGE_REMOVE,
                                graphics=0,
                            )
                            _draw_vector_analysis_on_pdf_page(
                                dest_page, sub, stats, ox=irec.x0, oy=irec.y0, paint_paper_bg=True
                            )
                continue

            new_page = out_doc.new_page(width=analysis["width_pt"], height=analysis["height_pt"])
            _draw_vector_analysis_on_pdf_page(new_page, analysis, stats)

        save(out_doc, output, clean=True)
    return stats


def _sources_to_pdf_bytes(sources: list[Path], password: str, config: dict) -> tuple[pdf.Document, int]:
    """Acepta PDF o lista de imagenes escaneadas y devuelve un pdf.Document en memoria."""
    if len(sources) == 1 and sources[0].suffix.lower() == ".pdf":
        doc = open_pdf(sources[0], password, config["max_pages"])
        return doc, 1

    if any(src.suffix.lower() == ".pdf" for src in sources):
        # Si combinan varios PDFs, fusionarlos ordenadamente respetando limites
        combined = pdf.open()
        total = 0
        for src in sources:
            if src.suffix.lower() != ".pdf":
                combined.close()
                raise ProcessingError("No mezcle PDF con imagenes en una misma carga; seleccione solo PDF o solo imagenes.")
            with open_pdf(src, password, config["max_pages"]) as part:
                total += len(part)
                if config["max_pages"] and total > config["max_pages"]:
                    combined.close()
                    raise ProcessingError("La suma de paginas excede el limite configurado.")
                combined.insert_pdf(part)
        return combined, len(sources)

    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass

    combined = pdf.open()
    for src in sources:
        if src.suffix.lower() not in IMAGE_TYPES:
            combined.close()
            raise ProcessingError("Formato de imagen o PDF no admitido.")
        try:
            with Image.open(src) as image:
                if image.width * image.height > config["max_render_pixels"]:
                    combined.close()
                    raise ProcessingError("Imagen demasiado grande.")
                if getattr(image, "n_frames", 1) != 1:
                    combined.close()
                    raise ProcessingError("Use imagenes de un solo fotograma.")
                image = ImageOps.exif_transpose(image)
                if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    flat = Image.new("RGB", rgba.size, "white")
                    flat.paste(rgba, mask=rgba.getchannel("A"))
                    image = flat
                else:
                    image = image.convert("RGB")
                raw_dpi = image.info.get("dpi")
                page_w_pt = image.width * 0.75
                page_h_pt = image.height * 0.75
                if isinstance(raw_dpi, tuple) and len(raw_dpi) == 2 and min(raw_dpi) >= 120 and max(raw_dpi) <= 600:
                    page_w_pt = image.width * 72.0 / float(raw_dpi[0])
                    page_h_pt = image.height * 72.0 / float(raw_dpi[1])
                elif max(page_w_pt, page_h_pt) > 842.0:
                    scale_pt = 792.0 / max(page_w_pt, page_h_pt)
                    page_w_pt *= scale_pt
                    page_h_pt *= scale_pt
                buf = io.BytesIO()
                image.save(buf, format="JPEG", quality=95)
                page = combined.new_page(width=page_w_pt, height=page_h_pt)
                page.insert_image(page.rect, stream=buf.getvalue())
        except (UnidentifiedImageError, OSError):
            combined.close()
            raise ProcessingError("Imagen escaneada no valida o danada.") from None
    return combined, len(sources)


def handle_scan_to_office(
    operation: str,
    sources: list[Path],
    options: dict,
    folder: Path,
    config: dict,
    root: Path,
) -> dict:
    """Convierte PDF/imagenes escaneadas en PPTX/DOCX/XLSX/PDF editable con OCR y vectores."""
    target = str(options.get("target_format", "pptx")).lower().strip()
    if target not in {"pptx", "docx", "xlsx", "pdf"}:
        raise ProcessingError("Formato de salida no valido. Use pptx, docx, xlsx o pdf.")

    password = str(options.get("password", ""))
    doc, _ = _sources_to_pdf_bytes(sources, password, config)
    try:
        selected = pages_from(options.get("pages", ""), len(doc))
        if target == "pdf":
            output = folder / "escaneo_vectorial_ocr.pdf"
            stats = refine_pdf_scans_to_vector(doc, selected, output, config, root, options)
            notice = (
                f"PDF vectorial reconstruido: {stats['pages']} pagina(s), "
                f"{stats['tables']} tabla(s), {stats['diagrams']} forma(s), "
                f"{stats['connectors']} conector(es) y capa OCR editable."
            )
            return {"file": output.name, "notice": notice}

        from office_export import export_office

        office_op = f"pdf_to_{target}"
        refined_opts = dict(options)
        refined_opts["scan_editable_mode"] = True
        output, notice = export_office(
            office_op, doc, selected, folder, config, options=refined_opts, root=root
        )
        return {"file": output.name, "notice": notice}
    finally:
        doc.close()
