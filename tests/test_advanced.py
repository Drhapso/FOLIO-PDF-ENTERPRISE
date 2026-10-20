from __future__ import annotations

import io
import json
import socket
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np
import pymupdf as pdf
from PIL import Image, ImageDraw
from pillow_heif import register_heif_opener

import test_platform as base
from advanced_tools import preprocess_scan, signature_report
from pdf_engine import ProcessingError, capabilities
from server import ROOT
from test_platform import sample_pdf


class AdvancedTests(unittest.TestCase):
    setUpClass = classmethod(base.PlatformTests.setUpClass.__func__)
    tearDownClass = classmethod(base.PlatformTests.tearDownClass.__func__)
    tearDown = base.PlatformTests.tearDown
    call = base.PlatformTests.call

    def test_heic_jpeg_and_pdf(self):
        register_heif_opener()
        buffer = io.BytesIO()
        Image.new("RGB", (160, 90), (210, 40, 20)).save(buffer, "HEIF", quality=90)
        source = buffer.getvalue()
        result = self.call("heic_to_jpg", uploads=[(source, "foto.heic")])
        with Image.open(io.BytesIO(result.data)) as image:
            self.assertEqual((image.format, image.size), ("JPEG", (160, 90)))
            self.assertLess(abs(image.getpixel((70, 40))[0] - 210), 15)
        result = self.call("images_to_pdf", uploads=[(source, "foto.heif"), (source, "foto.heic")])
        with pdf.open(stream=result.data, filetype="pdf") as doc:
            self.assertEqual(len(doc), 2)
            self.assertEqual(doc[0].rect.width, 120)
        self.call("heic_to_jpg", uploads=[(b"bad", "foto.heic")], expected=422)
        self.call("heic_to_jpg", expected=422)

    def test_epub_roundtrip_and_batch(self):
        result = self.call("pdf_to_epub")
        with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
            self.assertEqual(archive.infolist()[0].filename, "mimetype")
            self.assertEqual(archive.infolist()[0].compress_type, zipfile.ZIP_STORED)
            self.assertIn("SECRETO", archive.read("OEBPS/pagina-001.xhtml").decode())
            self.assertIn('properties="nav"', archive.read("OEBPS/content.opf").decode())
        converted = self.call("epub_to_pdf", uploads=[(result.data, "libro.epub")])
        with pdf.open(stream=converted.data, filetype="pdf") as doc:
            self.assertIn("SECRETO", "".join(page.get_text() for page in doc))
            self.assertAlmostEqual(doc[0].rect.width, 595)
        batch = self.call("pdf_to_epub", uploads=[(self.original, "a.pdf"), (sample_pdf(1), "b.pdf")])
        with zipfile.ZipFile(io.BytesIO(batch.data)) as archive:
            self.assertEqual(archive.namelist(), ["01-libro.epub", "02-libro.epub"])

    def test_epub_validation(self):
        self.call("epub_to_pdf", uploads=[(b"not a zip", "bad.epub")], expected=422)
        for kind in ("missing", "drm", "expanded"):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                if kind != "missing":
                    archive.writestr("mimetype", "application/epub+zip")
                if kind == "drm":
                    archive.writestr("META-INF/encryption.xml", "<encryption/>")
                elif kind == "expanded":
                    archive.writestr("large", b"x" * 2 * 1024 * 1024)
            original = self.config["max_upload_mb"]
            try:
                if kind == "expanded":
                    self.config["max_upload_mb"] = 1
                self.call("epub_to_pdf", uploads=[(buffer.getvalue(), "bad.epub")],
                          expected=413 if kind == "expanded" else 422)
            finally:
                self.config["max_upload_mb"] = original
        with pdf.open() as doc:
            doc.new_page()
            blank = doc.tobytes()
        self.call("pdf_to_epub", uploads=[(blank, "blank.pdf")], expected=422)

    def test_preprocessing_deskews_and_cleans(self):
        image = Image.new("RGB", (800, 1000), "white")
        draw = ImageDraw.Draw(image)
        for y in range(70, 950, 45):
            draw.text((70, y), "DOCUMENTO DE PRUEBA 1234567890", fill="black", font_size=24)
        image = image.rotate(3, fillcolor="white")
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        pix = pdf.Pixmap(buffer.getvalue())
        self.assertIs(preprocess_scan(pix, "none", 150, 16000000), pix)
        deskewed = preprocess_scan(pix, "deskew", 150, 16000000)

        def score(p):
            rgb = np.frombuffer(p.samples, dtype=np.uint8).reshape(p.height, p.width, 3)
            return np.var((rgb[:, :, 0] < 128).sum(axis=1))

        self.assertGreater(score(deskewed), score(pix) * 1.5)
        cleaned = preprocess_scan(pix, "clean", 150, 16000000)
        self.assertEqual(set(cleaned.samples), {0, 255})
        self.assertEqual(cleaned.xres, 150)
        with self.assertRaises(ProcessingError):
            preprocess_scan(pix, "invalid", 150, 16000000)
        with self.assertRaises(ProcessingError):
            preprocess_scan(pix, "deskew", 150, 800000)

    def test_ocr_preprocessing(self):
        if not capabilities(self.config, ROOT)["ocr"]:
            self.skipTest("Modelos OCR no instalados")
        for mode in ("deskew", "clean"):
            with self.subTest(mode=mode):
                result = self.call("ocr", {"dpi": "150", "preprocess": mode})
                with pdf.open(stream=result.data, filetype="pdf") as doc:
                    self.assertIn("PRUEBA", "".join(page.get_text() for page in doc).upper())
                self.assertIn("Enderezado", result.headers["X-PDF-Notice"])
        self.call("ocr", {"preprocess": ["bad"]}, expected=422)
        self.call("ocr", {"preprocess": "bad"}, expected=422)

    def test_unsigned_signature_report(self):
        result = self.call("verify_signatures")
        report = json.loads(result.data)
        self.assertEqual(report["firmas"], [])
        self.assertEqual(report["modo"], "offline")
        encrypted = self.call("protect", {"new_password": "clave123"})
        self.call("verify_signatures", {"password": "clave123"},
                  uploads=[(encrypted.data, "signed.pdf")], expected=422)

    def test_signed_pdf_integrity_offline(self):
        from asn1crypto import keys, x509 as asn1_x509
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign import signers
        from pyhanko_certvalidator.registry import SimpleCertificateStore

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EVA PDF prueba local")])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
                .not_valid_after(now + timedelta(days=1))
                .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
                .sign(key, hashes.SHA256()))
        signer = signers.SimpleSigner(
            signing_cert=asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER)),
            signing_key=keys.PrivateKeyInfo.load(key.private_bytes(
                serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())),
            cert_registry=SimpleCertificateStore())
        output = io.BytesIO()
        signers.PdfSigner(signers.PdfSignatureMetadata(field_name="Firma"), signer=signer).sign_pdf(
            IncrementalPdfFileWriter(io.BytesIO(self.original)), output=output)
        signed = output.getvalue()
        path = self.root / "signed-test.pdf"
        original_connect = socket.socket.connect

        def local_only(connection, address):
            # asyncio en Windows necesita un par de sockets de loopback.
            self.assertIn(address[0], ("127.0.0.1", "::1"), "No se permite red externa")
            return original_connect(connection, address)

        try:
            path.write_bytes(signed)
            with patch.object(socket.socket, "connect", new=local_only):
                report = signature_report(path)
            signature = report["firmas"][0]
            self.assertTrue(signature["firma_criptografica_correcta"])
            self.assertTrue(signature["integridad_bytes_firmados"])
            self.assertEqual(signature["cobertura"], "ENTIRE_FILE")
            self.assertEqual(signature["confianza_identidad"], "NO_EVALUADA")
            result = self.call("verify_signatures", uploads=[(signed, "signed.pdf")])
            self.assertTrue(json.loads(result.data)["firmas"][0]["firma_criptografica_correcta"])
            with pdf.open(path) as doc:
                doc.set_metadata({"title": "CAMBIO POSTERIOR"})
                doc.saveIncr()
            with patch.object(socket.socket, "connect", new=local_only):
                revised = signature_report(path)
            self.assertTrue(revised["firmas"][0]["integridad_bytes_firmados"])
            self.assertNotEqual(revised["firmas"][0]["cobertura"], "ENTIRE_FILE")
            # Un cambio en bytes firmados debe detectarse aunque el PDF siga siendo legible.
            altered = signed.replace(b"MediaBox", b"MediaBax", 1)
            self.assertNotEqual(altered, signed)
            path.write_bytes(altered)
            with patch.object(socket.socket, "connect", new=local_only):
                damaged = signature_report(path)
            self.assertFalse(damaged["firmas"][0]["integridad_bytes_firmados"])
        finally:
            path.unlink(missing_ok=True)
