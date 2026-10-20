# Cambios

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
