from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def _has_python_package(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def discover_addon_packs(config: dict, root: Path) -> dict[str, dict]:
    addons_dir = root / config.get("addons_dir", "addons")
    packs: dict[str, dict] = {}
    if not addons_dir.is_dir():
        return packs
    for entry in sorted(addons_dir.iterdir()):
        if not entry.is_dir():
            continue
        manifest = entry / "manifest.json"
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    packs[entry.name] = {
                        "id": entry.name,
                        "name": str(data.get("name", entry.name)),
                        "version": str(data.get("version", "1.0.0")),
                        "capabilities": list(data.get("capabilities", [])),
                        "installed": True,
                    }
                    continue
            except (OSError, json.JSONDecodeError):
                pass
        packs[entry.name] = {
            "id": entry.name,
            "name": entry.name,
            "version": "local",
            "capabilities": [],
            "installed": True,
        }
    return packs


def discover_nmt_pairs(config: dict, root: Path) -> list[str]:
    if not _has_python_package("ctranslate2"):
        return []
    nmt_root = root / config.get("addons_dir", "addons") / "pack-nmt"
    if not nmt_root.is_dir():
        return []
    has_sp = _has_python_package("sentencepiece")
    pairs: list[str] = []
    for entry in sorted(nmt_root.iterdir()):
        if not entry.is_dir() or not re.fullmatch(r"[a-z]{2}_[a-z]{2}", entry.name):
            continue
        if not (entry / "model" / "model.bin").is_file():
            continue
        if (entry / "sentencepiece.model").is_file() and has_sp:
            pairs.append(entry.name)
        elif (entry / "bpe.model").is_file():
            pairs.append(entry.name)
    return pairs


def addons_status(config: dict, root: Path) -> dict:
    packs = discover_addon_packs(config, root)
    nmt_pairs = discover_nmt_pairs(config, root)
    ai_mode = config.get("ai_mode", "disabled")
    loopback_url = config.get("ai_loopback_url", "").strip()
    edge_endpoint = config.get("ai_edge_endpoint", "").strip()
    allow_external = bool(config.get("allow_external_ai", False))
    pdfium_dir = root / "static" / "vendor" / "pdfium"
    pdfium_available = (pdfium_dir / "pdfium.js").is_file() and (pdfium_dir / "pdfium.wasm").is_file()
    katex_available = (root / "static" / "vendor" / "katex" / "katex.min.js").is_file()

    return {
        "packs": packs,
        "onnx": _has_python_package("onnxruntime") or "pack-ocr-onnx" in packs,
        "ctranslate2": _has_python_package("ctranslate2") or bool(nmt_pairs),
        "nmt_offline": bool(nmt_pairs),
        "nmt_pairs": nmt_pairs,
        "fonttools": _has_python_package("fontTools"),
        "piper_tts": bool(shutil.which("piper")) or _has_python_package("piper") or "pack-tts" in packs,
        "jbig2_lossless": bool(shutil.which("jbig2") or shutil.which("jbig2enc")) or "pack-jbig2" in packs,
        "loopback_slm": ai_mode == "loopback_slm" and bool(loopback_url),
        "edge_ai_opt_in": ai_mode == "edge_opt_in" and allow_external and edge_endpoint.startswith("https://"),
        "wasm_pdfium": bool(config.get("allow_wasm_viewer", False)) and pdfium_available,
        "wasm_enabled": bool(config.get("allow_wasm_viewer", False)),
        "katex_vendor": katex_available,
    }


def active_ai_target(config: dict) -> tuple[str, str]:
    """Devuelve ('loopback'|'edge'|'none', url) respetando aislamiento air-gapped."""
    mode = config.get("ai_mode", "disabled")
    if mode == "loopback_slm":
        url = config.get("ai_loopback_url", "").strip()
        if url:
            parsed = urlsplit(url)
            if parsed.scheme in ("http", "https") and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
                return "loopback", url.rstrip("/")
    elif mode == "edge_opt_in" and config.get("allow_external_ai") is True:
        url = config.get("ai_edge_endpoint", "").strip()
        if url.startswith("https://"):
            return "edge", url.rstrip("/")
    return "none", ""


def call_ai_backend(prompt: str, system_prompt: str, config: dict, *,
                    timeout: int = 25) -> dict | None:
    """Invoca SLM loopback (127.0.0.1) o endpoint Edge opt-in; nunca abre red si esta deshabilitado."""
    kind, base_url = active_ai_target(config)
    if kind == "none":
        return None
    import requests

    model_name = os.environ.get("EVA_AI_MODEL", "llama3.2")
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("EVA_AI_API_KEY", "").strip()
    if api_key and kind == "edge":
        headers["Authorization"] = f"Bearer {api_key}"

    # Soporta interfaz OpenAI-compatible (/v1/chat/completions) y Ollama (/api/chat)
    candidates = (
        (
            f"{base_url}/v1/chat/completions" if not base_url.endswith("/v1/chat/completions") else base_url,
            {
                "model": model_name,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            },
            "openai",
        ),
        (
            f"{base_url}/api/chat" if not base_url.endswith("/api/chat") else base_url,
            {
                "model": model_name,
                "stream": False,
                "options": {"temperature": 0.1},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            },
            "ollama",
        ),
    )
    for url, body, dialect in candidates:
        try:
            response = requests.post(url, json=body, headers=headers, timeout=timeout)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            data = response.json()
            if dialect == "openai":
                content = data["choices"][0]["message"]["content"]
            else:
                content = data["message"]["content"]
            return {"backend": kind, "dialect": dialect, "content": content}
        except (requests.RequestException, KeyError, IndexError, ValueError):
            continue
    return None
