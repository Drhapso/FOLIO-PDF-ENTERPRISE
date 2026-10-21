from __future__ import annotations

import copy
import shutil
import zipfile
from pathlib import Path


def prepare_export(folder: Path, result: dict) -> None:
    output = folder / result["file"]
    if result.get("editor_boundary"):
        name = "EVA00.pdf"
        temporary = folder / "export.multipart"
        with output.open("rb") as source, temporary.open("wb") as destination:
            boundary = source.readline()
            disposition = source.readline()
            if (boundary != f'--{result["editor_boundary"]}\r\n'.encode("ascii")
                    or not disposition.startswith(b'Content-Disposition: form-data; name="document";')):
                raise ValueError("Respuesta multipart de edicion no valida.")
            destination.write(boundary)
            destination.write(
                f'Content-Disposition: form-data; name="document"; filename="{name}"\r\n'.encode("ascii")
            )
            shutil.copyfileobj(source, destination, 1024 * 1024)
        temporary.replace(output)
    elif output.suffix.lower() == ".zip":
        temporary = folder / "export.zip"
        with zipfile.ZipFile(output) as source:
            entries = [entry for entry in source.infolist() if not entry.is_dir()]
            name = "EVA00.zip"
            with zipfile.ZipFile(temporary, "w", allowZip64=True) as destination:
                for index, entry in enumerate(entries, 1):
                    filename = f"EVA00_{index:02d}{Path(entry.filename).suffix}"
                    info = copy.copy(entry)
                    info.filename = str(Path(entry.filename).parent / filename).replace("\\", "/")
                    with source.open(entry) as reader, destination.open(info, "w", force_zip64=True) as writer:
                        shutil.copyfileobj(reader, writer, 1024 * 1024)
        temporary.replace(output)
    else:
        name = f"EVA00{output.suffix}"
    result["download_name"] = name
