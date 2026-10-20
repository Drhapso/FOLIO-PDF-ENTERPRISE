from __future__ import annotations

import ctypes
import json
import math
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from isolation import ProcessTree, worker_command


def hardware() -> dict:
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
                (name, ctypes.c_uint64) for name in (
                    "total", "available", "page_total", "page_available",
                    "virtual_total", "virtual_available", "extended")]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        total, available = status.total, status.available
    else:
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        available = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    return {"cpu_count": os.cpu_count() or 1,
            "total_memory_mb": total // (1024 * 1024),
            "available_memory_mb": available // (1024 * 1024)}


def tune(config: dict, profile: dict | None = None) -> dict:
    machine = hardware()
    # Reserva RAM para Windows, el servidor, cargas y las demas aplicaciones.
    budget = int(min(machine["total_memory_mb"] * .5, machine["available_memory_mb"] * .6))
    if budget < 256:
        raise RuntimeError("Memoria disponible insuficiente para iniciar los motores PDF.")
    slots = min(config["max_parallel_jobs"], max(1, machine["cpu_count"] // 2),
                max(1, budget // 1024))
    if profile is not None:
        if not isinstance(profile, dict) or profile.get("version") != 1 or not isinstance(profile.get("samples"), dict):
            raise ValueError("Perfil de rendimiento no valido; vuelva a calibrar.")
        for sample in profile["samples"].values():
            if not isinstance(sample, dict):
                raise ValueError("Medicion de rendimiento no valida; vuelva a calibrar.")
            seconds = sample.get("seconds_per_page")
            if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
                raise ValueError("Medicion de rendimiento no valida; vuelva a calibrar.")
        render = profile["samples"].get("render")
        if render is None:
            raise ValueError("Perfil sin medicion de render; vuelva a calibrar.")
        slots = min(slots, max(1, int(1 / render["seconds_per_page"])))
    config["max_parallel_jobs"] = slots
    config["max_job_memory_mb"] = min(config["max_job_memory_mb"], budget // slots)
    config["timeout_seconds"] = min(config["timeout_seconds"], 120)
    return {"calibrated": profile is not None, "cpu_count": machine["cpu_count"],
            "memory_budget_mb": budget, "parallel_jobs": slots,
            "job_memory_mb": config["max_job_memory_mb"],
            "timeout_seconds": config["timeout_seconds"],
            "measured_at": profile.get("measured_at") if profile else None,
            "ocr_tested": profile.get("ocr_tested", False) if profile else False,
            "samples": profile["samples"] if profile else {}}


def benchmark(folder: Path, config: dict, root: Path) -> dict:
    import pymupdf as pdf
    from pdf_engine import process

    source = folder / "synthetic.pdf"
    with pdf.open() as doc:
        for index in range(12):
            page = doc.new_page()
            for row in range(30):
                page.insert_text((45, 50 + row * 23),
                                 f"EVA PDF PERFORMANCE TEST {index + 1} / {row + 1}", fontsize=11)
            page.draw_rect(pdf.Rect(35, 30, 550, 760), color=(.3, .2, .5))
        doc.save(source)
    samples = {}
    for name, operation, count, options in (
        ("combine", "merge", 24, {}),
        ("render", "pdf_to_images", 12, {"dpi": 150}),
        ("ocr", "ocr", 1, {"dpi": 200}),
    ):
        languages = config["ocr_language"].split("+")
        if name == "ocr" and not all((root / "models" / f"{lang}.traineddata").is_file()
                                     for lang in languages):
            continue
        work = folder / name
        work.mkdir()
        input_path = source
        if name == "ocr":
            input_path = work / "single.pdf"
            with pdf.open(source) as doc, pdf.open() as single:
                single.insert_pdf(doc, from_page=0, to_page=0)
                single.save(input_path)
        durations = []
        for _ in range(3):
            start = time.perf_counter()
            process(operation, [input_path, input_path] if name == "combine" else [input_path],
                    options, work, config, root)
            durations.append(time.perf_counter() - start)
        seconds = max(durations) / count
        samples[name] = {"seconds_per_page": seconds, "sample_pages": count, "runs": 3,
                         "estimated_pages_per_job": max(1, int(config["timeout_seconds"] * .5 / seconds))}
    return {"version": 1, "measured_at": datetime.now(timezone.utc).isoformat(),
            "hardware": hardware(), "samples": samples,
            "ocr_tested": "ocr" in samples}


def calibrate(root: Path, config: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="job-calibration-", dir=root / "runtime") as temporary:
        folder = Path(temporary)
        (folder / "job.json").write_text(json.dumps({
            "operation": "_benchmark", "config": config, "files": [], "options": {},
        }), encoding="utf-8")
        tree = ProcessTree(config["max_job_memory_mb"])
        environment = os.environ.copy()
        environment["OMP_THREAD_LIMIT"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for key in ("TEMP", "TMP", "TMPDIR"):
            environment[key] = str(folder)
        try:
            with subprocess.Popen(worker_command(folder),
                                  stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, cwd=folder, env=environment) as child:
                try:
                    tree.assign(child)
                    child.communicate(input=b"1", timeout=120)
                finally:
                    tree.close()
                    if child.poll() is None:
                        child.kill()
                    child.wait()
                if child.returncode:
                    raise RuntimeError("La calibracion no termino correctamente.")
        finally:
            tree.close()
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        if not result["ok"]:
            raise RuntimeError(f"Calibracion rechazada: {result['error']}")
        profile = json.loads((folder / "performance.json").read_text(encoding="utf-8"))
        tune(config.copy(), profile)
        target = root / "instance" / "performance.json"
        staging = target.with_suffix(".tmp")
        staging.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        staging.replace(target)
        return profile
