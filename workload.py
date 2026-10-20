from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

HEAVY_OPERATIONS = frozenset({
    "ocr", "rasterize", "grayscale", "pdf_to_images", "office_to_pdf",
    "pdf_to_docx", "pdf_to_xlsx", "pdf_to_pptx", "html_to_pdf",
    "heic_to_jpg", "epub_to_pdf", "pdf_to_epub",
})
MB = 1024 * 1024


class AdmissionError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


@dataclass
class Ticket:
    token: str
    size: int
    heavy: bool
    entered: float = field(default_factory=time.monotonic)
    state: str = "queued"


class WorkloadQueue:
    """FIFO por clase; los trabajos pesados no ocupan todos los motores."""

    def __init__(self, config: dict, gate: threading.BoundedSemaphore):
        self.config = config
        self.gate = gate
        self.condition = threading.Condition()
        self.pending: list[Ticket] = []
        self.active: dict[str, Ticket] = {}
        self.closed = False

    def _fits(self, ticket: Ticket) -> bool:
        return (
            len(self.active) < self.config["max_parallel_jobs"]
            and (not ticket.heavy or sum(item.heavy for item in self.active.values())
                 < self.config["max_heavy_jobs"])
            and sum(item.size for item in self.active.values()) + ticket.size
            <= self.config["max_active_upload_mb"] * MB
        )

    def enter(self, token: str, operation: str, size: int) -> Ticket:
        ticket = Ticket(token, size, operation in HEAVY_OPERATIONS
                        or size >= self.config["heavy_upload_mb"] * MB)
        with self.condition:
            if self.closed:
                raise AdmissionError("Procesamiento detenido por fallo de limpieza.", 503)
            if token in self.active or any(item.token == token for item in self.pending):
                raise AdmissionError("Esta solicitud ya esta registrada. No la envie de nuevo.", 409)
            if size > self.config["max_active_upload_mb"] * MB:
                raise AdmissionError("La carga supera el presupuesto efectivo de entrada. Divida el trabajo.", 413)
            can_start = self._fits(ticket) and not any(self._fits(item) for item in self.pending)
            if not can_start and (
                len(self.pending) >= self.config["max_queued_jobs"]
                or sum(item.size for item in self.pending) + size > self.config["max_queued_upload_mb"] * MB
            ):
                raise AdmissionError("La cola esta llena. Intente mas tarde o reduzca el lote.", 429)
            self.pending.append(ticket)
            try:
                while True:
                    if self.closed:
                        raise AdmissionError("Procesamiento detenido por fallo de limpieza.", 503)
                    if ticket.state == "cancelled":
                        raise AdmissionError("Solicitud cancelada antes de iniciar el procesamiento.", 409)
                    eligible = next((item for item in self.pending if self._fits(item)), None)
                    if eligible is ticket and self.gate.acquire(blocking=False):
                        self.pending.remove(ticket)
                        self.active[token] = ticket
                        ticket.state = "processing"
                        self.condition.notify_all()
                        return ticket
                    remaining = self.config["queue_wait_seconds"] - (time.monotonic() - ticket.entered)
                    if remaining <= 0:
                        raise AdmissionError("Tiempo de espera agotado. Reduzca el lote e intente mas tarde.", 503)
                    self.condition.wait(timeout=min(remaining, .25))
            except BaseException:
                if ticket in self.pending:
                    self.pending.remove(ticket)
                self.condition.notify_all()
                raise

    def leave(self, ticket: Ticket) -> None:
        with self.condition:
            if self.active.pop(ticket.token, None) is not None:
                self.gate.release()
            self.condition.notify_all()

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()

    def status(self, token: str) -> dict | None:
        with self.condition:
            ticket = self.active.get(token)
            if ticket is None:
                ticket = next((item for item in self.pending if item.token == token), None)
            if ticket is None:
                return None
            position = self.pending.index(ticket) + 1 if ticket.state == "queued" else 0
            return {
                "state": ticket.state, "position": position, "heavy": ticket.heavy,
                "active": len(self.active), "waiting": len(self.pending),
                "active_heavy": sum(item.heavy for item in self.active.values()),
                "elapsed_seconds": round(time.monotonic() - ticket.entered, 1),
                "max_wait_seconds": self.config["queue_wait_seconds"],
                "notice": "Posicion de llegada; las tareas ligeras pueden avanzar mientras esperan las pesadas.",
            }

    def cancel(self, token: str) -> bool:
        with self.condition:
            ticket = next((item for item in self.pending if item.token == token), None)
            if ticket is None:
                return False
            self.pending.remove(ticket)
            ticket.state = "cancelled"
            self.condition.notify_all()
            return True
