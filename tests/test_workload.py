from __future__ import annotations

import io
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pymupdf as pdf

from server import CLIENT_BUILD, create_app
from settings import DEFAULTS, load_settings
from workload import AdmissionError, MB, WorkloadQueue


class WorkloadTests(unittest.TestCase):
    def queue(self, **overrides):
        config = dict(DEFAULTS, max_parallel_jobs=2, max_heavy_jobs=1, **overrides)
        return WorkloadQueue(config, threading.BoundedSemaphore(config["max_parallel_jobs"]))

    def wait_pending(self, queue, count):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with queue.condition:
                if len(queue.pending) == count:
                    return
            time.sleep(.005)
        self.fail("Queue did not reach expected state")

    def test_heavy_limit_reserves_capacity_for_light_work(self):
        queue = self.queue()
        first = queue.enter("a", "ocr", 100)
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(queue.enter, "b", "ocr", 100)
            self.wait_pending(queue, 1)
            light = queue.enter("c", "inspect", 100)
            self.assertEqual(queue.status("b")["position"], 1)
            self.assertTrue(queue.status("b")["heavy"])
            queue.leave(light)
            queue.leave(first)
            admitted = waiting.result(timeout=3)
            queue.leave(admitted)
        self.assertEqual(queue.active, {})

    def test_fifo_queue_capacity_and_duplicate_tokens(self):
        queue = self.queue(max_queued_jobs=1)
        tickets = [queue.enter(str(index), "inspect", 100) for index in range(2)]
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(queue.enter, "waiting", "inspect", 100)
            self.wait_pending(queue, 1)
            with self.assertRaises(AdmissionError) as full:
                queue.enter("extra", "inspect", 100)
            self.assertEqual(full.exception.status, 429)
            with self.assertRaises(AdmissionError) as duplicate:
                queue.enter("waiting", "inspect", 100)
            self.assertEqual(duplicate.exception.status, 409)
            queue.leave(tickets[0])
            ticket = waiting.result(timeout=3)
            queue.leave(ticket)
        queue.leave(tickets[1])

    def test_timeout_and_cancel_release_queue_bytes(self):
        queue = self.queue(queue_wait_seconds=.03)
        heavy = queue.enter("first", "ocr", 100)
        with self.assertRaises(AdmissionError) as expired:
            queue.enter("expires", "ocr", 100)
        self.assertEqual(expired.exception.status, 503)
        self.assertEqual(queue.pending, [])
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(queue.enter, "cancel", "ocr", 100)
            self.wait_pending(queue, 1)
            self.assertTrue(queue.cancel("cancel"))
            with self.assertRaises(AdmissionError):
                waiting.result(timeout=3)
        queue.leave(heavy)
        self.assertEqual(queue.pending, [])
        self.assertFalse(queue.cancel("absent"))

    def test_active_and_queued_byte_budgets(self):
        queue = self.queue(max_active_upload_mb=16, max_queued_upload_mb=16)
        first = queue.enter("first", "inspect", 10 * MB)
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(queue.enter, "waiting", "inspect", 10 * MB)
            self.wait_pending(queue, 1)
            with self.assertRaises(AdmissionError) as full:
                queue.enter("large", "inspect", 10 * MB)
            self.assertEqual(full.exception.status, 429)
            with self.assertRaises(AdmissionError) as oversized:
                queue.enter("too-large", "inspect", 17 * MB)
            self.assertEqual(oversized.exception.status, 413)
            queue.leave(first)
            queue.leave(waiting.result(timeout=3))

    def test_cleanup_failure_wakes_waiters(self):
        queue = self.queue()
        first = queue.enter("first", "ocr", 100)
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(queue.enter, "waiting", "ocr", 100)
            self.wait_pending(queue, 1)
            queue.close()
            with self.assertRaises(AdmissionError) as closed:
                waiting.result(timeout=3)
            self.assertEqual(closed.exception.status, 503)
        queue.leave(first)

    def test_large_input_is_heavy_even_for_inspection(self):
        queue = self.queue()
        ticket = queue.enter("large", "inspect", 11 * MB)
        self.assertTrue(queue.status("large")["heavy"])
        queue.leave(ticket)

    def test_fifo_within_same_class(self):
        queue = self.queue()
        first = queue.enter("first", "ocr", 100)
        with ThreadPoolExecutor(max_workers=2) as pool:
            second = pool.submit(queue.enter, "second", "ocr", 100)
            self.wait_pending(queue, 1)
            third = pool.submit(queue.enter, "third", "ocr", 100)
            self.wait_pending(queue, 2)
            queue.leave(first)
            second_ticket = second.result(timeout=3)
            self.assertFalse(third.done())
            queue.leave(second_ticket)
            queue.leave(third.result(timeout=3))

    def test_twelve_clients_finish_without_exceeding_limits(self):
        queue = self.queue()
        start = threading.Barrier(12)
        peaks = []
        order = []

        def client(number):
            start.wait(timeout=5)
            ticket = queue.enter(str(number), "ocr", 100)
            try:
                with queue.condition:
                    peaks.append(len(queue.active))
                    order.append(number)
                time.sleep(.015)
            finally:
                queue.leave(ticket)

        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(client, range(12)))
        self.assertEqual(len(order), 12)
        self.assertEqual(max(peaks), 1)
        self.assertEqual(queue.pending, [])
        self.assertEqual(queue.active, {})

    def test_settings_validate_limits_and_clamp_heavy_concurrency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            path = root / "config" / "site_config.json"
            path.write_text(json.dumps({"max_queued_jobs": 25}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_settings(root)
            path.write_text(json.dumps({"max_parallel_jobs": 1, "max_heavy_jobs": 2}), encoding="utf-8")
            config = load_settings(root)
            self.assertEqual(config["max_heavy_jobs"], 1)

    def test_installed_profile_exact_limits(self):
        from server import ROOT

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "site_config.json").write_bytes(
                (ROOT / "config" / "site_config.json").read_bytes()
            )
            config = load_settings(root)
            self.assertEqual(config["max_file_mb"], 1024)
            self.assertEqual(config["max_upload_mb"], 1024)
            self.assertEqual(config["recommended_upload_mb"], 3)
            self.assertEqual(config["max_queued_jobs"], 12)
            self.assertEqual(config["queue_wait_seconds"], 45)
            self.assertLessEqual(config["max_heavy_jobs"], 2)
            self.assertLessEqual(config["max_parallel_jobs"], 5)

    def test_production_profile_preserves_one_gib(self):
        from server import ROOT

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "site_config.json").write_bytes(
                (ROOT / "config" / "production_queue.json").read_bytes()
            )
            config = load_settings(root)
            self.assertEqual(config["max_file_mb"], 1024)
            self.assertEqual(config["max_upload_mb"], 1024)
            self.assertEqual(config["max_output_mb"], 2048)
            self.assertTrue(config["editor_live_preview"])
            queue = WorkloadQueue(config, threading.BoundedSemaphore(config["max_parallel_jobs"]))
            first = queue.enter("one-gib", "rotate", 1024 * MB + 1000)
            self.assertTrue(first.heavy)
            with ThreadPoolExecutor(max_workers=1) as pool:
                waiting = pool.submit(queue.enter, "another-gib", "rotate", 1024 * MB + 1000)
                self.wait_pending(queue, 1)
                self.assertEqual(queue.status("another-gib")["state"], "queued")
                queue.leave(first)
                queue.leave(waiting.result(timeout=3))


class QueueApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app = create_app(self.root)
        self.app.testing = True
        self.queue = self.app.extensions["workload_queue"]
        self.headers = {"Origin": "http://localhost", "X-PDF-Client": CLIENT_BUILD}
        with pdf.open() as doc:
            doc.new_page().insert_text((40, 60), "ORIGINAL")
            self.source = doc.tobytes()

    def tearDown(self):
        self.app.extensions["instance_lock"].close()
        self.temporary.cleanup()

    def post(self, token):
        with self.app.test_client() as client:
            response = client.post("/api/process/rotate", headers=dict(
                self.headers, **{"X-PDF-Job": token}
            ), data={"files": (io.BytesIO(self.source), "test.pdf"), "options": "{}"})
            data = response.get_data()
            response.close()
            return response.status_code, data

    def test_wait_status_cancel_and_no_staging(self):
        queue = self.queue
        held = [queue.enter(f"held-{n}", "inspect", 100)
                for n in range(queue.config["max_parallel_jobs"])]
        token = "a" * 32
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                waiting = pool.submit(self.post, token)
                deadline = time.monotonic() + 3
                while queue.status(token) is None and time.monotonic() < deadline:
                    time.sleep(.005)
                with self.app.test_client() as client:
                    status = client.get("/api/queue/" + token)
                    self.assertEqual(status.json["state"], "queued")
                    self.assertNotIn("files", status.json)
                    self.assertEqual(list((self.root / "runtime").glob("job-*")), [])
                    self.assertEqual(client.post("/api/queue/" + token + "/cancel").status_code, 403)
                    cancelled = client.post("/api/queue/" + token + "/cancel", headers=self.headers)
                    self.assertEqual(cancelled.status_code, 200)
                self.assertEqual(waiting.result(timeout=3)[0], 409)
                self.assertIsNone(queue.status(token))
        finally:
            for ticket in held:
                queue.leave(ticket)

    def test_queued_request_proceeds_and_releases_admission(self):
        held = [self.queue.enter(f"held-{n}", "inspect", 100)
                for n in range(self.queue.config["max_parallel_jobs"])]
        token = "b" * 32
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                waiting = pool.submit(self.post, token)
                deadline = time.monotonic() + 3
                while self.queue.status(token) is None and time.monotonic() < deadline:
                    time.sleep(.005)
                self.queue.leave(held.pop())
                status, data = waiting.result(timeout=10)
                self.assertEqual(status, 200)
                self.assertTrue(data.startswith(b"%PDF"))
                self.assertIsNone(self.queue.status(token))
        finally:
            for ticket in held:
                self.queue.leave(ticket)
        self.assertEqual(list((self.root / "runtime").glob("job-*")), [])

    def test_invalid_token_is_rejected(self):
        self.assertEqual(self.post("invalid")[0], 400)

    def test_failure_releases_admission_and_token(self):
        self.source = b"not a PDF"
        token = "c" * 32
        self.assertEqual(self.post(token)[0], 422)
        self.assertIsNone(self.queue.status(token))
        self.assertEqual(self.queue.active, {})
        self.assertEqual(list((self.root / "runtime").glob("job-*")), [])

    def test_file_limit_boundary_and_oversize_release(self):
        config = self.app.extensions["pdf_settings"]
        exact_mb = len(self.source) / MB
        with self.app.test_client() as client:
            with patch.dict(config, max_file_mb=exact_mb):
                self.assertEqual(self.post("d" * 32)[0], 200)
            with patch.dict(config, max_file_mb=(len(self.source) - 1) / MB):
                self.assertEqual(self.post("e" * 32)[0], 413)
            body_limit = self.app.config["MAX_CONTENT_LENGTH"]
            response = client.post(
                "/api/process/rotate", headers=self.headers,
                environ_overrides={"CONTENT_LENGTH": str(body_limit + 1)},
            )
            self.assertEqual(response.status_code, 413)
            response.close()
        self.assertEqual(self.queue.active, {})


if __name__ == "__main__":
    unittest.main()
