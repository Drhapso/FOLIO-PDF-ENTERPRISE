from __future__ import annotations

import json
import subprocess
import sys
import warnings
import zipfile
from pathlib import Path
from xml.etree.ElementTree import ParseError

import pymupdf
from PIL import Image, UnidentifiedImageError

from pdf_engine import ProcessingError, process
from settings import ROOT


def main():
    if sys.stdin.buffer.read(1) != b"1":
        return 2
    folder = Path(sys.argv[1]).resolve()
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    config = job["config"]
    Image.MAX_IMAGE_PIXELS = config["max_render_pixels"]
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    try:
        if job["operation"] == "_benchmark":
            from performance import benchmark
            profile = benchmark(folder, config, ROOT)
            (folder / "performance.json").write_text(json.dumps(profile), encoding="utf-8")
            result = {"file": "performance.json"}
        else:
            result = process(job["operation"], [folder / name for name in job["files"]],
                             job["options"], folder, config, ROOT)
        payload = {"ok": True, **result}
    except ProcessingError as error:
        payload = {"ok": False, "error": str(error), "status": error.status}
    except subprocess.TimeoutExpired:
        payload = {"ok": False, "error": "La conversion excedio el tiempo limite.", "status": 408}
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning,
            ValueError, RuntimeError, OSError, zipfile.BadZipFile, ParseError) as error:
        # No se registra el mensaje del motor: puede contener texto o claves del documento.
        payload = {"ok": False, "error": "Archivo danado, incompatible o no procesable.",
                   "status": 422, "category": type(error).__name__}
    (folder / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
