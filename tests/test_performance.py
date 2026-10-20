from __future__ import annotations

import unittest
from unittest.mock import patch

from performance import tune
from settings import DEFAULTS


class PerformanceTests(unittest.TestCase):
    def test_memory_and_cpu_budget(self):
        config = DEFAULTS.copy()
        machine = {"cpu_count": 4, "total_memory_mb": 8192, "available_memory_mb": 4096}
        with patch("performance.hardware", return_value=machine):
            result = tune(config)
        self.assertEqual(config["max_parallel_jobs"], 2)
        self.assertEqual(config["max_job_memory_mb"], 1228)
        self.assertLessEqual(config["max_parallel_jobs"] * config["max_job_memory_mb"], 2457)
        self.assertEqual(config["timeout_seconds"], 120)
        self.assertFalse(result["calibrated"])

    def test_measured_latency_reduces_concurrency(self):
        config = DEFAULTS.copy()
        config["timeout_seconds"] = 900
        machine = {"cpu_count": 16, "total_memory_mb": 32768, "available_memory_mb": 24000}
        with patch("performance.hardware", return_value=machine):
            result = tune(config, {"version": 1, "samples": {"render": {"seconds_per_page": .6}}})
        self.assertEqual(config["max_parallel_jobs"], 1)
        self.assertEqual(config["timeout_seconds"], 120)
        self.assertTrue(result["calibrated"])

    def test_insufficient_memory_and_invalid_measurement(self):
        machine = {"cpu_count": 4, "total_memory_mb": 8192, "available_memory_mb": 200}
        with patch("performance.hardware", return_value=machine):
            with self.assertRaisesRegex(RuntimeError, "Memoria"):
                tune(DEFAULTS.copy())
        machine["available_memory_mb"] = 4096
        with patch("performance.hardware", return_value=machine):
            with self.assertRaisesRegex(ValueError, "Medicion"):
                tune(DEFAULTS.copy(), {"version": 1, "samples": {"render": {"seconds_per_page": 0}}})
