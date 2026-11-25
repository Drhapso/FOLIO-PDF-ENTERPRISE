from __future__ import annotations

import atexit
import io
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import pymupdf as pdf
from PIL import Image
from flask import Flask, Request, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from engines.registry import allowed_upload_suffixes
from isolation import InstanceLock, ProcessTree, worker_command
from pdf_engine import BULK_OPERATIONS, OPERATIONS, ProcessingError, capabilities, file_limit
from settings import ROOT, load_settings
from workload import AdmissionError, HEAVY_OPERATIONS, WorkloadQueue
from recovery_events import install_recovery, report_failure, request_recovery

CLIENT_BUILD = "2026-11-24-desktop-fix-3"
LOG = logging.getLogger("pdf_lan")
INLINE_RESULT_BYTES = 64 * 1024 * 1024
STREAM_CHUNK = 1024 * 1024
MAX_ORPHAN_FOLDERS = 20
_quarantine_folders: set[Path] = set()
_quarantine_lock = threading.Lock()


def _async_sweep_quarantine() -> None:
    with _quarantine_lock:
        to_sweep = list(_quarantine_folders)
    for folder in to_sweep:
        try:
            shutil.rmtree(folder)
            with _quarantine_lock:
                _quarantine_folders.discard(folder)
        except OSError:
            pass
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/octet-stream", ".evacrypt")
mimetypes.add_type("application/json", ".evaboard")
mimetypes.add_type("application/json", ".evatpl")


def _handle_readonly_rmtree(func, path, exc_info):
    import stat
    exc = exc_info[1] if isinstance(exc_info, tuple) else exc_info
    if getattr(exc, "winerror", None) == 5 or getattr(exc, "errno", None) == 13:
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)
            return
        except OSError:
            pass
    if exc:
        raise exc


def remove_job_folder(folder: Path) -> None:
    delays = (0.1, 0.2, 0.4, 0.8, 1.6)
    for attempt in range(len(delays) + 1):
        try:
            shutil.rmtree(folder, onerror=_handle_readonly_rmtree)
            return
        except FileNotFoundError:
            if not folder.exists():
                return
            raise
        except OSError as error:
            if getattr(error, "winerror", None) not in (32, 33, 145) or attempt == len(delays):
                raise
            LOG.warning("Limpieza temporal en espera: intento=%s winerror=%s",
                        attempt + 1, error.winerror)
            time.sleep(delays[attempt])


class SpoolRequest(Request):
    """Las cargas grandes se escriben en archivos anonimos que Windows borra al cerrarlos."""

    spool_dir: Path | None = None

    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        return tempfile.TemporaryFile("w+b", dir=self.spool_dir)


class TransientFile:
    """Entrega un resultado grande y lo elimina al terminar o cancelar la descarga."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = path.open("rb")

    def __iter__(self):
        return self

    def __next__(self):
        chunk = self.handle.read(STREAM_CHUNK)
        if not chunk:
            raise StopIteration
        return chunk

    def close(self):
        self.handle.close()
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            LOG.critical("No se pudo eliminar un resultado entregado; se borrara al reiniciar.")
            request_recovery("outgoing_cleanup_failed")


def purge_folder(folder: Path):
    for path in folder.iterdir():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def create_app(root: Path = ROOT) -> Flask:
    config = load_settings(root)
    if "FOLIO_TEST_LIVE_PREVIEW" in os.environ:
        config["editor_live_preview"] = os.environ["FOLIO_TEST_LIVE_PREVIEW"] == "1"
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    install_recovery(app)
    runtime = root / "runtime"
    runtime.mkdir(exist_ok=True)
    spool = runtime / "spool"
    outgoing = runtime / "outgoing"
    app.request_class = type("FolioRequest", (SpoolRequest,), {"spool_dir": spool})
    app.config.update(
        # Margen para cabeceras multipart: un archivo de exactamente 1 GB debe caber.
        MAX_CONTENT_LENGTH=(config["max_upload_mb"] + 1) * 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=128 * 1024,
        MAX_FORM_PARTS=max(config["max_files"], config["max_batch_files"]) + 4,
        TEMPLATES_AUTO_RELOAD=True,
    )
    app.jinja_env.auto_reload = True
    lock = InstanceLock(runtime / "instance.lock")
    app.extensions["instance_lock"] = lock
    atexit.register(lock.close)
    # El bloqueo impide borrar el trabajo de otra instancia activa.
    try:
        for path in runtime.glob("job-*"):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
        for folder in (spool, outgoing):
            folder.mkdir(exist_ok=True)
            purge_folder(folder)
    except OSError:
        lock.close()
        raise RuntimeError("No se pudieron eliminar temporales anteriores. Arranque cancelado.") from None
    gate = threading.BoundedSemaphore(config["max_parallel_jobs"])
    app.extensions["job_gate"] = gate
    queue = WorkloadQueue(config, gate)
    app.extensions["workload_queue"] = queue
    app.extensions["pdf_settings"] = config
    app.extensions["spool_dir"] = spool
    pending_cleanups: set[Path] = set()
    app.extensions["pending_cleanups"] = pending_cleanups

    def sweep_cleanups() -> None:
        for folder in list(pending_cleanups):
            try:
                if folder.is_dir() and not folder.is_symlink():
                    shutil.rmtree(folder)
                elif folder.is_file():
                    folder.unlink(missing_ok=True)
                pending_cleanups.discard(folder)
            except OSError:
                pass

    app.extensions["sweep_cleanups"] = sweep_cleanups

    if os.environ.get("PDF_TRUSTED_PROXY") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    @app.before_request
    def enforce_origin():
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if not origin or urlsplit(origin).netloc != request.host or urlsplit(origin).scheme != request.scheme:
                return jsonify(error="Solicitud rechazada: origen no autorizado."), 403
            if request.headers.get("X-PDF-Client") != CLIENT_BUILD:
                return jsonify(error="Recargue la pagina antes de continuar."), 403
            if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
                return jsonify(error="Solicitud rechazada: sitio externo."), 403

    @app.after_request
    def privacy_headers(response):
        response.headers["Cache-Control"] = "no-store, private, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        script_src = "'self' 'wasm-unsafe-eval'" if config.get("allow_wasm_viewer") else "'self'"
        worker_src = "worker-src 'self' blob:; " if config.get("allow_wasm_viewer") else ""
        connect_src = "'self'"
        if config.get("allow_external_ai") and config.get("ai_edge_endpoint", "").startswith("https://"):
            edge = urlsplit(config["ai_edge_endpoint"])
            if edge.scheme == "https" and edge.netloc:
                connect_src = f"'self' https://{edge.netloc}"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src {script_src}; {worker_src}style-src 'self'; "
            f"img-src 'self' data: blob:; connect-src {connect_src}; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Permissions-Policy"] = "camera=(self), display-capture=(self), microphone=(), geolocation=()"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {413: "Se excedio el limite de carga o de campos del formulario.",
                    400: "Solicitud no valida.", 404: "Recurso no encontrado.",
                    405: "Metodo no permitido."}
        return jsonify(error=messages.get(error.code, "Solicitud rechazada.")), error.code

    @app.get("/")
    def index():
        return render_template("index.html", build=CLIENT_BUILD)

    @app.get("/editor")
    def editor():
        return render_template("editor.html", build=CLIENT_BUILD)

    @app.get("/pipeline")
    def pipeline_workspace():
        return render_template("pipeline.html", build=CLIENT_BUILD)

    @app.get("/canvas")
    def canvas_workspace():
        return render_template("canvas.html", build=CLIENT_BUILD)

    @app.get("/vault")
    def vault_workspace():
        return render_template("vault.html", build=CLIENT_BUILD)

    @app.get("/health")
    def health():
        if app.extensions.get("cleanup_failed"):
            return jsonify(app="pdf-lan", status="cleanup_failed", client_build=CLIENT_BUILD), 503
        return jsonify(app="pdf-lan", status="ok", client_build=CLIENT_BUILD)

    @app.get("/api/capabilities")
    def available():
        return jsonify(**capabilities(config, ROOT), max_upload_mb=config["max_upload_mb"],
                       max_file_mb=config["max_file_mb"], max_parallel_jobs=config["max_parallel_jobs"],
                       max_batch_files=config["max_batch_files"], bulk_operations=sorted(BULK_OPERATIONS),
                       max_files=config["max_files"], max_pages=config["max_pages"],
                       timeout_seconds=config["timeout_seconds"], build=CLIENT_BUILD,
                       performance=config["performance"],
                       ai_mode=config.get("ai_mode", "disabled"),
                       wasm_viewer=bool(config.get("allow_wasm_viewer", False)),
                       max_ai_jobs=config.get("max_ai_jobs", 1),
                       queue={"max_waiting": config["max_queued_jobs"],
                              "max_wait_seconds": config["queue_wait_seconds"],
                              "max_heavy_jobs": config["max_heavy_jobs"],
                              "heavy_upload_mb": config["heavy_upload_mb"],
                              "recommended_upload_mb": config["recommended_upload_mb"],
                              "max_active_upload_mb": config["max_active_upload_mb"],
                              "max_queued_upload_mb": config["max_queued_upload_mb"],
                              "heavy_operations": sorted(HEAVY_OPERATIONS)},
                       secure_transport=config["secure_transport"])

    @app.get("/api/queue/<token>")
    def queue_status(token: str):
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            return jsonify(error="Identificador de solicitud no valido."), 400
        status = queue.status(token)
        if status is None:
            return jsonify(error="Solicitud no registrada o ya finalizada."), 404
        return jsonify(status)

    @app.post("/api/queue/<token>/cancel")
    def queue_cancel(token: str):
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            return jsonify(error="Identificador de solicitud no valido."), 400
        if not queue.cancel(token):
            return jsonify(error="La solicitud ya inicio o finalizo; no se puede cancelar en cola."), 409
        return jsonify(state="cancelled")

    @app.get("/desktop/download")
    def desktop_download():
        return send_file(ROOT / "desktop" / "EVA-Desktop.ps1", as_attachment=True,
                         download_name="EVA-Desktop.ps1", mimetype="text/plain", conditional=False, etag=False)

    @app.post("/desktop/launch/<action>")
    def desktop_launch(action: str):
        if action not in ("Scan", "Print", "Printers", "Menu"):
            return jsonify(error="Accion no valida."), 400
        is_local = request.remote_addr in ("127.0.0.1", "::1", "localhost")
        if not is_local:
            return jsonify(ok=False, local_only=True,
                           message="Para escanear desde un equipo cliente en la LAN, descargue el complemento local.")
        script = ROOT / "desktop" / "EVA-Desktop.ps1"
        if not script.is_file():
            return jsonify(error="No se encuentra el script de escritorio."), 404
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                ["powershell.exe", "-STA", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Action", action],
                creationflags=creationflags,
            )
            return jsonify(ok=True, action=action, message=f"Accion {action} iniciada.")
        except Exception as error:
            LOG.error("Fallo al iniciar accion de escritorio: %s", error)
            return jsonify(error="No se pudo iniciar la accion en el sistema."), 500

    @app.post("/api/copilot/chat")
    def copilot_chat():
        from engines.copilot_service import process_copilot_request
        prompt = request.form.get("prompt") or request.form.get("message") or ""
        if not prompt and request.is_json:
            data = request.get_json(silent=True) or {}
            prompt = data.get("prompt") or data.get("message") or ""

        file = request.files.get("file")
        pdf_bytes = None
        filename = "documento.pdf"
        if file and file.filename:
            filename = file.filename
            pdf_bytes = file.read()

        res = process_copilot_request(prompt, pdf_bytes, filename, config)
        return jsonify(res)

    @app.post("/api/signature/remove_background")
    def signature_remove_bg():
        import numpy as np
        file = request.files.get("image") or request.files.get("file")
        if not file:
            return jsonify(error="No se envio imagen de firma."), 400
        threshold = int(request.form.get("threshold", 215))
        try:
            img = Image.open(file.stream).convert("RGBA")
            arr = np.array(img)
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            bright = 0.299 * r + 0.587 * g + 0.114 * b
            max_diff = np.maximum(np.abs(r.astype(int) - g.astype(int)), np.abs(r.astype(int) - b.astype(int)))
            is_bg = (bright > threshold) & (max_diff < 40)
            arr[is_bg & (bright >= 240), 3] = 0
            semi = is_bg & (bright < 240)
            arr[semi, 3] = np.clip(255 * (1.0 - (bright[semi] - threshold) / max(240 - threshold, 1)), 0, 255).astype(np.uint8)
            out_img = Image.fromarray(arr, "RGBA")
            buf = io.BytesIO()
            out_img.save(buf, format="PNG")
            buf.seek(0)
            return send_file(buf, mimetype="image/png", as_attachment=False)
        except Exception as e:
            LOG.error("Fallo al remover fondo: %s", e)
            return jsonify(error="No se pudo procesar la imagen de firma."), 422

    @app.post("/api/ocr_snippet")
    def ocr_snippet():
        file = request.files.get("file")
        if not file:
            return jsonify(error="Se requiere archivo PDF."), 400
        page_num = int(request.form.get("page", 1))
        x = float(request.form.get("x", 0))
        y = float(request.form.get("y", 0))
        w = float(request.form.get("w", 100))
        h = float(request.form.get("h", 100))
        password = request.form.get("password", "")

        try:
            pdf_bytes = file.read()
            with pdf.open(stream=pdf_bytes, filetype="pdf") as doc:
                if doc.needs_pass and not doc.authenticate(password):
                    return jsonify(error="Contraseña incorrecta."), 403
                if not (1 <= page_num <= len(doc)):
                    return jsonify(error="Pagina fuera de rango."), 400
                page = doc[page_num - 1]

                pw, ph = page.rect.width, page.rect.height
                rx0 = page.rect.x0 + pw * (x / 100.0)
                ry0 = page.rect.y0 + ph * (y / 100.0)
                rx1 = rx0 + pw * (w / 100.0)
                ry1 = ry0 + ph * (h / 100.0)
                clip_rect = pdf.Rect(rx0, ry0, rx1, ry1) & page.rect

                if clip_rect.is_empty:
                    return jsonify(text="", page=page_num, source="none")

                native_text = page.get_text("text", clip=clip_rect).strip()
                if len(native_text) >= 5:
                    return jsonify(text=native_text, page=page_num, source="native")

                caps = capabilities(config, root)
                if caps.get("ocr"):
                    import pytesseract
                    pix = page.get_pixmap(clip=clip_rect, dpi=300)
                    pil_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    ocr_text = pytesseract.image_to_string(pil_img, lang="spa+eng").strip()
                    return jsonify(text=ocr_text or native_text, page=page_num, source="ocr")

                return jsonify(text=native_text, page=page_num, source="native")
        except Exception as e:
            LOG.error("Fallo en OCR de area: %s", e)
            return jsonify(error=f"Error en OCR de area: {e}"), 500

    @app.post("/api/process/<operation>")
    def handle(operation: str):
        if operation not in OPERATIONS:
            return jsonify(error="Herramienta desconocida."), 404
        if not request.content_length or request.content_length > app.config["MAX_CONTENT_LENGTH"]:
            return jsonify(error="Carga vacia o superior al limite de entrada."), 413
        token = request.headers.get("X-PDF-Job", secrets.token_hex(16))
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            return jsonify(error="Identificador de solicitud no valido."), 400
        try:
            ticket = queue.enter(token, operation, request.content_length)
        except AdmissionError as error:
            LOG.warning("Admision de trabajo: HTTP %s", error.status)
            try:
                if request.stream:
                    request.stream.close()
            except Exception:
                pass
            response = jsonify(error=str(error))
            response.headers["Connection"] = "close"
            if error.status in (429, 503):
                response.headers["Retry-After"] = "5"
            return response, error.status
        folder = None
        data = None
        delivery = None
        result = None
        failure = None
        uploads = []
        try:
            try:
                options = json.loads(request.form.get("options", "{}"))
            except json.JSONDecodeError:
                raise ProcessingError("Opciones JSON no validas.", 400) from None
            if not isinstance(options, dict):
                raise ProcessingError("Opciones no validas.", 400)
            uploads = request.files.getlist("files")
            if not uploads:
                raise ProcessingError("Seleccione al menos un archivo.", 400)
            if len(uploads) > file_limit(operation, config):
                raise ProcessingError(
                    f"Maximo {file_limit(operation, config)} archivos por sesion para esta herramienta.", 400)
            sizes = []
            for upload in uploads:
                upload.stream.seek(0, os.SEEK_END)
                sizes.append(upload.stream.tell())
                upload.stream.seek(0)
            if max(sizes) > config["max_file_mb"] * 1024 * 1024:
                raise ProcessingError(f"Cada archivo debe pesar como maximo {config['max_file_mb']} MB.", 413)
            if sum(sizes) > config["max_upload_mb"] * 1024 * 1024:
                raise ProcessingError(
                    f"El peso conjunto de los archivos no puede superar {config['max_upload_mb']} MB.", 413)
            folder = Path(tempfile.mkdtemp(prefix="job-", dir=runtime))
            files = []
            allowed_suffixes = allowed_upload_suffixes(operation)
            for index, upload in enumerate(uploads):
                suffix = Path(upload.filename or "").suffix.lower()
                if suffix not in allowed_suffixes:
                    raise ProcessingError("Extension no admitida.")
                name = f"entrada-{index:03}{suffix}"
                saved_path = folder / name
                upload.save(saved_path)
                upload.close()

                prefix = f"Archivo {index + 1}: " if len(uploads) > 1 else ""
                header = saved_path.read_bytes()[:16]
                if suffix == ".pdf" and not header.startswith(b"%PDF-"):
                    raise ProcessingError(f"{prefix}El documento no es un PDF valido.", 422)
                elif suffix in (".docx", ".xlsx", ".pptx") and not header.startswith(b"PK\x03\x04"):
                    raise ProcessingError(f"{prefix}El archivo de Office no tiene formato OpenXML válido.", 422)
                elif suffix in (".jpg", ".jpeg") and not header.startswith(b"\xff\xd8\xff"):
                    raise ProcessingError(f"{prefix}La imagen no coincide con el formato JPEG.", 422)
                elif suffix == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ProcessingError(f"{prefix}La imagen no coincide con el formato PNG.", 422)
                elif suffix == ".webp" and not (header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP"):
                    raise ProcessingError(f"{prefix}La imagen no coincide con el formato WebP.", 422)
                elif suffix == ".bmp" and not header.startswith(b"BM"):
                    raise ProcessingError(f"{prefix}La imagen no coincide con el formato BMP.", 422)
                elif suffix in (".tif", ".tiff") and not (header.startswith(b"II*\x00") or header.startswith(b"MM\x00*")):
                    raise ProcessingError(f"{prefix}La imagen no coincide con el formato TIFF.", 422)

                files.append(name)
            (folder / "job.json").write_text(json.dumps({
                "operation": operation, "files": files, "options": options, "config": config,
            }), encoding="utf-8")
            environment = os.environ.copy()
            for key in ("TEMP", "TMP", "TMPDIR"):
                environment[key] = str(folder)
            environment["OMP_THREAD_LIMIT"] = "1"
            environment["OPENBLAS_NUM_THREADS"] = "1"
            environment["MKL_NUM_THREADS"] = "1"
            environment["NUMEXPR_NUM_THREADS"] = "1"
            environment["OPENCV_FOR_THREADS_NUM"] = "1"
            environment["CT2_USE_MKL"] = "0"
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            job_memory_mb = config["max_job_memory_mb"]
            if operation in HEAVY_OPERATIONS or operation == "translate_layout":
                budget_mb = int(config.get("performance", {}).get("memory_budget_mb", job_memory_mb))
                job_memory_mb = max(job_memory_mb, min(2048, max(1536, budget_mb)))
            tree = ProcessTree(job_memory_mb)
            try:
                with subprocess.Popen(
                    worker_command(folder),
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    cwd=folder, env=environment,
                ) as child:
                    try:
                        tree.assign(child)
                        child.communicate(input=b"1", timeout=config["timeout_seconds"])
                    finally:
                        tree.close()
                        if child.poll() is None:
                            child.kill()
                        try:
                            try:
                                child.wait(timeout=5)
                            except TypeError:
                                child.wait()
                        except (subprocess.TimeoutExpired, OSError):
                            pass
                if child.returncode or not (folder / "result.json").is_file():
                    rc = child.returncode
                    # 0xC00000A1 (STATUS_WORKING_SET_QUOTA_EXCEEDED), 0xC0000128 (STATUS_PAGEFILE_QUOTA_EXCEEDED) o SIGKILL (-9)
                    if rc in (3221225633, -1073741671, 3221225768, -1073741528, -9):
                        raise ProcessingError(
                            f"El documento excedió la cuota de memoria RAM asignada al proceso ({job_memory_mb} MB). "
                            "Reduzca la resolución DPI o procese menos páginas.",
                            413,
                        )
                    # 0xC0000005 (STATUS_ACCESS_VIOLATION / Segfault en C++)
                    if rc in (-1073741819, 3221225477):
                        raise ProcessingError(
                            "El documento contiene estructuras o fuentes malformadas que provocaron un fallo en el motor nativo. "
                            "Pruebe primero a usar la herramienta 'Reparar PDF'.",
                            422,
                        )
                    if rc == 2:
                        raise ProcessingError("Error de sincronización con el subproceso del motor.", 500)
                    if rc:
                        raise ProcessingError(
                            f"El motor terminó inesperadamente (código {rc}). El documento podría estar dañado o exceder los recursos del sistema.",
                            500,
                        )
                    raise ProcessingError("El motor finalizó pero no generó el archivo de resultado.", 500)
            finally:
                tree.close()
            result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
            if not result["ok"]:
                if result.get("category"):
                    LOG.warning("Trabajo rechazado por el motor: %s", result["category"])
                raise ProcessingError(result["error"], result["status"])
            output = folder / result["file"]
            if output.parent != folder or not output.is_file():
                raise ProcessingError("Respuesta del motor no valida.", 500)
            size = output.stat().st_size
            if size > config["max_output_mb"] * 1024 * 1024:
                raise ProcessingError("Resultado demasiado grande.", 413)
            if size <= INLINE_RESULT_BYTES or operation == "inspect":
                data = output.read_bytes()
            else:
                delivery = outgoing / f"{folder.name}-{secrets.token_hex(8)}"
                output.replace(delivery)
        except ProcessingError as error:
            failure = (str(error), error.status)
        except subprocess.TimeoutExpired:
            failure = ("El trabajo excedio el tiempo limite. Use menos paginas.", 408)
        except (OSError, RuntimeError, KeyError, json.JSONDecodeError) as error:
            report_failure(error)
            LOG.error("Fallo de infraestructura: %s", type(error).__name__)
            failure = ("No se pudo completar el trabajo. Consulte al administrador.", 500)
        finally:
            try:
                for file_storage in request.files.getlist("files"):
                    try:
                        file_storage.close()
                    except Exception:
                        pass
                for upload in uploads:
                    try:
                        upload.close()
                    except Exception:
                        pass
                if folder is not None:
                    remove_job_folder(folder)
            except OSError as error:
                LOG.critical(
                    "No se pudo limpiar un espacio temporal; procesamiento bloqueado hasta reiniciar. "
                    "operation=%s exception=%s errno=%s winerror=%s previous_status=%s",
                    operation, type(error).__name__, error.errno, getattr(error, "winerror", None),
                    failure[1] if failure else None,
                )
                app.extensions["cleanup_failed"] = True
                failure = ("Fallo de eliminacion temporal. El administrador debe revisar el servidor.", 503)
                queue.close()
            queue.leave(ticket)
        if failure and delivery is not None:
            delivery.unlink(missing_ok=True)
        if failure:
            return jsonify(error=failure[0]), failure[1]
        if operation == "inspect":
            return app.response_class(data, mimetype="application/json")
        mimetype = mimetypes.guess_type(result["file"])[0] or "application/octet-stream"
        if delivery is not None:
            try:
                body = TransientFile(delivery)
            except OSError:
                delivery.unlink(missing_ok=True)
                return jsonify(error="No se pudo entregar el resultado."), 500
            response = app.response_class(body, mimetype=mimetype, direct_passthrough=True)
            response.headers["Content-Length"] = str(delivery.stat().st_size)
            response.headers.set("Content-Disposition", "attachment", filename=result["download_name"])
            response.headers["X-PDF-Cleanup"] = "on-delivery"
        else:
            response = send_file(
                io.BytesIO(data), mimetype=mimetype,
                as_attachment=True, download_name=result["download_name"], conditional=False, etag=False,
            )
            response.headers["X-PDF-Cleanup"] = "complete"
        response.headers["X-PDF-Notice"] = result["notice"]
        if operation in ("edit", "edit_text_pro") and result.get("editor_boundary"):
            response.headers["Content-Type"] = f'multipart/form-data; boundary={result["editor_boundary"]}'
        return response

    @app.before_request
    def block_after_cleanup_failure():
        if app.extensions.get("cleanup_failed") and request.method == "POST":
            return jsonify(error="Procesamiento detenido por fallo de limpieza. Contacte al administrador."), 503

    return app


def main():
    import argparse
    from waitress import serve

    parser = argparse.ArgumentParser()
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--calibrate", action="store_true",
                        help="Medir motores con documentos sinteticos, guardar perfil y salir.")
    args = parser.parse_args()
    if args.host:
        os.environ["PDF_HOST"] = args.host
    if args.port is not None:
        os.environ["PDF_PORT"] = str(args.port)
    application = create_app()
    config = application.extensions["pdf_settings"]
    if args.calibrate:
        from performance import calibrate
        try:
            print(json.dumps(calibrate(ROOT, config), indent=2), flush=True)
        finally:
            application.extensions["instance_lock"].close()
        return
    # Waitress desborda cuerpos grandes con TemporaryFile(); se mantienen dentro de runtime.
    tempfile.tempdir = str(application.extensions["spool_dir"])
    print(f"PDF LAN | {config['host']}:{config['port']} | build {CLIENT_BUILD}", flush=True)
    serve(application, host=config["host"], port=config["port"],
          threads=config["max_parallel_jobs"] + config["max_queued_jobs"] + 4,
          max_request_body_size=(config["max_upload_mb"] + 1) * 1024 * 1024,
          connection_limit=config["max_parallel_jobs"] + config["max_queued_jobs"] + 16,
          channel_timeout=config["timeout_seconds"] + config["queue_wait_seconds"] + 60,
          clear_untrusted_proxy_headers=True)


if __name__ == "__main__":
    main()
