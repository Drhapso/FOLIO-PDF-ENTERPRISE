from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from isolation import worker_command
from settings import ROOT


class DistributionTests(unittest.TestCase):
    def test_source_worker_command(self):
        folder = Path("trabajo temporal")
        with patch.object(sys, "frozen", False, create=True):
            command = worker_command(folder)
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(Path(command[1]), ROOT / "worker.py")
        self.assertEqual(command[2], str(folder))

    def test_frozen_worker_command(self):
        with patch.object(sys, "frozen", True, create=True):
            self.assertEqual(worker_command(Path("trabajo")),
                             [sys.executable, "--worker", "trabajo"])

    def entry(self):
        spec = importlib.util.spec_from_file_location("folio_frozen_entry", ROOT / "deploy" / "frozen_entry.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_entry_worker_dispatch(self):
        with patch.object(sys, "argv", ["Folio.exe", "--worker", "trabajo"]), \
                patch("worker.main", return_value=0) as worker:
            self.assertEqual(self.entry().main(), 0)
            worker.assert_called_once_with()
            self.assertEqual(sys.argv, ["Folio.exe", "trabajo"])

    def test_entry_rejects_invalid_worker_arguments(self):
        with patch.object(sys, "argv", ["Folio.exe", "--worker"]):
            with self.assertRaises(SystemExit):
                self.entry().main()

    def test_entry_server_dispatch(self):
        with patch.object(sys, "argv", ["Folio.exe", "--host", "127.0.0.1"]), \
                patch("server.main") as server:
            self.assertEqual(self.entry().main(), 0)
            server.assert_called_once_with()
