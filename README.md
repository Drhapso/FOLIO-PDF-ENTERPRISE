# EVA PDF Enterprise

### Tu centro documental. En tu equipo o en tu red. Sin subir archivos a una nube.

**EVA PDF Enterprise** es una plataforma web local y de red interna (LAN) para organizar, editar, convertir, reconstruir, traducir, auditar y proteger documentos PDF desde el navegador. Todos los motores de procesamiento se ejecutan en el servidor propio (sin cuentas, sin telemetría ni envío de archivos a servicios externos).

> Antes llamada **Folio PDF**. Algunas rutas internas, archivos de configuración y tareas de despliegue conservan ese nombre por compatibilidad operativa.

---

## Características principales

- **Procesamiento 100 % local u offline.** Sin APIs remotas, CDN ni fuentes externas; CSP estricta (`script-src 'self'`).
- **Privacidad por diseño.** No guarda historial ni biblioteca documental: SQLite almacena únicamente la tabla técnica `settings`, y cada carpeta temporal (`runtime/job-*`) se elimina antes de entregar la respuesta (`EVA00.<ext>` o `EVA00.zip`).
- **Más de 60 herramientas en 3 niveles.** Interfaz organizada por complejidad —**Edición básica** (18), **Edición avanzada** (28), **Edición profesional** (15)— más flujo encadenado **Edición múltiple** y tarjetas descriptivas emergentes (*tooltips*).
- **Aislamiento y cuotas controladas.** Subprocesos independientes por trabajo, cola acotada (hasta 5 motores en paralelo y 2 pesados configurables), lotes de hasta 200 archivos dentro de una cuota de 1 GB y calibración local de hardware.
- **Temas claro y oscuro** con diseño adaptable.

---

## Capacidades destacadas

1. **Editor Acrobat unificado (`/editor`) y Co-Piloto local:** reemplaza texto directamente en el flujo PDF (sin parches blancos), añade notas, resaltados y censura real, permite auditoría tipográfica, ecuaciones LaTeX vectoriales, reflujo `Story` XY-Cut, compilación Liquid PDF, etiquetado PDF/UA (WCAG + Web Speech offline) y co-piloto con plan + vista previa aprobada.
2. **PDF Escaneado a Office Editable (estilo Acrobat Pro):** canalización OCR + vectorización (`scan_to_office` y modo automático en PDF ↔ Word / Excel / PowerPoint / PDF) que detecta y reconstruye tablas (con/sin bordes y celdas combinadas), formas geométricas y conectores/flechas de diagramas sin duplicar texto en el fondo.
3. **Traductor Vectorial In-Situ offline (ES ↔ EN):** traducción neuronal 100 % local con **CTranslate2** (`addons/pack-nmt`, pares `en_es` / `es_en`) y respaldo automático OCR Tesseract para escaneos, preservando cajas y geometría del documento.
4. **PDF a Word, Excel y PowerPoint editables:** disposición posicional fiel sobre el fondo gráfico (logos, firmas, sellos y marcas de agua), tipado automático de celdas en `.xlsx` (`Puente Tabular Tipado`) y hojas visuales `Original`.
5. **Estudios especializados:**
   - **Canvas Multidocumento (`/canvas`):** mesa de luz interactiva para fijar páginas, conectar extractos con SHA-256, comparar versiones semánticamente y exportar tableros `.evaboard`.
   - **Pipeline Batch (`/pipeline`):** división por expresiones regulares, enrutamiento condicional en subcarpetas, nombrado contextual y compilación masiva mediante plantillas `.evatpl` / CSV.
   - **Bóveda Forense (`/vault`):** desinfección COS de revisión única (`%%EOF=1`), purga anti-rastreo, auditoría de custodia/corpus local y cripto-contenedores multi-rol `.evacrypt` (PBKDF2 + AES-256-GCM con descifrado en el navegador).
6. **Compresión estructural sin pérdida, OCR enderezado y firmas offline:** comprobación criptográfica local con `pyHanko` (sin OCSP/CRL/TSA externos) y reconocimiento OCR local español/inglés con Tesseract.

---

## Inicio rápido (desde Git)

### Requisitos

- **Sistema:** Windows 10/11 o Windows Server x64.
- **Python:** 3.13 (compatible con entornos virtuales `.venv` de Python 3.13+).
- **Opcionales recomendados:**
  - **LibreOffice** en el servidor (requerido para `Office a PDF`).
  - **Tesseract OCR** y modelos `spa`/`eng` (instalables con `deploy\install-ocr.ps1`).
  - **Modelos NMT offline `ES↔EN`** (`deploy\install-nmt.ps1`) para activar traducción neuronal completa en lugar del glosario básico.

### Instalación y arranque

```powershell
# 1. Clonar el repositorio e ingresar a la carpeta
git clone <URL_DEL_REPOSITORIO>
cd FOLIO-PDF-ENTERPRISE

# 2. Crear entorno virtual e instalar dependencias Python
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Instalar modelos offline de OCR (Tesseract spa/eng) y traductor NMT (ES<->EN)
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\install-ocr.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\install-nmt.ps1

# 4. Iniciar servidor local (o quitar -LocalOnly para exponer en LAN)
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\run-lan.ps1 -LocalOnly
```

Abrir **`http://127.0.0.1:8090`** en el navegador.

---

## Estructura del repositorio y notas para Git

| Ruta | Propósito |
|---|---|
| `server.py`, `pdf_engine.py`, `office_export.py` | Servidor Flask/Waitress, cola de trabajos, motores base PDF y exportación Office |
| `engines/` | Motores modulares V2 (Acrobat-Pro Scan-to-Office, forense, NMT/tipografía, pipelines, bóveda) |
| `templates/`, `static/` | Interfaz HTML/CSS/JS autocontenida (CSP estricta, sin recursos remotos) |
| `deploy/` | Scripts PowerShell de OCR, NMT offline, arranque LAN, firewall y empaquetado PyInstaller |
| `docs/` | [Manual técnico](docs/MANUAL_TECNICO.md), [distribución offline](docs/DISTRIBUCION_OFFLINE.md) y guías |
| `tests/` | Suite automatizada `unittest` (`test_platform.py`, `test_v2_enterprise.py`, `test_scan_office_bridge.py`, etc.) |

### Exclusiones en `.gitignore`

Para mantener el repositorio ágil y sin datos privados ni artefactos binarios pesados, `.gitignore` excluye automáticamente:
- Entornos y cachés: `.venv/`, `.venv-build/`, `__pycache__/`, `.pytest_cache/`, `*.pyc`.
- Modelos descargables pesados: `models/*.traineddata`, `addons/pack-nmt/en_es/`, `addons/pack-nmt/es_en/`, `addons/pack-nmt/*.argosmodel`.
- Estado de ejecución y muestras privadas: `runtime/`, `instance/`, `config/site_config.json`, `MUESTRAS/`, `*.log`.
- Salidas de compilación offline: `build/`, `dist/`, `wheelhouse/`, `deploy/release.local.json`, `*.exe`, `*.msi`, `*.zip`.

Tras clonar en un equipo nuevo, ejecuta `deploy\install-ocr.ps1` y `deploy\install-nmt.ps1` para regenerar los pesos locales en `models\` y `addons\pack-nmt\`.

---

## Pruebas automatizadas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Las pruebas generan únicamente documentos sintéticos y directorios temporales aislados.

---

## Documentación adicional

- [Manual técnico y de operación](docs/MANUAL_TECNICO.md)
- [Distribución e instalador offline](docs/DISTRIBUCION_OFFLINE.md)
- [Historial de cambios](CHANGELOG.md)
- [Registro técnico detallado (`Cambios de antigravity.txt`)](Cambios%20de%20antigravity.txt)

> EVA PDF Enterprise prioriza tareas documentales locales y controladas en red interna; revisa siempre resultados sensibles (censuras, OCR, conversiones y firmas) antes de distribuirlos.
