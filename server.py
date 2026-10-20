from __future__ import annotations

import atexit
import io
import json
import logging
import mimetypes
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Request, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException

from isolation import InstanceLock, ProcessTree, worker_command
from pdf_engine import BULK_OPERATIONS, OPERATIONS, ProcessingError, capabilities, file_limit
from settings import ROOT, load_settings

CLIENT_BUILD = "2026-10-20-editor-lan-1"
LOG = logging.getLogger("pdf_lan")
INLINE_RESULT_BYTES = 64 * 1024 * 1024
STREAM_CHUNK = 1024 * 1024


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


def purge_folder(folder: Path):
    for path in folder.iterdir():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def create_app(root: Path = ROOT) -> Flask:
    config = load_settings(root)
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
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
    )
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
    app.extensions["pdf_settings"] = config
    app.extensions["spool_dir"] = spool

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
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; "
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
                       secure_transport=config["secure_transport"])

    @app.get("/desktop/download")
    def desktop_download():
        return send_file(ROOT / "desktop" / "Folio-Desktop.ps1", as_attachment=True,
                         download_name="Folio-Desktop.ps1", mimetype="text/plain", conditional=False, etag=False)

    @app.post("/api/process/<operation>")
    def handle(operation: str):
        if operation not in OPERATIONS:
            return jsonify(error="Herramienta desconocida."), 404
        if not gate.acquire(blocking=False):
            response = jsonify(error="Todos los motores estan ocupados. Intente nuevamente en unos segundos.")
            response.headers["Retry-After"] = "5"
            return response, 429
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
            for index, upload in enumerate(uploads):
                suffix = Path(upload.filename or "").suffix.lower()
                if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp",
                                  ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".html", ".htm",
                                  ".heic", ".heif", ".epub"}:
                    raise ProcessingError("Extension no admitida.")
                name = f"entrada-{index:03}{suffix}"
                upload.save(folder / name)
                upload.close()
                files.append(name)
            (folder / "job.json").write_text(json.dumps({
                "operation": operation, "files": files, "options": options, "config": config,
            }), encoding="utf-8")
            environment = os.environ.copy()
            for key in ("TEMP", "TMP", "TMPDIR"):
                environment[key] = str(folder)
            environment["OMP_THREAD_LIMIT"] = "1"
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            tree = ProcessTree(config["max_job_memory_mb"])
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
                        child.wait()
                if child.returncode or not (folder / "result.json").is_file():
                    raise ProcessingError("El motor no pudo terminar el trabajo.", 500)
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
            LOG.error("Fallo de infraestructura: %s", type(error).__name__)
            failure = ("No se pudo completar el trabajo. Consulte al administrador.", 500)
        finally:
            try:
                for upload in uploads:
                    upload.close()
                if folder is not None:
                    shutil.rmtree(folder)
            except OSError:
                LOG.critical("No se pudo limpiar un espacio temporal; procesamiento bloqueado hasta reiniciar.")
                app.extensions["cleanup_failed"] = True
                failure = ("Fallo de eliminacion temporal. El administrador debe revisar el servidor.", 503)
            gate.release()
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
            response.headers.set("Content-Disposition", "attachment", filename=result["file"])
            response.headers["X-PDF-Cleanup"] = "on-delivery"
        else:
            response = send_file(
                io.BytesIO(data), mimetype=mimetype,
                as_attachment=True, download_name=result["file"], conditional=False, etag=False,
            )
            response.headers["X-PDF-Cleanup"] = "complete"
        response.headers["X-PDF-Notice"] = result["notice"]
        if operation == "edit_text_pro" and result.get("editor_boundary"):
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
          threads=config["max_parallel_jobs"] * 2 + 4,
          max_request_body_size=(config["max_upload_mb"] + 1) * 1024 * 1024,
          channel_timeout=config["timeout_seconds"] + 60, clear_untrusted_proxy_headers=True)


if __name__ == "__main__":
    main()
