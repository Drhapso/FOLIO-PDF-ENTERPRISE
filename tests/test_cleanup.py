from __future__ import annotations

import ctypes
import os
import shutil
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from server import remove_job_folder


def windows_error(code: int) -> OSError:
    error = OSError("synthetic lock")
    error.winerror = code
    return error


class CleanupTests(unittest.TestCase):
    def test_sharing_violation_retries_until_removed(self):
        with patch("server.shutil.rmtree", side_effect=[windows_error(32), None]) as remove, \
             patch("server.time.sleep") as sleep:
            remove_job_folder(Path("unused"))
        self.assertEqual(remove.call_count, 2)
        sleep.assert_called_once_with(0.1)

    def test_permanent_lock_is_not_silently_ignored(self):
        with patch("server.shutil.rmtree", side_effect=windows_error(32)) as remove, \
             patch("server.time.sleep") as sleep:
            with self.assertRaises(OSError):
                remove_job_folder(Path("unused"))
        self.assertEqual(remove.call_count, 6)
        self.assertEqual(sum(args.args[0] for args in sleep.call_args_list), 3.1)

    def test_access_denied_does_not_retry(self):
        with patch("server.shutil.rmtree", side_effect=windows_error(5)) as remove:
            with self.assertRaises(OSError):
                remove_job_folder(Path("unused"))
        remove.assert_called_once()

    def test_missing_directory_is_already_clean(self):
        with tempfile.TemporaryDirectory() as temporary:
            remove_job_folder(Path(temporary) / "absent")

    @unittest.skipUnless(os.name == "nt", "Windows file sharing")
    def test_real_windows_file_lock_released_during_cleanup(self):
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "job-test"
            folder.mkdir()
            path = folder / "input.pdf"
            path.write_bytes(b"synthetic")
            handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
            self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
            with self.assertRaises(OSError) as original_failure:
                shutil.rmtree(folder)
            self.assertEqual(original_failure.exception.winerror, 32)
            timer = threading.Timer(0.25, kernel.CloseHandle, args=(handle,))
            timer.start()
            try:
                remove_job_folder(folder)
            finally:
                timer.join()
            self.assertFalse(folder.exists())


if __name__ == "__main__":
    unittest.main()
