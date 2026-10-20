from __future__ import annotations

import errno
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sqlite3
import threading
import time

_lock = threading.Lock()
_recent: list[float] = []
_logger = None


def event_logger(folder: Path, name: str) -> logging.Logger:
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("recovery." + str(folder.resolve()) + "." + name)
    if not logger.handlers:
        handler = RotatingFileHandler(folder / (name + ".jsonl"), maxBytes=2 * 1024 * 1024,
                                      backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def emit(logger: logging.Logger, event: str, **fields) -> None:
    logger.info(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": event, **fields}, ensure_ascii=True))


def classify(error: BaseException) -> str | None:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, MemoryError):
            return "memory_exhausted"
        if isinstance(error, OSError):
            if error.errno in (errno.ENOMEM, errno.EMFILE, errno.ENFILE):
                return "resource_exhausted"
            if error.errno == errno.EIO:
                return "io_failure"
            if getattr(error, "winerror", None) in (8, 14, 1450, 1455):
                return "resource_exhausted"
            if getattr(error, "winerror", None) in (23, 1117):
                return "io_failure"
        if isinstance(error, sqlite3.Error):
            if getattr(error, "sqlite_errorcode", 0) & 255 == sqlite3.SQLITE_IOERR:
                return "database_io_failure"
        error = error.__cause__ or error.__context__
    return None


def request_recovery(reason: str) -> None:
    marker = os.environ.get("SERVICE_RECOVERY_MARKER")
    if not marker:
        return
    path = Path(marker)
    temporary = path.with_suffix(".tmp")
    with _lock:
        temporary.write_text(json.dumps({"reason": reason, "pid": os.getpid(),
                                         "generation": os.environ.get("SERVICE_RECOVERY_GENERATION"),
                                         "time": time.time()}), encoding="utf-8")
        os.replace(temporary, path)


def report_failure(error: BaseException) -> None:
    category = classify(error)
    if category is None:
        return
    if _logger is not None:
        emit(_logger, "application_fault", category=category, exception=type(error).__name__)
    with _lock:
        now = time.monotonic()
        _recent[:] = [stamp for stamp in _recent if now - stamp <= 60]
        _recent.append(now)
        recover = category == "memory_exhausted" or len(_recent) >= 3
    if recover:
        request_recovery(category)


def install_recovery(app) -> None:
    global _logger
    from flask import got_request_exception

    folder = Path(os.environ.get("SERVICE_EVENT_DIR", str(Path(app.root_path) / "instance" / "logs")))
    _logger = event_logger(folder, "application-events")

    def on_exception(sender, exception, **extra):
        emit(_logger, "request_exception", exception=type(exception).__name__)
        report_failure(exception)

    got_request_exception.connect(on_exception, sender=app, weak=False)

    @app.after_request
    def report_response(response):
        if response.status_code >= 500:
            emit(_logger, "http_server_error", status=response.status_code)
        if app.extensions.get("cleanup_failed"):
            request_recovery("cleanup_failed")
        return response

    emit(_logger, "application_hooks_ready", pid=os.getpid())
