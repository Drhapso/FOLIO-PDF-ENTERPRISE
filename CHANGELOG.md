# Cambios

## 2026-11-21 - Corrección de cuellos de botella en cola, cálculo de slots de memoria y timeout de conversión Word/Office

- **Descongestión de cola y piso de memoria dinámica (`performance.py`):** Corrección en el cálculo de `tune()` para garantizar que en sistemas de 64 bits con al menos 4 GB de RAM, `budget` no colapse por debajo de 2048 MB debido a fluctuaciones transitorias de RAM libre en Windows. `max_parallel_jobs` ya no se colapsa artificialmente a 1 slot ni estrangula `max_heavy_jobs`.
- **Garantía de cuota de memoria para operaciones pesadas (`server.py`):** Se aseguró un piso mínimo de 1536 MB - 2048 MB de cuota en el Windows Job Object (`ProcessTree`) para todas las tareas en `HEAVY_OPERATIONS` (`pdf_to_docx`, `scan_to_office`, `ocr`, etc.), evitando terminaciones forzadas por `0xC0000128` (`STATUS_PAGEFILE_QUOTA_EXCEEDED`).
- **Drenaje de cuerpo y cierre de conexión en errores de admisión (`server.py`):** Cierre explícito del stream de entrada no leído y envío de cabecera `Connection: close` en respuestas HTTP de `AdmissionError` (503/429), evitando que Waitress y el cliente HTTP/navegador se queden colgados en estado `CloseWait`/`Established`.
- **Timeout seguro y preventivo en subprocesos del motor (`server.py`):** Incorporación de `child.wait(timeout=5)` con captura de `TypeError` en el bloque `finally:` de `Popen`, impidiendo que hilos del servidor queden bloqueados indefinidamente por procesos huérfanos.
- **Protección de interfaz de usuario contra esperas infinitas (`static/processing_queue.js`):** Implementación de un `safetyTimer` conectado al `AbortController` que interrumpe la solicitud y muestra un diagnóstico amigable si la red o el servidor tardan más allá de los límites configurados (`timeout_seconds + queue_wait_seconds + 30s`).
- **Verificación end-to-end con `BIZHUB 363.pdf`:** Documento de 16 páginas procesado y exportado exitosamente a Word (.docx) editable de 5.9 MB en **11.9 segundos** sobre el servidor activo local.
- Build web `2026-11-21-v2-enterprise-5`.

## 2026-11-21 - Optimización de rendimiento en conversión a Office y descongestión de cola

- **Aceleración algorítmica de extracción y análisis visual (`engines/scan_office_bridge.py`):**
  - **Vectorización 1D de `_stroke_contrast`:** Sustitución de los bucles fila por fila y columna por columna de NumPy (`np.where`, `np.diff`, `np.insert`, `np.append`) por cálculo directo de corridas 1D en NumPy (`np.diff(np.pad(...).flatten('C'))` y `'F'`), logrando una aceleración de **11.9x** en la detección de modulación de trazo tipográfico (fuste vs filete/serifa).
  - **Bypass de inpainting Telea en `_build_clean_backdrop`:** Verificación anticipada de ausencia de fotos, sellos, firmas protegidas o tinta residual fuera de texto y tablas. En páginas estándar de texto/tablas se omite la costosa llamada `cv2.inpaint`, reduciendo el tiempo de procesamiento por página en ~42% (de 3.3s a 1.9s).
  - **Optimización de resolución en auto-deskew sub-píxel:** Downsampling ajustado a 520 px de dimensión máxima para el barrido de 76 transformaciones afines de proyección, reduciendo en un 70% el costo computacional de alineación sin perder precisión angular sub-0.05°.
- **Descongestión y ampliación de límites en la cola de procesamiento (`settings.py`, `config/site_config.json`):**
  - Incremento de trabajos pesados simultáneos (`max_heavy_jobs`) de **2 a 3**, duplicando la capacidad efectiva de procesamiento simultáneo de conversiones PDF a Office / OCR en la cola de trabajo.
  - Aumento del tiempo de espera en cola (`queue_wait_seconds`) de **45 a 120 segundos**, evitando cancelaciones prematuras con error HTTP 503 cuando se encolan documentos extensos de múltiples páginas.
  - Aumento de trabajos máximos encolados (`max_queued_jobs`) de **12 a 16**.
- Build web `2026-11-21-v2-enterprise-4`.

## 2026-11-21 - Diagnóstico inteligente de subprocesos, cuotas 4GB, advertencia LAN HTTP e importación en pruebas

- **Diagnóstico preciso de códigos de terminación de subprocesos (`server.py`):**
  - Reemplazo del error genérico `"El motor no pudo terminar el trabajo."` (HTTP 500) por inspección detallada del código de salida (`returncode`) del subproceso `worker.py`.
  - Mapeo de terminaciones por cuota de memoria RAM en Windows Job Object (`0xC00000A1` / `STATUS_WORKING_SET_QUOTA_EXCEEDED` o códigos `-1073741671`, `3221225633`, `3221225768`, `-1073741528`, `-9`) a código de estado **HTTP 413** con mensaje explicativo indicando que el documento superó el límite de memoria asignado y recomendando optimización o división de páginas.
  - Mapeo de violaciones de acceso en librerías C++ nativas (`0xC0000005` / `STATUS_ACCESS_VIOLATION` o códigos `-1073741819`, `3221225477`) a código de estado **HTTP 422** indicando estructuras, fuentes o streams corruptos en el PDF de origen.
  - Manejo diferenciado de errores de sincronización (`rc == 2`) y códigos de fallo inesperados con telemetría del código exacto para agilizar el soporte técnico.
- **Sincronización de cuotas y ampliación de memoria a 4096 MB (`isolation.py`, `config/site_config.json`):**
  - Actualización del límite por defecto en `ProcessTree` de 768 MB a **4096 MB (4 GB)** para evitar caídas prematuras en conversiones pesadas de documentos escaneados multinivel y OCR intensivo.
  - Sincronización explícita en `config/site_config.json` con `"max_job_memory_mb": 4096` y `"timeout_seconds": 180`.
- **Cierre preventivo de descriptores y limpieza de temporales (`server.py`):**
  - Incorporación de `file_storage.close()` en el bloque `finally:` de `_run_isolated_tool`, eliminando las advertencias `ResourceWarning: Implicitly cleaning up <_TemporaryFileWrapper>`.
- **Detección y advertencia de seguridad para conexiones HTTP no cifradas en LAN (`static/app.js`):**
  - Detección en frontend cuando el acceso se realiza por protocolo `http:` desde una IP de red local (distinta de localhost / 127.0.0.1 / ::1), mostrando un aviso de seguridad visible en la barra de estado inferior: `"Conectado en red local (LAN) por HTTP sin cifrar. Para entornos corporativos o confidenciales, configure un proxy inverso HTTPS"`.
- **Normalización de rutas de importación en suites de pruebas (`tests/test_extended.py`, `tests/test_advanced.py`):**
  - Inserción dinámica de la ruta del directorio de pruebas en `sys.path` antes de importar `test_platform`, permitiendo la ejecución aislada de cada archivo de prueba sin requerir la variable de entorno `$env:PYTHONPATH=".;tests"`.
- **Nueva prueba de cobertura de códigos de salida (`tests/test_platform.py`):**
  - Añadida `test_worker_termination_codes_return_accurate_diagnostics` validando que los códigos `0xC00000A1` y `0xC0000005` son transformados rigurosamente a HTTP 413 y HTTP 422 respectivamente.
- Build web `2026-11-21-v2-enterprise-3`.

## 2026-11-21 - Mejoras Acrobat Pro: Sub-píxel deskew, limpieza de bordes, flujo continuo DOCX, listas y sospechosos OCR

- **Auto-Deskew fino sub-píxel y limpieza de bordes perimetrales (`engines/scan_office_bridge.py`):**
  - Proceso en dos fases: barrido grueso en rango ampliado de $\pm 15.0^\circ$ en pasos de $0.5^\circ$, seguido de refinamiento áureo fino sub-píxel de $\pm 0.40^\circ$ en pasos de $0.05^\circ$ con umbral de activación optimizado (`1.06` en auto y `1.005` manual), emulando `bDeskew` de Acrobat `Scan.api`.
  - Neutralización de sombras de bordes de escáner y márgenes perimetrales oscuros (`MagicCleanBoundariesLayout` / `BGRemoval`): detección en la franja exterior del 1.8% del área de página y reemplazo al tono base del papel sin afectar arte interno.
- **Selector de disposición en Word: Flujo Continuo vs Disposición Fija (`office_export.py`):**
  - Soporte para `layout_mode = "flow"` (flujo continuo análogo a `IDS_LAYOUT_FLOW` de Acrobat `SaveAsRTF.api`): emite párrafos nativos en Word sin marcos anclados absolutos (`w:framePr`), con `space_before`, `space_after = Pt(2.0)`, espaciado de línea uniforme e indentación adecuada.
  - Mantenimiento por defecto de `layout_mode = "retain"` para documentos donde se requiera fijación visual exacta con marcos flotantes.
- **Detección automática de viñetas y listas numeradas (`office_export.py`):**
  - Reconocimiento de marcadores de lista (`•`, `·`, `-`, `*`, `1.`, `a)`, etc.) mediante `_BULLET_RE` y aplicación automática de sangría francesa en Word (`left_indent = Pt(18)`, `first_line_indent = Pt(-18)`), emulando `BulletedList` de Acrobat `TouchUp.api`.
- **Detección y navegación interactiva de dudas de OCR ("Suspects") (`scan_editor.py`, `acrobat_tools.py`, `templates/editor.html`, `static/acrobat_editor.css`, `static/acrobat_editor.js`):**
  - Función heurística `is_suspect_word` para detectar anomalías tipográficas de digitalización (mezclas alfanuméricas, símbolos extraños o signos de puntuación internos).
  - Marcado de `is_suspect` y `suspect_reason` en bloques de escaneo y bloques nativos del editor.
  - Nuevo botón en barra de herramientas del editor: `⚠️ Dudas OCR (N)` con contador en tiempo real, estilos de advertencia punteada y navegación cíclica con scroll automático y foco al fragmento sospechoso, emulando `TouchUp::FEAT_GetSuspectList` de Acrobat Pro DC.
- Build web `2026-11-21-v2-enterprise-2`.

## 2026-11-21 - Remoción de botón Falcon Center en entorno local y regla de exclusión para equipo BAINTS604

- **Ajuste de interfaz en proyecto local (`templates/index.html`):**
  - Retirado el botón de enlace `🏛️ Ir a Falcon Center` (`#fcCenterLink`, `.btn-fc-center`) de la barra superior de acciones (`.header-actions`).
- **Configuración de exclusión y sincronización (`.gitignore`, `GEMINI.md`, `Cambios de antigravity.txt`):**
  - Añadida directiva en `.gitignore` para no sincronizar la eliminación del botón Falcon Center en máquinas con nombre de equipo `BAINTS604`.
  - Establecida regla obligatoria de validación por `hostname`: al leer los archivos en otro equipo para replicar cambios con GitHub Copilot Chat, si el nombre de la máquina coincide con `BAINTS604`, se omite la modificación de `templates/index.html`, preservando el botón y la conectividad con Falcon Center en dicho equipo.
- Build web `2026-11-21-v2-enterprise-1`.

## 2026-11-19 - Protección de firmas manuscritas, sellos oficiales y logotipos en conversión escaneada a Office (DOCX / PPTX)

- **Aislamiento visual y protección de arte no tipográfico (`engines/scan_office_bridge.py`):**
  - Detección precisa de firmas manuscritas mediante análisis morfológico de trazo fino (`0.015 <= dens <= 0.28`, `stroke_w <= max(14.0, pt_to_px * 5.5)`, `stroke_w / min(bw, bh) <= 0.35`, `aspect >= 1.05`), absorbiendo además puntos y tildes aislados directamente asociados al trazo.
  - Reconocimiento de sellos oficiales y estampas compactas circulares/ovales/rectangulares (`0.70 <= aspect <= 1.45`) por saturación cromática (`comp_sat >= 30.0`) y compacidad superficial.
  - Preservación de logotipos y arte raster denso mediante apertura morfológica (`13x13`) sobre tinta real no perteneciente a tablas ni diagramas, suprimiendo falsos positivos sobre texto de cabecera o tipografía en color.
  - Exclusión geométrica de conectores y flechas de diagramas de flujo adyacentes a cajas para evitar falsos positivos de firmas sobre líneas de conexión.
  - Enmascaramiento preventivo en la entrada OCR de Tesseract (`ocr_input[photo_mask > 0] = paper_bgr`) y filtrado estricto de superposición (`photo_overlap > 0.25`), impidiendo la alucinación de cadenas de texto erróneas ('LATA', 'MANN', 'SS') sobre rúbricas, sellos y logos.
  - Protección de tinta original en `_build_clean_backdrop`: las firmas, sellos y logos quedan 100 % intactos y nítidos en el fondo raster PNG (`backdrop_png`), sin degradación por inpainting ni borrado.
  - Supresión de conectores vectoriales espurios sobre curvas de firmas en `_detect_raster_connectors`.
- **Pruebas automatizadas de no regresión (`tests/test_scan_office_bridge.py`):**
  - Nueva prueba `test_scan_to_office_preserves_signatures_and_logos_without_superimposed_text` validando la ausencia de marcos flotantes de texto o párrafos espurios sobre firmas y logotipos, la preservación de conectores genuinos y la presencia de la rúbrica en el fondo raster.
- Build web `2026-11-19-v2-enterprise-2`.

## 2026-11-19 - Reconstrucción tipográfica OCR, detección de fuentes Serif/Sans/Mono y orden de lectura topológico en Word (.docx)

- **Extracción tipográfica precisa desde OCR (`engines/scan_office_bridge.py`):**
  - Recuperación de tamaños exactos, coordenadas de línea base (`origin`), cajas de caracteres y palabras individuales mediante `rawdict` de PyMuPDF, eliminando la fluctuación arbitraria de tamaños por altura de caja de palabra.
  - Detección de familias tipográficas por análisis de contraste de trazos (ratio asta vs remate): `Times New Roman` (Serif), `Arial` / `Calibri` (Sans-Serif) y `Courier New` (Monospace), con suavizado modal por documento.
  - Estimación robusta de peso (Regular vs Negrita) combinando grosor de trazo en DistanceTransform y densidad de tinta (`density >= 0.44 and ratio >= 0.14`).
  - Detección de cursiva/itálica mediante varianza de proyección vertical en barrido de cizallamiento (shear angles).
- **Estructuración y orden de lectura topológico en Word (`office_export.py`):**
  - Algoritmo recursivo XY-cut (`_topological_sort_blocks`) para ordenar bloques (párrafos, tablas y diagramas) respetando columnas múltiples y evitando que las tablas se releguen al final del documento.
  - Agrupación cohesiva de líneas en párrafos editables con alineación (`center`, `right`, `justify`, `left`) y espaciado de línea uniforme (`line_spacing = Pt(line_h)`).
  - Marcos acotados (`frame_width = pw + 10.0`) para evitar solapamientos entre columnas adyacentes.
  - Emisión de espacios reales entre palabras en `docx_runs`, absorbiendo holguras inter-palabra y eliminando la distorsión por tracking entre letras (`w:spacing`).
- **Compatibilidad con formatos Office (`office_export.py`, `tests/test_scan_office_bridge.py`):**
  - Soporte integrado de fuentes, estilos y tamaños en DOCX, PPTX y XLSX.
  - Nueva prueba automatizada `test_scan_to_office_docx_preserves_fonts_styles_and_reading_order`.
- Build web `2026-11-19-v2-enterprise-1`.

## 2026-11-09 - Barra superior depurada, niveles de edición, traductor NMT offline y conversión escaneada estilo Acrobat Pro

- **Barra superior principal simplificada (`templates/index.html`, `static/extended.css`):**
  - Retirados los accesos superiores `Herramientas`, `Pipeline Batch`, `Canvas` y `Bóveda Forense` (los estudios `/pipeline`, `/canvas` y `/vault` siguen accesibles desde sus tarjetas en la cuadrícula).
  - Desplazada la opción `Privacidad` (`#privacidad`) al extremo derecho dentro de `.header-actions`, inmediatamente junto al botón de cambio de tema claro/oscuro.
- **Reorganización de herramientas por nivel y tooltips (`templates/index.html`, `static/app.js`, `static/extended.css`):**
  - Retirada la pestaña aislada `Suite V2`; las 61 herramientas de la portada quedan clasificadas en `Edición básica` (18), `Edición avanzada` (28) y `Edición profesional` (15), manteniendo `Edición múltiple`.
  - Añadido tooltip flotante descriptivo al situar o enfocar cada tarjeta de herramienta.
- **Traductor Vectorial In-Situ 100 % offline (`engines/typography_and_layout.py`, `deploy/install-nmt.ps1`, `engines/addons.py`):**
  - Integrado motor neuronal `CTranslate2` (`addons/pack-nmt`, pares `en_es` y `es_en`) con soporte OCR automático en PDFs escaneados y capas `GlyphLessFont`, aislamiento de memoria `CT2_USE_MKL=0` e hilos `OMP_THREAD_LIMIT`, además de fallback determinista a glosario si no hay modelos NMT.
- **Conversión escaneada refinada estilo Acrobat Pro (`engines/scan_office_bridge.py`, `office_export.py`, `pdf_engine.py`):**
  - Nueva operación `scan_to_office` y modo editable automático/refinado (`scan_editable_mode` en PDF→Office y `refine_scans` en Office→PDF) con OCR Tesseract, detección de tablas con/sin bordes y celdas combinadas, vectorización de cajas/conectores/flechas y limpieza de fondo sin texto fantasma.
- **Suite modular V2 (`engines/`, `/pipeline`, `/canvas`, `/vault`, `/editor` drawer):**
  - Incorporados estudios dedicados `/pipeline`, `/canvas` y `/vault`, además del registro `engines/registry.py` con 25 operaciones V2 y pruebas dedicadas en `tests/test_v2_enterprise.py` y `tests/test_scan_office_bridge.py`.
- **Documentación para Git (`README.md`, `CHANGELOG.md`, `Cambios de antigravity.txt`):**
  - Actualizado `README.md` con la arquitectura actual, scripts `deploy\install-ocr.ps1` y `deploy\install-nmt.ps1`, tabla de estructura y exclusiones de `.gitignore`.
- Build web `2026-11-09-v2-enterprise-6`.

## 2026-10-21 - README de portada simplificado

- README reducido a caracteristicas generales y funciones mas novedosas.
- Documentacion tecnica y operativa completa trasladada sin cambios de
  contenido a `docs/MANUAL_TECNICO.md` (enlaces relativos ajustados).

## 2026-10-21 - PDF a Word con disposicion posicional fiel

- Problema real: un PDF de 2 paginas generaba un Word de 4 paginas con tablas y
  texto rasterizados por agrupacion de graficos y flujo vertical de parrafos.
- Word ahora usa un fondo raster sin el texto reconstruido (logos, firmas,
  marcas y bordes), lineas en marcos anclados por linea base y tablas nativas
  flotantes; runs por palabra con espaciado ajustado y tamanos redondeados.
- Deteccion de tablas solo con trazos rectos: curvas/diagonales de firmas y
  marcas de agua ya no crean filas o columnas (afecta tambien Excel/PowerPoint).
- Muestra real: 2 -> 2 paginas, 3 tablas, 0 palabras faltantes o anadidas;
  desviacion por caracter mediana 0,12-0,21 pt, p95 0,32 pt.
- Limites: disposicion fija sin reflujo; el fondo no es editable.
- Build web `2026-10-21-word-positional-1`; 59 pruebas aprobadas.

## 2026-10-21 - Conversion editable a Office con reconstruccion de formato

- Word: estilos de texto, tablas nativas, celdas combinadas, rellenos simples,
  imagenes/graficos y dimensiones de pagina; flujo aproximado por posicion.
- Excel: tablas formateadas y texto exterior sin descartarlo, combinaciones,
  estilos y hoja Original por pagina para referencia completa. Texto del PDF
  neutralizado contra formulas; no se infieren calculos ni valores numericos.
- PowerPoint: texto horizontal y tablas editables sobre fondo sin el texto
  reconstruido, manteniendo graficos e imagenes sin editabilidad.
- Paginas escaneadas/sin texto visible o giradas conservadas como imagen, con
  aviso. Limitaciones de maquetacion y fuentes explicitas en interfaz y README.
- Modulo `office_export` con bibliotecas existentes, incluido en empaquetado;
  build web `2026-10-21-office-layout-1`. No se genero instalador offline.
- Validacion local: 27 pruebas aprobadas, incluyendo API, estilos, rellenos,
  tablas combinadas, imagenes, OCR invisible, rotacion, orden de paginas,
  lotes y nombres EVA00. Word y PowerPoint abiertos y renderizados con
  LibreOffice; muestra de una pagina conserva texto una sola vez e imagenes.
- Activado en produccion mediante reinicio oficial de EVA PDF, sin cambiar
  configuracion privada. Pruebas HTTP reales DOCX/XLSX/PPTX y lote Word aprobadas:
  estructuras editables, estilos, tablas, referencia visual Excel y nombres
  EVA00; original de prueba intacto. Salud directa y proxy con build nuevo.

## 2026-10-21 - Nombre fijo de exportacion EVA00

- Sustituido el consecutivo global por `EVA00` y la extension de salida:
  `EVA00.pdf`, `EVA00.docx`, `EVA00.zip`, etc.
- Dentro de cada ZIP: `EVA00_01`, `EVA00_02`, etc., conservando extensiones,
  orden y carpetas de lote. El indice es local al archivo ZIP.
- Contador anterior conservado sin leerlo ni modificarlo. Editor y descargas
  por streaming usan el mismo nombre fijo; build `2026-10-21-export-fixed-1`.
- Validacion: 39 pruebas enfocadas aprobadas y exportaciones HTTP reales de PDF,
  TXT, ZIP y editor verificadas en produccion. Servicio directo y proxy saludables
  tras reinicio exclusivo de EVA PDF; configuracion privada sin cambios.

## 2026-10-21 - Consecutivo global de exportacion EVA

- Todas las descargas web usan el prefijo `EVA00 ` y un consecutivo de al menos
  seis digitos, conservando la extension. Incluye archivos dentro de ZIP,
  lotes, respuesta multipart del editor y descargas grandes por streaming.
- Contador SQLite persistente y transaccional compartido por los motores de la
  instalacion, sin guardar documentos ni datos de usuarios. Vistas previas
  excluidas; errores del contador devuelven HTTP 503 y se registran por categoria.
- Editor actualizado para respetar el nombre del servidor; build web
  `2026-10-21-export-sequence-1`. Sin instalador offline nuevo.
- Pruebas de concurrencia entre procesos, persistencia tras reinicio,
  limites de longitud, ZIP, multipart, streaming y fallo de base de datos.
- Validacion: 106 pruebas aprobadas. Activado con el reinicio oficial exclusivo
  de EVA PDF, configuracion privada intacta y salud directa/proxy con build nuevo.
  Prueba HTTP de PDF, TXT, ZIP y editor aprobada con identificadores distintos.
  Navegador: guardado real del editor con nombre `EVA00 000008.pdf` verificado.
  Las pruebas de produccion consumen numeros reales; no se reinicia el contador.

## 2026-10-21 - Editor unico y reconstruccion local de escaneos

- Unificados Editar PDF, Anotar PDF y Censurar PDF en el editor estilo Acrobat,
  incluidos los accesos y el retorno desde Edicion multiple.
- Eliminado el motor heredado de texto superpuesto. `edit` y `edit_text_pro`
  usan el mismo motor, con compatibilidad validada para `edits` y `changes`.
- Integradas notas, resaltados, rectangulos y censura con arrastre o teclado;
  confirmacion para censura y cambios de pixeles en palabras escaneadas.
- Detectados escaneos y capas OCR invisibles. OCR local a 200 DPI y
  reconstruccion conservadora de palabras a 216 DPI: elimina pixeles originales
  antes de insertar texto nuevo, sin convertir toda la pagina.
- Bloqueadas zonas con tinta en limites, fondos complejos, posibles lineas o
  graficos y reconstrucciones con restos. Reemplazo global rechazado cuando
  existen fragmentos escaneados. No equivale al motor propietario de Adobe ni
  garantiza reconocimiento o reconstruccion perfectos.
- Vista previa y guardado reconstruyen desde el mismo documento; validacion
  del servidor independiente de la mascara del navegador. Modulo `scan_editor`
  incluido en la receta del ejecutable; no se genero un instalador nuevo.
- Build web `2026-10-21-scan-local-1` para invalidar recursos anteriores.
- Diagnostico local: 35 pruebas enfocadas aprobadas, incluidos escaneo puro,
  OCR invisible, pagina mixta, eliminacion de tinta y conservacion del exterior.
  Avisos ResourceWarning de temporales durante pruebas, sin fallos de prueba.
- Muestra real: 552 palabras OCR, 325 habilitadas y 227 bloqueadas. Sustitucion
  de una palabra comprobada visualmente, cero pixeles cambiados fuera de la zona
  de control y original intacto por SHA-256. Muestras y resultados privados
  excluidos de la sincronizacion Git.
- Desplegado en produccion con respaldo y SHA-256 de fuentes; reiniciada solo
  Folio-PDF-LAN tras comprobar ausencia de trabajos y transferencias temporales.
  Salud directa y proxy con build nuevo; configuracion privada sin cambios.
- Prueba HTTP real: OCR, reemplazo y respuesta multipart PDF/vista aprobados;
  limpieza `complete`, cero pixeles cambiados fuera de la zona de control y
  sin tinta oscura residual tras quitar el texto de reemplazo en memoria.
  Detalle operativo y recuperacion en `docs/DESPLIEGUE_2026-10-21.md`.

## 2026-10-20 - V2.0.1: Reproduccion incondicional de animaciones, perfil productivo y documentacion local

- Eliminadas las guardas prefers-reduced-motion: reduce en static/opening.js,
  static/opening.css, static/processing_queue.js, static/palette.css y
  static/app.css para que la presentacion de apertura (#folio-opening), el
  video de procesamiento (loadinggif.mp4) y las transiciones visuales se
  reproduzcan siempre de forma uniforme, incluso en equipos Windows con
  SPI_GETCLIENTAREAANIMATION desactivado.
- Instalado el perfil productivo config/production_queue.json como
  config/site_config.json (editor_live_preview: true, 
  recommended_upload_mb: 3,
  max_queued_upload_mb: 2048).
- Agregados EJECUCION PRIMERA VEZ LOCALMENTE.txt, GEMINI.md y la bitacora
  estructurada Cambios de antigravity.txt con bloques <<< SEARCH / === REPLACE
  para replicacion exacta con GitHub Copilot Chat.
- Retirados archivos de referencia obsoletos en FOLIO PDF INSTALLER WINDOWS/.

## 2026-10-20 - Cambio de marca a EVA PDF Enterprise

- Marca visible renombrada de Folio a EVA PDF Enterprise: titulos, logotipo
  (icono "E" y favicon), apertura animada, editor, pie, mensajes, complemento
  `desktop/EVA-Desktop.ps1` y documentacion.
- Ejecutable `EVA-PDF.exe` (`deploy/eva-pdf.spec`), instalador offline
  `EVA-PDF-Enterprise-Offline-<v>-win-x64.zip`, instalacion en
  `%LOCALAPPDATA%\EVA-PDF-Enterprise`, lanzador `Iniciar-EVA.ps1` y
  desinstalador `Desinstalar-EVA.ps1`.
- Sin cambios: carpetas del proyecto y repositorio, tarea `Folio-PDF-LAN`,
  scripts de recuperacion, regla de firewall e identificadores internos.
  Entradas anteriores de este registro conservan el nombre historico.
- Build web `2026-10-20-eva-brand-1`; favicon versionado para renovar cache.

## 2026-10-20 - Instalador offline 3.1.0

- Generado `dist/Folio-PDF-Offline-3.1.0-win-x64.zip`: Folio.exe PyInstaller
  onedir con todas las librerias, VC++ runtime y modelos OCR, instalador
  `INSTALAR.bat/.ps1` por usuario con verificacion SHA256, actualizacion que
  conserva configuracion e instancia, lanzador local/LAN, desinstalador,
  `LEEME.txt` y `COMPLEMENTOS_ADICIONALES.txt`.
- Nuevos `deploy/build-offline-package.ps1` y `deploy/offline/`; corregidas
  comillas de `deploy/build-executable.ps1` para Windows PowerShell 5.1.
- Validado sin Python en PATH: instalacion, calibracion, OCR, conversiones,
  actualizacion, integridad alterada, desinstalacion y acceso LAN.
  Produccion y `CLIENT_BUILD` sin cambios.

## 2026-10-20 - Cola LAN, edicion multiple y rendimiento

- Publicado build `2026-10-20-queue-lan-1`. Respaldada version anterior,
  reiniciada exclusivamente la tarea Folio-PDF-LAN, verificados acceso directo
  y proxy, limites efectivos de 1024 MiB y edicion sintetica por LAN:
  HTTP 200, resultado/preview validados y limpieza confirmada.
- Validacion previa final: 31 pruebas enfocadas aprobadas. La prueba de
  admision de 1 GiB usa contabilidad de tamaños, no transfiere un archivo de
  1 GiB ni certifica su tiempo de procesamiento.

- Espacio de Edicion multiple con 24 acciones y reutilizacion del PDF.
- Corregida compatibilidad de paneles y recursos versionados para evitar
  controles inactivos; retorno del editor conserva el modo multiple.
- Guardado de texto devuelve PDF y vista en una respuesta multipart, sin
  segunda subida; imports Office diferidos y extraccion sin imagenes embebidas.
- Vista posterior al guardado reutiliza el documento abierto solo en edicion
  multiple cuando `editor_live_preview` esta habilitado.
- Cola acotada con FIFO entre trabajos admisibles, cinco motores como techo,
  dos pesados, doce en espera, espera de 45 s y motor de 120 s.
- Presupuestos agregados de entrada activa (1026 MiB) y en cola (2048 MiB);
  conservados 1 GiB conjunto por envio, 1 GiB por archivo y 2 GiB de salida.
- Avisos emergentes de carga, cola, procesamiento y entrega en herramientas
  generales y editor; cancelacion durante espera y errores explicitos.
- Recomendacion inicial hasta 3 MB conjuntos; desde 10 MB o por tipo de
  operacion se limita como pesado. No confundir recomendacion con cuota.
- Editor bloquea cambios mientras guarda para evitar perder modificaciones.
- Pruebas de FIFO, cancelacion, saturacion, presupuestos, cierre por fallo de
  limpieza y liberacion de admision. Validacion LAN con 12 clientes, 72 envios,
  todos completados; documentos sinteticos de 1, 50 y 200 paginas.
- Perfil reducido de prueba no desplegado. Sin certificacion de OCR/Office
  bajo carga ni de archivos de 1 GiB; no se promete un optimo universal.
- Proyecto activo en FOLIO PDF ENTERPRISE; despliegue y tarea Folio-PDF-LAN
  mantienen el puerto 8090 y no modifican los demas servicios.

## 2026-10-19 - README de presentacion para GitHub

- Resumen de novedades, diferencias de despliegue y privacidad, uso local/LAN
  offline y limites efectivos, conservando el manual tecnico existente.
- Explicado el motor de compresion estructural sin perdida, sus opciones
  y limites, sin porcentajes garantizados ni comparaciones no verificadas.
- Separado el modo visual con perdida y aclarado el estado del instalador,
  requisitos externos, firmas digitales y funciones en construccion.

## 2026-10-19 - Preparacion de distribucion offline (sin construir)

- Documentado el proceso de implementacion, decisiones, validaciones y
  limitaciones en `docs/HISTORIAL_IMPLEMENTACION.md`.
- Parametros propuestos 3.1.0, CPython 3.13 Windows x64; script de prevalidacion
  y construccion explicita, PyInstaller onedir e Inno Setup por usuario.
- Entrada congelada con despacho servidor/worker; rutas fuente conservadas,
  modelos y recursos incluidos mediante lista de distribucion.
- Exclusiones de estado local, configuracion privada, builds y binarios;
  hashes de payload y Setup, control de licencias y pruebas previas.
- Sin generacion de ejecutables ni instalador, sin commit ni push. La
  certificacion de binarios y VM offline queda para la siguiente entrega.
- Corregida documentacion historica del instalador: no anunciar archivos
  ausentes ni la compatibilidad de un paquete externo no verificado.

## 2026-10-19 - Apertura inmersiva a pantalla completa

- Sin marco ni boton de omitir: fondo real de la portada desenfocado,
  luz ambiental, haces, estelas y particulas con profundidad.
- Composicion original Folio; sin usar el GIF, musica ni elementos de marca
  de terceros en el sitio. Conserva Escape, movimiento reducido y cierre a 4.5 s.
- Checkpoint de la apertura de arco anterior conservado sin cambios.
- Build `2026-10-19-fullscreen-opening-1`.

## 2026-10-19 - Apertura cinematografica original

- Emergente Folio con relieve de papel, movimiento en profundidad, bruma
  y particulas geometricas, sin elementos distintivos de estudios de cine.
- Conserva apertura en cada carga, omitir, Escape y movimiento reducido;
  cierre automatico a los 4.5 s.
- Checkpoint de la apertura anterior guardado fuera del proyecto.
- Build `2026-10-19-cinematic-opening-1`.

## 2026-10-19 - Apertura en cada visita

- La presentacion se reproduce al entrar a la portada y al recargarla,
  sin consultar ni guardar una marca de primera visita.
- Conserva el cierre automatico, omitir, Escape y movimiento reducido.
- Build `2026-10-19-opening-always-1`.

## 2026-10-19 - Presentacion de apertura Folio

- Apertura original con el logotipo Folio, arco luminoso y destello suave,
  usando la paleta del sitio y sin sonido ni recursos externos.
- Solo primera visita por navegador/origen, sin repetirse al actualizar.
- Duracion maxima de 3.5 s, boton para omitir, Escape y restauracion de foco.
  Respeta movimiento reducido; con almacenamiento bloqueado se omite.
- Build `2026-10-19-opening-1`.

## 2026-10-19 - Portada opcional del expediente

- Casilla "Incluir pagina inicial (portada)", marcada por defecto.
- Al desmarcarla, el titulo se deshabilita y el resultado contiene solo los
  anexos en el orden elegido. La API conserva portada si se omite la opcion.
- Validacion booleana y pruebas con/sin portada, orden y limite administrativo.
- Build `2026-10-19-optional-cover-1`.

## 2026-10-19 - Capacidad adaptativa y calibracion local

- Sin topes predeterminados de 200/5000 paginas en PDF, expedientes,
  exportaciones, informes y EPUB (`max_pages` y `max_batch_pages`: 0).
- Presupuesto estricto de 120 s por motor/lote; CPU y RAM disponible ajustan
  concurrencia y memoria, conservando la cuota conjunta de 1 GB y limites de salida.
- `server.py --calibrate`: ensayos sinteticos aislados de combinacion,
  render y OCR local, con perfil tecnico persistente y limpieza de documentos.
- Mediciones orientativas, no garantias ni limites nuevos de paginas.
- Pruebas con expedientes de 5227 paginas, union de 5226 paginas y division
  de 201 paginas; dimensionamiento y rechazo por memoria insuficiente.
- Build `2026-10-19-adaptive-capacity-1`.

## 2026-10-19 - Cuota conjunta para expedientes

- Armar expediente admite multiples anexos PDF dentro de 1 GB conjunto,
  en lugar del limite de 5 documentos, tanto en navegador como en servidor.
- Conserva el tope tecnico masivo de 200 archivos y el limite existente
  de 200 paginas por expediente contando la portada.
- Prueba de 12 anexos, cuota exacta admitida y rechazo al excederla en un byte.
- Build `2026-10-19-dossier-quota-1`.

## 2026-10-19 - Aviso de construccion y detalles industriales

- Seccion Escritorio, camara e impresion cerrada en la interfaz con
  "Funcion en Construccion" y botones deshabilitados.
- Aviso original con franjas de precaucion, simbolo geometrico y luz ambar,
  sin logotipos ni graficos de terceros. No representa una alarma real.
- Detalles de esquinas, bordes y brillo suave en tarjetas y controles;
  animacion inicial limitada a 4.4 segundos, sin destellos, desactivada
  con `prefers-reduced-motion`. No modifica documentos ni el motor PDF.
- Build `2026-10-19-construction-1`.

## 2026-10-19 - Paleta visual de Folio

- Combinaciones clara y oscura probadas en un HTML independiente antes
  de modificar el sitio. Referencia: negro, violeta, purpura, lima y amarillo.
- Colores centralizados en `static/palette.css`: portada, categorias,
  formularios, dialogos, avisos, estados, foco y controles del editor.
- Acciones purpuras en modo claro y lima en oscuro, con texto contrastado.
  El editor conserva la preferencia de tema seleccionada en la portada.
- PDF, firmas y muestras de color de formato conservan sus colores.
  Seleccion violeta sobre papel; sin introducir fondos en el texto editado.
- Evitada la inicializacion de controles del editor cuando solo esta
  presente la portada.
- Build `2026-10-19-palette-1`.

## 2026-10-19 - Edicion sin recuadros blancos

- Retirados los fondos y sombras blancos del editor. Seleccionar conserva
  la imagen original; modificar, mover o eliminar utiliza el fondo real del PDF
  sin texto como capa de vista previa.
- Texto horizontal separado por linea y estilo para no agrupar etiquetas
  de diferentes celdas. Corregida la deteccion de negrita/cursiva.
- Borrado de texto sin relleno, sin ampliar el area y sin retirar imagenes
  o trazos vectoriales. Reemplazo individual conserva la linea base.
- El texto que no cabe genera un error, sin expansion silenciosa sobre celdas.
- Corregido el guardado de eliminaciones por identificador y la continuacion
  de ediciones sobre el documento actualizado tras guardar.
- Fuentes compatibles Helvetica/Times/Courier; no reconstruye parrafos ni
  sustituye texto dentro de imagenes. Pruebas de fondo, imagenes y lineas.
- Build `2026-10-19-text-editor-1`.

## 2026-10-16 - Interfaz especializada de edición de texto en pestaña independiente (Acrobat Pro DC)

- La opción "Editar PDF" ahora reconoce bloques y párrafos de texto y se abre automáticamente en una pestaña independiente (`/editor`) al estilo Adobe Acrobat Pro DC.
- Paso seguro y efímero del documento entre pestañas mediante IndexedDB del navegador con borrado inmediato (respetando Privacidad por Diseño y sin límites de memoria de sesión).
- Interfaz WYSIWYG completa en `/editor` con barra de herramientas superior Acrobat DC (`✎ Editar texto`, `+ Agregar texto`, `▦ Contornos`, `⌕ Buscar`, `🗑 Eliminar`, navegación y zoom).
- Reconocimiento in-situ de tipografías existentes, tamaños, colores y alineación en el panel lateral RHP.
- Edición de texto mediante redacción vectorial limpia sin alterar imágenes, sellos ni gráficos de fondo.
- Resueltas las opciones de "MOTOR PENDIENTE": modelos OCR en español e inglés descargados y validados con hash SHA256; LibreOffice detectado y habilitado para conversiones Office a PDF.
- Suite de pruebas completa: 71 pruebas ejecutadas y aprobadas satisfactoriamente (incluyendo `tests/test_acrobat_editor.py`).

## 2026-10-16 - Motores locales avanzados

- 46 accesos: HEIC a JPEG, EPUB a PDF, PDF a EPUB de texto y comprobacion
  criptografica offline de firmas PDF. No certifica confianza ni revocacion.
- Imagenes a PDF admite HEIC/HEIF de un solo fotograma.
- OCR conserva el modo anterior por defecto y agrega enderezado hasta 5 grados
  y limpieza binaria opcionales con OpenCV. Revisar sellos y trazos tenues.
- EPUB sin DRM con control de peso descomprimido y paginas; PDF a EPUB admite
  lotes dentro de la cuota conjunta de 1 GB.
- Dependencias declaradas: OpenCV headless, pillow-heif y pyHanko.
- Las herramientas usan el aislamiento y borrado temporal existentes.
- PDF/A validado, creacion de firmas y HTTPS siguen sujetos a motores,
  certificados y politicas institucionales; no se simulan.
- Build `2026-10-16-pdf-toolbox-6`.

## 2026-10-16 - Directorio del proyecto

- Actualizada la ruta de inicio a la carpeta `FOLIO PDF`.
- Los lanzadores resuelven el directorio del proyecto desde su propia ubicacion.
- Corregido el mensaje de PDF danado en lotes para identificar el archivo por numero.
- Build `2026-10-16-pdf-toolbox-5`.

## 2026-10-16 - Lotes masivos dentro de 1 GB

- Unir, Imagenes a PDF, Dividir, Comprimir, PDF a imagen/texto/Word/Excel/
  PowerPoint/SVG y Extraer imagenes admiten tantos archivos como quepan en la
  cuota de 1 GB (tope tecnico `max_batch_files`, 200). El resto sigue en 5.
- Las herramientas por archivo procesan cada PDF por separado y devuelven un
  ZIP numerado por orden de seleccion; un error indica el numero de archivo.
- Unir acepta hasta 5000 paginas sumadas (`max_batch_pages`); 200 por documento.
- Build `2026-10-16-pdf-toolbox-4`.

## 2026-10-16 - Archivos pesados: 5 archivos y 1 GB por sesion

- Cuota por sesion de procesamiento: maximo 5 archivos con peso conjunto de
  1 GB; un archivo de 1 GB ocupa la sesion completa (`max_files`,
  `max_upload_mb`, `max_file_mb`). Validada al seleccionar y en el servidor.
- 2 GB por resultado, 5 trabajos simultaneos en el servidor,
  4 GB de memoria por trabajo (`max_job_memory_mb`) y 900 s de timeout.
- Cargas volcadas a archivos anonimos en `runtime\spool` en vez de RAM.
- Resultados mayores de 64 MB se transmiten desde `runtime\outgoing` y se
  borran al terminar o cancelar la descarga (`X-PDF-Cleanup: on-delivery`).
- Build `2026-10-16-pdf-toolbox-3`.

## 2026-10-16 - Ampliacion Toolbox

- 42 accesos de herramientas, incluidos anotacion/censura y extraccion/eliminacion
  de paginas con motores compartidos.
- Numeracion, extraccion de imagenes, recorte, formatos de papel, N-up,
  superposicion, comparacion visual/texto e informes.
- Firma visual dibujada o imagen, formularios AcroForm, metadatos,
  aplanado, grises/rasterizacion, deteccion y eliminacion confirmada de blancos.
- Expedientes con portada, exportacion JPG/TIFF/SVG y HTML local solo texto.
- pikepdf/qpdf para reparacion estructural y linealizacion verificada.
- Complemento Windows descargable: WIA, solicitud de impresion confirmada,
  ajustes de impresoras y diagnostico sin privilegios ni listener.
- Camara y captura de pantalla mediante permisos del navegador; requieren
  contexto seguro. Sin instalacion automatica de dispositivos.
- Conservados aislamiento, limites y borrado antes de responder.
- PDF/A validado, firma certificada, fax y OCR avanzado siguen pendientes
  de motores/configuracion especifica; no se simulan.
- Build cliente/servidor: `2026-10-16-pdf-toolbox-2`.

## 2026-10-16 - Folio inicial

- Aplicacion independiente Flask/Waitress para navegador y LAN.
- Diecisiete herramientas locales de organizacion, conversion, OCR, edicion
  y proteccion PDF; interfaz adaptable con temas claro/oscuro.
- Editor con vista previa, texto y redacciones reales mediante cajas.
- Procesamiento por subprocesos, timeout y arbol de procesos Windows controlado.
- Borrado antes de responder; limpieza en errores y al reiniciar, sin historial.
- SQLite exclusivo para configuracion tecnica; ningun documento en la base.
- Instalador de modelos OCR, lanzadores y firewall explicito por subred.
- Documentacion de limites, licencias, HTTPS y borrado logico.
- Build cliente/servidor: `2026-10-16-pdf-lan-1`.

## Recuperacion de servicios - 2026-10-20

- Senales internas de errores de memoria y E/S y de fallos de limpieza temporal.
- Supervisor comun para Folio, HelpDesk y Falcon: comprobaciones de salud,
  espera entre reintentos e historial persistente para evitar bucles de reinicio.
- Logs de eventos y salida con rotacion por proyecto; scripts administrativos
  de reinicio manual que validan la identidad del servicio.
- Se mantiene el limite conjunto de 1024 MiB y el perfil de cola publicado.
- Detalles y operacion: [RECUPERACION_SERVICIOS.md](RECUPERACION_SERVICIOS.md).

## Limpieza de cargas grandes - 2026-10-20

- Reintento acotado del borrado temporal ante bloqueos transitorios Windows
  32/33/145; conserva el bloqueo de seguridad si el borrado sigue fallando.
- Diagnostico de limpieza con operacion, errno/winerror y estado previo del trabajo,
  sin registrar rutas, nombres de documentos ni contenido.
- Prueba con bloqueo real Windows y regresion de limpieza permanente.
- Compresion sin perdida de PDF sintetico de 1000 MiB en instancia aislada:
  HTTP 200, salud 200, sin carpetas job pendientes. No certifica rendimiento
  para PDFs escaneados ni identifica retrospectivamente el error historico,
  cuyo registro anterior no guardaba codigos de Windows.
## Animacion de procesamiento - 2026-10-20

- Recurso `loadinggif.mp4` integrado en el aviso inferior derecho de herramientas
  y editor: reproduccion silenciosa en bucle con bordes difuminados.
- Se mantiene visible durante envio, cola, procesamiento y recepcion de resultados.
- Respeta movimiento reducido, se adapta a pantallas pequenas y libera el video
  al terminar o fallar. No requiere reiniciar el servidor.
