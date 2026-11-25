from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from server import CLIENT_BUILD, create_app
from tests.test_platform import sample_pdf


class AdminFeatureFlagsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_user = os.environ.get("EVA_ADMIN_USER")
        self._old_pass = os.environ.get("EVA_ADMIN_PASSWORD")
        os.environ["EVA_ADMIN_USER"] = "admin"
        os.environ["EVA_ADMIN_PASSWORD"] = "EvaAdminTest*2026"
        self.temporary = tempfile.TemporaryDirectory(prefix="eva-flags-test-")
        self.root = Path(self.temporary.name)
        self.app = create_app(self.root)
        self.app.testing = True
        self.client = self.app.test_client()
        self.headers = {"Origin": "http://localhost", "X-PDF-Client": CLIENT_BUILD}
        self.sample = sample_pdf(1)

    def tearDown(self) -> None:
        self.app.extensions["instance_lock"].close()
        self.temporary.cleanup()
        if self._old_user is None:
            os.environ.pop("EVA_ADMIN_USER", None)
        else:
            os.environ["EVA_ADMIN_USER"] = self._old_user
        if self._old_pass is None:
            os.environ.pop("EVA_ADMIN_PASSWORD", None)
        else:
            os.environ["EVA_ADMIN_PASSWORD"] = self._old_pass

    def _login(self, password: str = "EvaAdminTest*2026"):
        return self.client.post(
            "/api/admin/login",
            headers=self.headers,
            json={"username": "admin", "password": password},
        )

    def test_admin_auth_and_feature_toggle_lifecycle(self) -> None:
        # 1. Sin sesión admin: acceso denegado
        self.assertEqual(self.client.get("/api/admin/session").get_json()["is_admin"], False)
        self.assertEqual(self.client.get("/api/admin/features").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/admin/features",
                headers=self.headers,
                json={"tool_id": "compress", "state": "maintenance"},
            ).status_code,
            401,
        )

        # 2. Contraseña incorrecta -> 401
        bad = self._login("clave-mala")
        self.assertEqual(bad.status_code, 401)

        # 3. Inicio de sesión válido
        ok = self._login()
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.get_json()["is_admin"])
        self.assertTrue(self.client.get("/api/admin/session").get_json()["is_admin"])

        # 4. Inhabilitar una función en Mantenimiento y otra en Desarrollo
        r1 = self.client.post(
            "/api/admin/features",
            headers=self.headers,
            json={
                "updates": {
                    "compress": {"state": "maintenance", "note": "Ajustando compresión de imágenes"},
                    "translate_layout": {"state": "development", "note": "Integración NMT pendiente"},
                    "v2_pipeline_studio": {"state": "development"},
                    "eva_copilot": {"state": "maintenance"},
                }
            },
        )
        self.assertEqual(r1.status_code, 200)
        flags = r1.get_json()["feature_flags"]
        self.assertEqual(flags["compress"]["state"], "maintenance")
        self.assertEqual(flags["compress"]["label"], "Función en Mantenimiento")
        self.assertEqual(flags["translate_layout"]["state"], "development")
        self.assertEqual(flags["translate_layout"]["label"], "Función en desarrollo")

        # 5. /api/capabilities publica los estados bloqueados para el frontend
        caps_resp = self.client.get("/api/capabilities").get_json()
        self.assertEqual(caps_resp["feature_flags"]["compress"]["state"], "maintenance")
        self.assertEqual(caps_resp["feature_flags"]["translate_layout"]["state"], "development")

        # 6. El backend bloquea directamente la ejecución de la herramienta deshabilitada (HTTP 503)
        proc_blocked = self.client.post(
            "/api/process/compress",
            headers=self.headers,
            data={"options": "{}", "files": [(io.BytesIO(self.sample), "doc.pdf")]},
        )
        self.assertEqual(proc_blocked.status_code, 503)
        self.assertIn("Función en Mantenimiento", proc_blocked.get_json()["error"])

        # 7. Rutas de estudio dedicadas (/pipeline) y Copiloto IA también respetan el bloqueo
        pipe_resp = self.client.get("/pipeline")
        self.assertEqual(pipe_resp.status_code, 302)
        self.assertIn("/?blocked=v2_pipeline_studio", pipe_resp.headers["Location"])

        cop_resp = self.client.post(
            "/api/copilot/chat",
            headers=self.headers,
            json={"prompt": "Hola"},
        )
        self.assertEqual(cop_resp.status_code, 503)
        self.assertIn("Función en Mantenimiento", cop_resp.get_json()["error"])

        # 8. Invariante de privacidad: platform.sqlite3 conserva únicamente la tabla 'settings'
        with closing(sqlite3.connect(self.root / "instance" / "platform.sqlite3")) as conn:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            self.assertEqual(tables, [("settings",)])

        # 9. Rehabilitar una función individualmente y luego reset_all
        r2 = self.client.post(
            "/api/admin/features",
            headers=self.headers,
            json={"tool_id": "compress", "state": "enabled"},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertNotIn("compress", r2.get_json()["feature_flags"])

        r3 = self.client.post(
            "/api/admin/features",
            headers=self.headers,
            json={"reset_all": True},
        )
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.get_json()["feature_flags"], {})

        # 10. Cerrar sesión
        out = self.client.post("/api/admin/logout", headers=self.headers)
        self.assertEqual(out.status_code, 200)
        self.assertEqual(self.client.get("/api/admin/session").get_json()["is_admin"], False)

    def test_index_renders_admin_ui_and_preserves_topbar_contract(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('id="eva-admin-btn"', html)
        self.assertIn('id="eva-admin-login-dialog"', html)
        self.assertIn('id="eva-admin-dialog"', html)
        self.assertIn('id="fcCenterLink"', html)


if __name__ == "__main__":
    unittest.main()
