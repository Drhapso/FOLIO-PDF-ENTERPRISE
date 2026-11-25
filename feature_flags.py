from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FEATURE_FLAGS_KEY = "feature_flags"
VALID_FEATURE_STATES = ("enabled", "development", "maintenance")
STATE_LABELS = {
    "development": "Función en desarrollo",
    "maintenance": "Función en Mantenimiento",
}
TOOL_ID_RE = re.compile(r"^[a-z0-9_]{2,64}$")

# Mapeo de operaciones internas del backend hacia su ID visible de tarjeta/herramienta
OPERATION_TO_TOOL_ID = {
    "edit_text_pro": "edit",
    "pipeline_run": "v2_pipeline_studio",
    "canvas_extract": "v2_canvas_studio",
    "canvas_diff": "v2_canvas_studio",
    "vault_compile": "v2_vault_studio",
}

LOGIN_RATE_WINDOW_SECONDS = 600
LOGIN_RATE_MAX_USER_ATTEMPTS = 5
LOGIN_RATE_MAX_IP_ATTEMPTS = 10
_LOGIN_LOCK = threading.Lock()
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_FLAGS_LOCK = threading.Lock()


def load_or_create_secret(path: Path, env_var: str = "EVA_SECRET_KEY") -> bytes:
    env_value = (os.environ.get(env_var) or "").strip()
    if env_value:
        return env_value.encode("utf-8")
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    secret_text = secrets.token_hex(32)
    tmp_path = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    try:
        tmp_path.write_text(secret_text + "\n", encoding="utf-8")
        os.replace(str(tmp_path), str(path))
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return secret_text.encode("utf-8")


def verify_pbkdf2_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_text, digest_text = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.urlsafe_b64decode(salt_text.encode("ascii")),
            int(rounds),
        )
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def _candidate_falcon_dbs(root: Path) -> list[Path]:
    env_db = (os.environ.get("EVA_ADMIN_DB_PATH") or "").strip()
    cands: list[Path] = []
    if env_db:
        cands.append(Path(env_db))
    # Desde D:\PROYECTOS IA INDEPENDIENTES\FOLIO PDF\FOLIO PDF ENTERPRISE -> parents[1] es el workspace
    bases = [root]
    for parent in list(root.parents)[:3]:
        bases.append(parent)
    for base in bases:
        cands.append(base / "FALCON" / "falcon web" / "data" / "control_produccion_final.db")
        cands.append(base / "PROYECTOS V.2" / "falcon-web" / "data" / "control_produccion_final.db")
    seen: set[Path] = set()
    unique: list[Path] = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def authenticate_admin(root: Path, username: str, password: str) -> dict[str, Any] | None:
    clean_user = (username or "").strip()
    if not clean_user or not password:
        return None

    # 1. Credencial explícita por entorno (útil para despliegue autónomo o pruebas)
    env_pass = os.environ.get("EVA_ADMIN_PASSWORD")
    if env_pass is not None and env_pass != "":
        env_user = (os.environ.get("EVA_ADMIN_USER") or "admin").strip()
        if (
            hmac.compare_digest(clean_user.lower(), env_user.lower())
            and hmac.compare_digest(password, env_pass)
        ):
            return {
                "username": env_user.lower(),
                "nombre_completo": "ADMINISTRADOR EVA PDF",
                "role": "admin",
            }

    # 2. Autenticación institucional compartida con la base de administradores FALCON
    for db_path in _candidate_falcon_dbs(root):
        if not db_path.is_file():
            continue
        try:
            with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT id, username, password_hash, role, activo, nombre_completo "
                    "FROM users WHERE LOWER(username) = ?",
                    (clean_user.lower(),),
                ).fetchone()
                if row and row["activo"] and row["role"] == "admin":
                    if verify_pbkdf2_password(password, row["password_hash"]):
                        return {
                            "username": str(row["username"]),
                            "nombre_completo": str(row["nombre_completo"] or row["username"]).upper(),
                            "role": "admin",
                        }
        except Exception:
            continue
    return None


def is_login_rate_limited(ip: str, username: str) -> bool:
    now = time.monotonic()
    cutoff = now - LOGIN_RATE_WINDOW_SECONDS
    user_key = f"u:{ip}:{(username or '').strip().lower()}"
    ip_key = f"ip:{ip}"
    with _LOGIN_LOCK:
        u_hist = [t for t in _LOGIN_ATTEMPTS.get(user_key, []) if t > cutoff]
        i_hist = [t for t in _LOGIN_ATTEMPTS.get(ip_key, []) if t > cutoff]
        _LOGIN_ATTEMPTS[user_key] = u_hist
        _LOGIN_ATTEMPTS[ip_key] = i_hist
        return len(u_hist) >= LOGIN_RATE_MAX_USER_ATTEMPTS or len(i_hist) >= LOGIN_RATE_MAX_IP_ATTEMPTS


def record_login_failure(ip: str, username: str) -> None:
    now = time.monotonic()
    cutoff = now - LOGIN_RATE_WINDOW_SECONDS
    user_key = f"u:{ip}:{(username or '').strip().lower()}"
    ip_key = f"ip:{ip}"
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS[user_key] = [t for t in _LOGIN_ATTEMPTS.get(user_key, []) if t > cutoff] + [now]
        _LOGIN_ATTEMPTS[ip_key] = [t for t in _LOGIN_ATTEMPTS.get(ip_key, []) if t > cutoff] + [now]


def clear_login_failures(ip: str, username: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop(f"u:{ip}:{(username or '').strip().lower()}", None)


def _db_path(root: Path) -> Path:
    data_dir = root / "instance"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "platform.sqlite3"


def _sanitize_flags_dict(raw: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, dict[str, str]] = {}
    for tool_id, entry in raw.items():
        if not isinstance(tool_id, str) or not TOOL_ID_RE.fullmatch(tool_id):
            continue
        if isinstance(entry, str):
            state = entry.strip().lower()
            note = ""
            updated_at = ""
            updated_by = ""
        elif isinstance(entry, dict):
            state = str(entry.get("state") or "").strip().lower()
            note = " ".join(str(entry.get("note") or "").split()).strip()[:180]
            updated_at = str(entry.get("updated_at") or "").strip()[:40]
            updated_by = str(entry.get("updated_by") or "").strip()[:60]
        else:
            continue
        if state in ("development", "maintenance"):
            clean[tool_id] = {
                "state": state,
                "label": STATE_LABELS[state],
                "note": note,
                "updated_at": updated_at,
                "updated_by": updated_by,
            }
    return clean


def get_feature_flags(root: Path) -> dict[str, dict[str, str]]:
    db_file = _db_path(root)
    if not db_file.is_file():
        return {}
    with _FLAGS_LOCK:
        try:
            with closing(sqlite3.connect(db_file, timeout=10)) as db:
                row = db.execute(
                    "SELECT value FROM settings WHERE key = ?",
                    (FEATURE_FLAGS_KEY,),
                ).fetchone()
                if not row or not row[0]:
                    return {}
                return _sanitize_flags_dict(json.loads(row[0]))
        except Exception:
            return {}


def save_feature_flags(root: Path, flags: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    clean = _sanitize_flags_dict(flags)
    db_file = _db_path(root)
    with _FLAGS_LOCK:
        with closing(sqlite3.connect(db_file, timeout=10)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            with db:
                db.execute(
                    "INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (FEATURE_FLAGS_KEY, json.dumps(clean, ensure_ascii=False)),
                )
    return clean


def update_feature_flags(
    root: Path,
    *,
    updates: dict[str, dict[str, Any]] | None = None,
    reset_all: bool = False,
    actor: str = "admin",
) -> dict[str, dict[str, str]]:
    if reset_all:
        return save_feature_flags(root, {})
    current = get_feature_flags(root)
    now_iso = datetime.now(timezone.utc).isoformat()
    if updates:
        for tool_id, cfg in updates.items():
            if not isinstance(tool_id, str) or not TOOL_ID_RE.fullmatch(tool_id):
                raise ValueError(f"Identificador de función no válido: {tool_id!r}")
            if isinstance(cfg, str):
                state = cfg.strip().lower()
                note = ""
            elif isinstance(cfg, dict):
                state = str(cfg.get("state") or "enabled").strip().lower()
                note = " ".join(str(cfg.get("note") or "").split()).strip()[:180]
            else:
                raise ValueError(f"Estado no válido para {tool_id!r}")
            if state not in VALID_FEATURE_STATES:
                raise ValueError(f"Estado no permitido '{state}'. Use enabled, development o maintenance.")
            if state == "enabled":
                current.pop(tool_id, None)
            else:
                current[tool_id] = {
                    "state": state,
                    "label": STATE_LABELS[state],
                    "note": note,
                    "updated_at": now_iso,
                    "updated_by": actor,
                }
    return save_feature_flags(root, current)


def get_blocked_feature_info(root: Path, operation_or_tool_id: str) -> dict[str, str] | None:
    flags = get_feature_flags(root)
    direct = flags.get(operation_or_tool_id)
    if direct:
        return direct
    mapped = OPERATION_TO_TOOL_ID.get(operation_or_tool_id)
    if mapped:
        return flags.get(mapped)
    return None


def blocked_error_message(info: dict[str, str]) -> str:
    label = info.get("label") or STATE_LABELS.get(info.get("state", ""), "Función deshabilitada")
    note = (info.get("note") or "").strip()
    if note:
        return f"{label}: {note}"
    if info.get("state") == "maintenance":
        return f"{label}: esta función presenta ajustes técnicos y se encuentra temporalmente inhabilitada por el administrador."
    return f"{label}: esta función se encuentra temporalmente inhabilitada por el administrador."
