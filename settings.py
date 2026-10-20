from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8090,
    "max_file_mb": 1024,
    "max_upload_mb": 1024,
    "max_output_mb": 2048,
    "max_files": 5,
    "max_batch_files": 200,
    "max_pages": 0,
    "max_batch_pages": 0,
    "max_render_pixels": 16_000_000,
    "max_parallel_jobs": 5,
    "max_job_memory_mb": 4096,
    "timeout_seconds": 120,
    "ocr_language": "spa+eng",
    "libreoffice_path": "",
    "secure_transport": False,
    "editor_live_preview": False,
    "max_heavy_jobs": 2,
    "max_queued_jobs": 12,
    "queue_wait_seconds": 45,
    "max_active_upload_mb": 1026,
    "max_queued_upload_mb": 256,
    "heavy_upload_mb": 10,
    "recommended_upload_mb": 10,
}


def load_settings(root: Path = ROOT) -> dict:
    config = DEFAULTS.copy()
    source = root / "config" / "site_config.json"
    if source.exists():
        supplied = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(supplied, dict) or supplied.keys() - DEFAULTS.keys():
            raise ValueError("Configuracion desconocida o no valida.")
        config.update(supplied)
    for key in ("host", "port"):
        value = os.environ.get(f"PDF_{key.upper()}")
        if value is not None:
            config[key] = int(value) if key == "port" else value
    limits = {
        "port": (1, 65535), "max_file_mb": (1, 2048), "max_upload_mb": (1, 10240),
        "max_output_mb": (1, 4096), "max_files": (1, 100), "max_batch_files": (1, 1000),
        "max_pages": (0, 2000), "max_batch_pages": (0, 50000),
        "max_render_pixels": (100_000, 40_000_000),
        "max_parallel_jobs": (1, 8), "max_job_memory_mb": (256, 16384),
        "timeout_seconds": (10, 3600),
        "max_heavy_jobs": (1, 8), "max_queued_jobs": (1, 24),
        "queue_wait_seconds": (1, 120), "max_active_upload_mb": (16, 4096),
        "max_queued_upload_mb": (16, 4096), "heavy_upload_mb": (1, 1024),
        "recommended_upload_mb": (1, 1024),
    }
    for key, (low, high) in limits.items():
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError(f"Configuracion fuera de rango: {key}.")
    if config["max_file_mb"] > config["max_upload_mb"]:
        raise ValueError("max_file_mb no puede superar max_upload_mb.")
    if config["max_active_upload_mb"] < config["max_upload_mb"] + 1:
        raise ValueError("El presupuesto activo debe cubrir la carga maxima y el margen multipart de 1 MB.")
    if config["recommended_upload_mb"] > min(config["max_upload_mb"], config["heavy_upload_mb"]):
        raise ValueError("El rango recomendado debe caber en la carga y el umbral pesado.")
    for key in ("host", "ocr_language", "libreoffice_path"):
        if not isinstance(config[key], str):
            raise ValueError(f"Configuracion no valida: {key}.")
    if not config["host"] or config["ocr_language"] not in ("spa", "eng", "spa+eng"):
        raise ValueError("Host o idioma OCR no valido.")
    if type(config["secure_transport"]) is not bool:
        raise ValueError("secure_transport debe ser booleano.")
    if type(config["editor_live_preview"]) is not bool:
        raise ValueError("editor_live_preview debe ser booleano.")
    data = root / "instance"
    data.mkdir(exist_ok=True)
    from performance import tune
    profile_path = data / "performance.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else None
    performance = tune(config, profile)
    config["max_heavy_jobs"] = min(config["max_heavy_jobs"], max(1, config["max_parallel_jobs"] - 1))
    with closing(sqlite3.connect(data / "platform.sqlite3", timeout=10)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        with db:
            db.executemany(
                "INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [(key, json.dumps(value)) for key, value in config.items()],
            )
            db.execute("PRAGMA user_version=1")
    config["performance"] = performance
    return config
