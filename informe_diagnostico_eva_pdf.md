# Informe Diagnóstico Integral: EVA PDF Enterprise
**Evaluación Exhaustiva de Funciones de Edición, Configuración, Organización y Seguridad**  
*Fecha de Ejecución:* 2026-11-21 | *Build Evaluado:* `2026-11-21-v2-enterprise-2` | *Entorno:* Windows local (`DESKTOP-FGH0NV5`)

---

## 1. Resumen Ejecutivo y Resultados de Pruebas

Se ejecutó una batería de pruebas de regresión e integración profunda que abarcó **todas las funciones de edición, conversión, manipulación y seguridad** de la plataforma EVA PDF Enterprise.

```
+-------------------------------------------------------------------------------+
|                        RESUMEN DE SUITES EJECUTADAS                           |
+------------------------------+------------+----------+-----------+------------+
| Suite de Pruebas             | Tests      | Estado   | Tiempo    | Cobertura  |
+------------------------------+------------+----------+-----------+------------+
| test_acrobat_editor          | 23 tests   | PASS     | 24.1s     | Edición DC |
| test_extended                | 17 tests   | PASS     | 38.4s     | Edic. Avan |
| test_advanced                | 13 tests   | PASS     | 32.9s     | OCR/Sign   |
| test_office_export           | 13 tests   | PASS     | 18.2s     | Word/XLS   |
| test_scan_office_bridge      | 10 tests   | PASS     | 83.9s     | ScanBridge |
| test_platform                | 22 tests   | PASS     | 16.5s     | Core HTTP  |
| test_cleanup                 | 5 tests    | PASS     | 6.2s      | Privacidad |
| test_workload                | 12 tests   | PASS     | 12.8s     | Colas/Mem  |
+------------------------------+------------+----------+-----------+------------+
| TOTAL EJECUTADO              | 115 tests  | 100% OK  | 233.0s    | Global     |
+------------------------------+------------+----------+-----------+------------+
```

Las 115 pruebas pasaron de forma limpia. Sin embargo, la inspección minuciosa del código fuente, el comportamiento del subproceso `worker.py`, las advertencias del runtime (`ResourceWarning`) y los límites del contenedor `ProcessTree` revelan falencias y riesgos críticos de producción que se detallan a continuación.

---

## 2. Falencias Técnicas (Motor, Rendimiento y Resiliencia)

### 2.1. Opacidad del Fallo Fatal: *"El motor no pudo terminar el trabajo"*
* **Diagnóstico**: Cuando el subproceso `worker.py` muere por terminación de memoria del Job Object (`0xC00000A1`), por violación de acceso en MuPDF/OpenCV (`0xC0000005`) o por rotura de pipe en `sys.stdin`, el proceso no alcanza a ejecutar su bloque `try...except` ni a escribir `result.json`.
* **Impacto**: `server.py` (Línea 356) captura la ausencia de `result.json` y lanza `ProcessingError("El motor no pudo terminar el trabajo.", 500)`. El usuario final no recibe ninguna pista sobre si el fallo fue por memoria insuficiente, página corrupta, timeout o DPI excesivo.
* **Remediación**: Inspeccionar el `child.returncode` antes de emitir el error. Si el código coincide con terminación de Job Object (`3221225633` / `-1073741671`), advertir: *"El documento excedió la cuota de memoria RAM asignada al proceso. Reduzca la resolución DPI o procese menos páginas"*.

### 2.2. Advertencias de Fuga de Recursos en Archivos Temporales (`ResourceWarning`)
* **Diagnóstico**: Durante las pruebas de sustitución y escaneo se capturó la advertencia:
  ```text
  ResourceWarning: unclosed file <_io.FileIO name='...\tmplbly7gar' mode='rb+'>
  ResourceWarning: Implicitly cleaning up <_TemporaryFileWrapper ...>
  ```
* **Impacto**: En Windows, los archivos abiertos que no se cierran explícitamente retienen un bloqueo de archivo exclusivo (*Sharing Violation*, `WinError 32`), obligando al bucle de limpieza en `server.py` a reintentar hasta 5 veces antes de poder borrar la carpeta temporal.
* **Remediación**: Envolver todo uso de `tempfile.NamedTemporaryFile` y descriptores `BytesIO` en bloques `with` contextuales estrictos.

### 2.3. Cuello de Botella en Procesamiento de Escaneos Masivos
* **Diagnóstico**: La suite de `test_scan_office_bridge` consumió **83.9 segundos** para procesar 10 pruebas. Cada página escaneada analizada requiere múltiples pasadas pesadas en OpenCV: umbral adaptativo, dos `warpAffine` para deskew sub-píxel, `distanceTransform`, análisis de contornos y Tesseract OCR.
* **Impacto**: En documentos escaneados de más de 20 páginas, el tiempo acumulado superará fácilmente el timeout de 120 segundos, abortando el trabajo.

---

## 3. Falencias de Configuración

### 3.1. Discrepancia en Cuotas de Memoria de Aislamiento
* **Diagnóstico**: `settings.py` declara `"max_job_memory_mb": 4096`, pero el constructor `ProcessTree(memory_mb: int = 768)` en `isolation.py` utiliza 768 MB como valor predeterminado si no se le pasa parámetro. En `server.py:336`, se lee `config["max_job_memory_mb"]`, pero en `site_config.json` dicha clave no está definida explícitamente, quedando sujeta al valor por defecto.
* **Impacto**: En máquinas con 16 GB o 32 GB de RAM, documentos legítimos con gráficos vectoriales densos son abortados innecesariamente por cuotas desactualizadas.
* **Remediación**: Homogeneizar la cuota en `config/site_config.json` fijando `"max_job_memory_mb": 4096` y documentar el ajuste en la guía de instalación.

### 3.2. Límite Rígido de Renderizado (`max_render_pixels: 16_000_000`)
* **Diagnóstico**: Una página A4 a 300 DPI tiene $2480 \times 3508 = 8,700,000$ píxeles (válida). Sin embargo, un plano técnico A1 o A0 a 200 DPI supera los $25,000,000$ de píxeles, disparando inmediatamente `Image.DecompressionBombError` o rechazando la exportación.
* **Remediación**: Implementar reescalado automático proporcional dinámico cuando la página exceda el límite, en lugar de abortar la exportación completa.

### 3.3. Dependencia Silenciosa de LibreOffice
* **Diagnóstico**: La herramienta `office_to_pdf` depende de LibreOffice (`soffice.com`). Si no está instalado, la función retorna error 503 sin ofrecer conversión alternativa de archivos simples `.txt` o `.docx` estándar.

---

## 4. Falencias de Organización y Arquitectura de Código

### 4.1. Monolito en `scan_office_bridge.py` (2,381 líneas)
* **Diagnóstico**: Un solo archivo concentra detección de tablas raster, aislamiento de firmas/logos, vectorización de diagramas, extracción tipográfica de OCR, suavizado modal y generación de fondo residual.
* **Impacto**: Dificultad para mantener pruebas unitarias aisladas y alto riesgo de regresiones colaterales al modificar la lógica de un elemento (como ocurrió previamente con el blur en firmas).

### 4.2. Acoplamiento de `sys.path` en la Suite de Pruebas
* **Diagnóstico**: Durante la ejecución de la suite completa se detectó que `test_extended.py` y `test_advanced.py` contienen `import test_platform as base` en lugar de `from tests import test_platform as base`.
* **Impacto**: Si la suite se ejecuta con `python -m unittest tests.test_extended` sin definir `$env:PYTHONPATH=".;tests"`, falla con `ModuleNotFoundError`.

---

## 5. Falencias de Seguridad y Privacidad

### 5.1. Matriz de Evaluación de Seguridad

| Vector de Seguridad | Estado en EVA PDF | Nivel de Riesgo | Detalle Técnico |
| :--- | :--- | :--- | :--- |
| **Privacidad de Documentos** | **Excelente** | Ninguno | *Privacy by Design*: los PDFs se procesan en carpetas volátiles `runtime/job-*` y se eliminan físicamente al terminar. No hay base de datos de documentos. |
| **Aislamiento de Procesos** | **Excelente** | Bajo | Los conversores corren en subprocesos aislados asignados a Windows Job Objects (`ProcessTree`) que mueren al cerrar el handle. |
| **Transporte Seguro (TLS/HTTPS)** | **Deficiente** | **ALTO** | Por defecto opera en HTTP plano (`http://127.0.0.1:8090`). En despliegues LAN corporativos, el tráfico y los PDFs viajan sin cifrado si no se activa un proxy inverso. |
| **Protección contra DoS (Bombas Zip/PDF)** | **Aceptable** | Medio | Cuenta con `Image.MAX_IMAGE_PIXELS` y límites de descompresión, pero archivos con miles de capas vectoriales diminutas pueden saturar la CPU de MuPDF. |
| **Validación de Firmas Digitales** | **Básico** | Medio | Realiza comprobación de integridad criptográfica offline con `pyhanko`, pero no verifica listas de revocación CRL ni OCSP en tiempo real. |

En operaciones como `protect` y `unlock`, la contraseña del documento viaja en texto claro dentro del cuerpo de la petición JSON (`{"password": "..."}`). Si el servidor se expone en red local sin HTTPS (`secure_transport: true`), las claves son interceptables mediante análisis de tráfico de red.

---

## 6. Plan de Acción y Remediación Priorizado

### Tabla de Tareas Prioritarias

1. **[P0] Diagnóstico Inteligente de Fallos en Subproceso (`server.py`)**:
   - Detectar si `child.returncode` es negativo o coincide con cuota de Job Object (`0xC00000A1`), devolviendo HTTP 413 o mensaje explicativo en lugar del genérico `"El motor no pudo terminar el trabajo"`.
2. **[P0] Corrección de Importación en Pruebas (`tests/test_extended.py`, `tests/test_advanced.py`)**:
   - Normalizar a `from tests import test_platform as base` o añadir `sys.path.insert(0, str(Path(__file__).parent))` para permitir ejecución directa sin `$env:PYTHONPATH`.
3. **[P1] Sincronización de Configuración (`config/site_config.json`)**:
   - Incluir explícitamente `"max_job_memory_mb": 4096` y `"timeout_seconds": 180` en la plantilla de configuración para evitar cuotas conservadoras no deseadas.
4. **[P1] Reescalado Preventivo en Grandes Formatos (`pdf_engine.py`)**:
   - Si una página excede `max_render_pixels`, aplicar escala adaptativa previa en lugar de lanzar excepción fatal.
5. **[P2] Modularización Arquitectónica de `engines/scan_office_bridge.py`**:
   - Descomponer el archivo de 2,381 líneas en módulos cohesivos:
     - `engines/ocr/typography.py` (análisis de fuentes, serif/sans/mono, pesos).
     - `engines/ocr/deskew.py` (deskew sub-píxel y limpieza perimetral).
     - `engines/raster_tables.py` (detección y enrejado de celdas).
     - `engines/diagram_vectorizer.py` (formas, conectores y flechas).
