from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

import pymupdf

from export_names import prepare_export
from server import CLIENT_BUILD, create_app


class ExportNamesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_fixed_names_preserve_formats_and_repeat_without_state(self):
        for suffix in (".pdf", ".docx", ".xlsx", ".pptx", ".epub", ".txt"):
            with self.subTest(suffix=suffix):
                output = self.root / f"result{suffix}"
                output.write_bytes(b"unchanged bytes")
                for _ in range(2):
                    result = {"file": output.name}
                    prepare_export(self.root, result)
                    self.assertEqual(result["download_name"], f"EVA00{suffix}")
                    self.assertEqual(output.read_bytes(), b"unchanged bytes")

    def test_zip_members_preserve_bytes_format_and_directories(self):
        output = self.root / "batch.zip"
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("01/a.pdf", b"pdf bytes")
            archive.writestr("02/b.docx", b"office bytes")
        result = {"file": output.name}
        prepare_export(self.root, result)
        self.assertEqual(result["download_name"], "EVA00.zip")
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.namelist(), ["01/EVA00_01.pdf", "02/EVA00_02.docx"])
            self.assertEqual(archive.read(archive.namelist()[0]), b"pdf bytes")
            self.assertEqual(archive.read(archive.namelist()[1]), b"office bytes")

    def test_zip_indices_restart_and_remain_unique_above_99(self):
        for _ in range(2):
            output = self.root / "batch.zip"
            with zipfile.ZipFile(output, "w") as archive:
                for index in range(101):
                    archive.writestr(f"page-{index}.pdf", str(index).encode())
            prepare_export(self.root, {"file": output.name})
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist(),
                                 [f"EVA00_{index:02d}.pdf" for index in range(1, 102)])

    def test_invalid_multipart_is_rejected(self):
        output = self.root / "invalid.multipart"
        output.write_bytes(b"invalid")
        with self.assertRaises(ValueError):
            prepare_export(self.root, {"file": output.name, "editor_boundary": "boundary"})


class ExportAPITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = create_app(self.root)
        self.addCleanup(lambda: self.app.extensions["instance_lock"].close())
        with pymupdf.open() as doc:
            doc.new_page().insert_text((72, 90), "ORIGINAL")
            self.source = doc.tobytes()

    def call(self, operation, options=None):
        response = self.app.test_client().post(
            "/api/process/" + operation,
            headers={"Origin": "http://localhost", "X-PDF-Client": CLIENT_BUILD},
            data={"options": json.dumps(options or {}),
                  "files": [(io.BytesIO(self.source), "private.pdf")]},
        )
        self.addCleanup(response.close)
        response.get_data()
        response.request.environ["wsgi.input"].close()
        return response

    def test_fixed_names_preview_failure_streaming_and_restart(self):
        self.assertEqual(self.call("inspect").status_code, 200)
        self.assertEqual(self.call("rotate", {"angle": 91}).status_code, 422)
        first = self.call("rotate", {"angle": 90})
        self.assertEqual(first.status_code, 200)
        self.assertIn('filename=EVA00.pdf', first.headers["Content-Disposition"])
        with patch("server.INLINE_RESULT_BYTES", 1):
            streamed = self.call("extract_text")
        self.assertEqual(streamed.status_code, 200)
        self.assertIn('filename=EVA00.txt', streamed.headers["Content-Disposition"])
        streamed.close()
        self.assertEqual(list((self.root / "runtime" / "outgoing").iterdir()), [])
        self.app.extensions["instance_lock"].close()
        self.app = create_app(self.root)
        restarted = self.call("rotate", {"angle": 180})
        self.assertIn('filename=EVA00.pdf', restarted.headers["Content-Disposition"])
        self.assertEqual(list((self.root / "runtime").glob("job-*")), [])

    def test_editor_multipart_uses_document_name(self):
        response = self.call("edit_text_pro", {
            "editor_preview": True,
            "changes": [{"action": "add", "page": 1, "bbox": [72, 120, 400, 155],
                         "text": "NUEVO", "size": 12}],
        })
        self.assertEqual(response.status_code, 200, response.get_data()[:300])
        message = BytesParser(policy=policy.default).parsebytes(
            f'Content-Type: {response.content_type}\r\n\r\n'.encode() + response.data
        )
        parts = {part.get_param("name", header="content-disposition"): part
                 for part in message.iter_parts()}
        self.assertEqual(parts["document"].get_filename(), "EVA00.pdf")
        self.assertIn('filename=EVA00.pdf', response.headers["Content-Disposition"])
        with pymupdf.open(stream=parts["document"].get_payload(decode=True), filetype="pdf") as doc:
            self.assertIn("NUEVO", doc[0].get_text())
        self.assertIn("blocks", json.loads(parts["preview"].get_payload(decode=True)))

    def test_old_counter_is_ignored_and_preserved(self):
        database = self.root / "instance" / "export-counter.sqlite3"
        database.write_bytes(b"invalid")
        response = self.call("rotate", {"angle": 90})
        self.assertEqual(response.status_code, 200)
        self.assertIn('filename=EVA00.pdf', response.headers["Content-Disposition"])
        self.assertEqual(database.read_bytes(), b"invalid")
        self.assertEqual(list((self.root / "runtime").glob("job-*")), [])
