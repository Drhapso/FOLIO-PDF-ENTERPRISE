# EVA PDF Enterprise

> Antes llamada **Folio PDF**. Desde el 2026-10-20 la marca visible, el
> ejecutable (`EVA-PDF.exe`) y el instalador usan el nombre EVA PDF Enterprise.
> Se conservan a proposito, para no interrumpir produccion ni el repositorio:
> las carpetas `FOLIO PDF\FOLIO PDF ENTERPRISE`, el repositorio GitHub, la
> tarea programada `Folio-PDF-LAN`, la entrada `Folio` del gestor de servidores,
> los scripts `reiniciar-folio.ps1`, la regla de firewall `Folio-PDF-LAN-<puerto>`
> e identificadores internos (`folio-theme`, `#folio-opening`, `folioProcess`).

## Nombres de exportacion

Todas las descargas de la aplicacion web usan el nombre fijo `EVA00.pdf`,
`EVA00.txt`, etc., conservando la extension del formato exportado.
El editor usa el nombre asignado por el servidor, no el nombre del original.
Los ZIP se descargan como `EVA00.zip`; sus archivos usan `EVA00_01.pdf`,
`EVA00_02.pdf`, etc., con un indice local que comienza en 01 en cada ZIP.
Las carpetas de orden de los lotes se conservan. No se renombran los recursos internos
de DOCX, XLSX, PPTX o EPUB, para no alterar sus formatos.

No se asignan identificadores globales ni se consulta o actualiza el contador
anterior `instance/export-counter.sqlite3`; su archivo existente se conserva
sin modificaciones. El navegador puede agregar `(1)`, `(2)`, etc., cuando ya
existe una descarga con el mismo nombre en el equipo.

## Cola de produccion y limites efectivos (2026-10-20)

El perfil de produccion `config/production_queue.json`, instalado como
`config/site_config.json`, conserva 1024 MiB (1 GiB) por archivo y por envio
conjunto, y 2048 MiB por resultado. No es 1 GiB por cada archivo de un lote.
Hasta 3 MB conjuntos es un rango
recomendado inicial, no una garantia de tiempo. Desde 10 MB, o en OCR,
conversiones y rasterizacion, el trabajo entra en la clase pesada.
La complejidad, las imagenes, las paginas y las fuentes tambien afectan el coste.

- Hasta cinco motores, reducidos automaticamente por CPU, RAM y calibracion.
- Hasta dos trabajos pesados; si solo hay un motor, se permite uno pesado.
  Los pesados no aumentan el presupuesto de RAM de cada proceso.
- Hasta doce solicitudes en espera y 2048 MiB conjuntos de cuerpos en cola.
  El presupuesto agregado de entrada activa es 1026 MiB (incluye multipart).
  Una carga proxima a 1 GiB puede ocupar casi todo ese presupuesto y esperar
  a que otros trabajos liberen capacidad. La cola tiene tambien un limite de
  bytes: doce plazas no garantizan admitir doce archivos grandes.
- Espera maxima de 45 s; motor hasta 120 s despues de la admision.
- FIFO entre trabajos que caben; una tarea ligera puede adelantar una pesada
  bloqueada por su cupo o presupuesto. No se promete un tiempo estimado exacto.
- Cola llena: HTTP 429; espera agotada o fallo de limpieza: HTTP 503.
  No se reintentan automaticamente trabajos, para evitar ejecuciones duplicadas.
- El aviso emergente muestra envio, posicion de llegada, procesamiento y entrega;
  permite cancelar solo mientras el trabajo esta en cola.
  No cerrar ni recargar la pestaña: una desconexion no garantiza cancelar el motor.

Los cuerpos HTTP pueden permanecer en archivos transitorios del servidor mientras
esperan. No se escriben documentos en SQLite. Los archivos de trabajo se crean
solo tras la admision y se limpian tambien tras errores; el transporte y los
resultados grandes conservan su limpieza al cerrar. La cola no sobrevive un
reinicio: el cliente recibira un error y debera volver a seleccionar su archivo.
Los limites de cola no incluyen descargas en curso ni todos los buffers de red;
mantener espacio libre en `runtime`. Waitress reserva hilos para estado/avisos
y limita conexiones, pero esto no equivale a aislamiento frente a cualquier
saturacion de red o de otros servicios.

Prueba LAN del prototipo: doce clientes desde un solo equipo, dos rondas por
documento, 72 solicitudes medidas, todas completadas sin HTTP 429/500.
Medianas de carga, procesamiento y descarga: 0,654 s para 1 pagina,
6,472 s para 50 paginas (2,86 MB) y 23,698 s para 200 paginas (11,44 MB).
Se observaron como maximo cinco trabajos activos y dos pesados.
Son documentos sinteticos y mediciones orientativas; no certifican el rendimiento
de OCR, Office ni archivos de 1 GiB. Las cuotas superiores son protecciones,
no tamaños recomendados para edicion interactiva.

El perfil reducido de prueba (64/128 MB, cola de 256 MB) no se instala en
produccion. Se mantienen hasta 200 archivos en herramientas masivas y la
cantidad exigida por cada herramienta en las demas. No se certifica completar
1 GiB en 120 s. No se aumentaron CPU, hilos de motores ni memoria por motor.
La cola usa un proceso servidor; no iniciar varias instancias compartiendo
`runtime`. Se reservan hilos HTTP para consultas de estado y cancelacion.

## Directorio activo y servidor principal

- Desarrollo: `D:\PROYECTOS IA INDEPENDIENTES\FOLIO PDF\FOLIO PDF ENTERPRISE`.
- Servidor principal: `G:\PROYECTOS IA INDEPENDIENTES\FOLIO PDF\FOLIO PDF ENTERPRISE`.
- Acceso LAN: `http://172.23.174.11:8090`.
- La entrada `Folio` del gestor `servidores-proyectos.json` y la tarea
  `Folio-PDF-LAN` deben apuntar a la carpeta Enterprise. Mantener el puerto 8090
  y las entradas de los demas servicios sin cambios.
- Los recursos y motores se resuelven desde esta carpeta; no iniciar la copia
  anterior al mismo tiempo en el puerto de produccion.

### Vista de edicion en memoria

La opcion `editor_live_preview: true` del perfil de produccion permite generar la vista posterior al guardado usando
el documento abierto, sin reabrir el PDF de salida. Solo se solicita al entrar
al editor desde Edicion multiple (`multi=1`). Por defecto base esta desactivada;
el perfil de produccion la activa. `FOLIO_TEST_LIVE_PREVIEW` permite sustituir
ese valor en instancias de prueba.
El guardado completo, la compresion, el aislamiento y la limpieza de temporales
se conservan. No retiene documentos entre peticiones ni implementa un motor
local en el navegador. Se validaron equivalencia de vista, ediciones sucesivas,
eliminacion real y limpieza; no garantiza una mejora para todos los PDF.

### Editor Acrobat unico

**Editar PDF**, **Anotar PDF** y **Censurar PDF**, incluidos sus accesos desde
Edicion multiple, abren el mismo editor `/editor`. El PDF se transfiere antes
de navegar y el resultado guardado sigue disponible para otras modificaciones.
El panel permite resaltar, dibujar rectangulos, agregar notas y censurar zonas,
con arrastre o coordenadas de teclado. Las zonas pendientes se pueden quitar;
la censura requiere confirmacion al guardar.

El texto existente se reemplaza eliminando primero su contenido PDF, sin
rectangulos blancos y conservando imagenes y trazos del fondo. Las anotaciones
siguen siendo anotaciones PDF; la censura elimina el contenido de su zona y
retira metadatos y adjuntos. Revisar siempre el resultado: no es un saneamiento
forense de todo el documento.

`edit_text_pro` es el motor comun. La ruta `edit` se conserva como alias:
acepta `changes` o el formato anterior `edits`, nunca ambos. Las cajas antiguas
de texto reemplazan los fragmentos nativos contenidos completamente; una
seleccion parcial se rechaza para no borrar texto vecino ni superponerlo.
Una caja sin texto nativo agrega texto nuevo. `modify` y `delete` requieren
`orig_bbox` coincidente con el fragmento inspeccionado. Los dos alias permiten
la misma respuesta multipart con `editor_preview`.

No se reconstruyen parrafos automaticamente; las fuentes se sustituyen por
familias PDF compatibles.
Agregar texto es una accion explicita distinta de reemplazar texto existente.
Marcas de agua, firmas visuales, formularios y operaciones de paginas conservan
sus herramientas especializadas: no son rutas alternativas de reemplazo de texto.

### Escaneos: reconstruccion local conservadora

Al inspeccionar para editar, el motor detecta paginas sin texto visible o con
una imagen de pagina completa y ejecuta OCR local a 200 DPI (`spa+eng` segun
la configuracion). Tambien detecta texto OCR invisible: no se considera que
eliminar esa capa elimine las letras fotografiadas. Se necesitan los modelos
en `models`; si faltan se informa del error, sin simular una edicion correcta.

Las palabras OCR se comprueban sobre un recorte a 216 DPI. Solo se habilitan
zonas pequenas con tinta aislada sobre fondo simple. Se rechazan limites con
tinta, posibles lineas, sellos/graficos, fondos no uniformes y reconstrucciones
con restos detectados. Las cajas bloqueadas tienen contorno ambar y muestran
el motivo al pulsarlas. Estas comprobaciones son heuristicas, no una garantia
de reconocimiento perfecto.

La vista previa usa un recorte reconstruido con inpainting local. Al guardar
se repiten OCR, validacion y reconstruccion desde el PDF original: no se confia
en una mascara enviada por el navegador. Se eliminan los pixeles de la zona
original con redaccion de imagen y se inserta el recorte limpio, antes del texto
nuevo. Solo se cambia la palabra seleccionada; no se convierte toda la pagina
ni se coloca un rectangulo blanco sobre el original. El OCR y las fuentes
compatibles pueden diferir del original: se solicita confirmacion y revision
visual. Agregar texto sigue siendo una accion explicita, no un reemplazo.

El reemplazo global se rechaza en paginas con fragmentos escaneados para exigir
revision individual. La API antigua `edits` tambien pasa por esta validacion.
No es una limpieza forense ni un sustituto completo del motor de Acrobat.

### Tu centro documental. En tu equipo o en tu red. Sin subir archivos a una nube.

**46 accesos a herramientas PDF · Compresion estructural sin perdida · OCR local ·
Expedientes por lote · Edicion de texto · Funcionamiento offline y LAN**

EVA PDF Enterprise es una plataforma web para organizar, comprimir, convertir y editar
documentos desde el navegador. Puede ejecutarse en un solo equipo o centralizar
el procesamiento en un servidor de la red local, sin instalar el editor en cada
puesto de trabajo. No requiere cuentas ni suscripciones a servicios de nube
para procesar documentos.

> **Estado:** aplicacion ejecutable desde codigo fuente, orientada a Windows.
> La receta del proximo instalador offline esta preparada, pero el nuevo
> ejecutable y Setup todavia no se han generado ni certificado.
> EVA PDF Enterprise no pretende sustituir todas las funciones de un editor profesional.

## Lo mas destacado

- **Privacidad por diseno.** El servidor no crea una biblioteca documental:
  los originales y temporales del trabajo se eliminan antes de enviar el
  resultado. Los resultados grandes se entregan mediante archivos transitorios
  que se borran al cerrar la descarga. SQLite guarda configuracion tecnica,
  no documentos ni historial de trabajos.
- **Compresion sin rasterizar.** Optimiza la estructura interna del PDF sin
  bajar la resolucion de las imagenes ni convertir las paginas a JPEG.
  Si el resultado no pesa menos, devuelve el original con un aviso explicito.
- **Expedientes flexibles.** Reune multiples anexos en el orden elegido,
  con portada opcional y titulo configurable. No queda limitado a cinco PDF:
  admite hasta 200 archivos dentro de una cuota conjunta de 1 GB.
- **Paginas sin tope fijo predeterminado.** La capacidad se controla mediante
  memoria, tiempo y concurrencia, no mediante un numero universal de paginas.
  Cada motor o lote dispone de hasta 120 segundos; no se garantiza terminar
  cualquier documento dentro de ese plazo.
- **Calibracion del equipo.** Un test interno con documentos sinteticos mide
  combinacion, renderizado y OCR, y permite ajustar la concurrencia junto con
  la CPU y RAM disponible. Las mediciones son orientativas, no promesas.
- **Texto editable sin parches blancos.** Modifica fragmentos de texto
  horizontal conservando fondos, imagenes y trazos. Usa fuentes compatibles;
  no reconstruye parrafos complejos ni edita texto contenido en imagenes.
- **OCR sin servicios externos.** Reconocimiento en espanol e ingles,
  enderezado opcional hasta 5 grados y limpieza de escaneos. Revisar siempre
  la transcripcion y posibles cambios en sellos o trazos tenues.
- **Conversiones y diagnostico local.** HEIC/HEIF, EPUB, exportaciones desde
  PDF, formularios, comparacion e informes de integridad criptografica de firmas.
  Office a PDF utiliza LibreOffice instalado en el servidor.
- **Interfaz propia.** Temas claro/oscuro, paleta violeta/lima, diseno adaptable
  y apertura animada original con respeto por movimiento reducido.

## Que diferencia a EVA PDF Enterprise

La diferencia principal es **el modelo de despliegue y control del documento**,
no una afirmacion de superioridad sobre todos los editores. Las funciones y
politicas de otros productos varian segun su version y modalidad.

| Aspecto | Enfoque de EVA PDF Enterprise |
| --- | --- |
| Frente a un servicio alojado en la nube | El procesamiento ocurre en el equipo o servidor que administras. No necesita enviar documentos a un proveedor externo. |
| Frente a un editor de escritorio por puesto | Los clientes LAN usan el navegador; los motores y dependencias se mantienen en el servidor. El servidor debe estar encendido y accesible. |
| Conservacion documental | No incorpora cuentas, biblioteca permanente ni historial de documentos. La descarga queda en el equipo del usuario. |
| Control de capacidad | Cuota de entrada conjunta, procesos aislados, calibracion local, corte de tiempo y cola acotada cuando los motores estan ocupados. |
| Lotes | Varias herramientas procesan multiples PDF y entregan ZIP numerados; expediente y union combinan los anexos en un solo PDF. |
| Alcance profesional | Prioriza tareas documentales locales. No ofrece paridad con Acrobat, certificacion PDF/A, firma con custodia de claves ni maquetacion semantica avanzada. |

## Compresion sin perdida: potencia sin sacrificar resolucion

El modo **estructural sin perdida**, predeterminado en la herramienta Comprimir,
utiliza PyMuPDF/MuPDF para reescribir y compactar el PDF:

1. Elimina objetos internos sin referencia y compacta la estructura.
2. Consolida objetos duplicados cuando el motor lo permite (`garbage=4`).
3. Comprime flujos mediante Deflate y utiliza flujos de objetos
   (`deflate=True`, `use_objstms=1`).
4. Compara el peso obtenido con el original y evita entregar un archivo mayor
   como si fuera una mejora.

**No reduce DPI, no recodifica las paginas como JPEG y no convierte el texto
en imagen.** Su fuerza esta en aprovechar redundancia y estructura ineficiente,
especialmente en PDF con objetos duplicados o flujos poco comprimidos.
Una imagen ya comprimida o un PDF optimizado puede ofrecer poco o ningun ahorro.

> **Sin porcentajes inventados:** no existe una reduccion minima garantizada
> ni se ha certificado una ventaja de compresion frente a otros productos.
> "Sin perdida" describe la optimizacion estructural, no que el archivo conserve
> exactamente sus bytes ni que sus firmas digitales sigan siendo validas.
> Revisar siempre documentos firmados, formularios e interactividad.

Tambien existe un modo **visual con perdida**, separado y explicito:
rasteriza las paginas y utiliza JPEG. Puede reducir mas algunos escaneos,
pero elimina texto seleccionable, formularios, enlaces y capas; no debe
confundirse con la compresion estructural ni usarse si esos elementos importan.
EVA PDF Enterprise no utiliza JBIG2 con perdida ni sustitucion de simbolos.

## Local, LAN y offline: tres conceptos compatibles

| Modalidad | Donde se procesa | Como se accede |
| --- | --- | --- |
| Local | En el mismo equipo que ejecuta EVA PDF Enterprise | Navegador en `http://127.0.0.1:8090`. |
| LAN | En un servidor propio de la red | Navegadores de los equipos autorizados, mediante la direccion del servidor. |
| Offline | En cualquiera de las modalidades anteriores, sin salida a Internet | Dependencias, recursos web y modelos OCR previamente instalados. En LAN sigue siendo necesaria la conexion a la red local. |

**Offline no significa sin servidor:** el proceso de EVA PDF Enterprise debe estar activo.
Los clientes no necesitan Python, LibreOffice ni modelos OCR; esos componentes
residen en el equipo servidor. Para trabajar en un unico PC, ese PC cumple
ambas funciones. Una LAN puede funcionar sin conexion a Internet.

El procesamiento no usa APIs externas, CDN, fuentes remotas ni telemetria propia.
La preparacion inicial requiere obtener dependencias y modelos; despues pueden
trasladarse mediante medios offline conforme a la politica de TI. LibreOffice
es un requisito adicional para Office a PDF y no se incluye en la receta actual
del instalador. La comprobacion offline de firmas no certifica confianza,
revocacion ni validez legal.

### Limites y seguridad que conviene conocer

- **Entrada:** 1 GB conjunto por envio. Herramientas masivas: hasta 200 archivos;
  las demas conservan la cantidad que exige cada operacion.
- **Motor:** maximo 120 segundos por trabajo o lote completo, excluyendo carga
  y descarga. Si no termina, se cancela y limpia; no se entrega un PDF parcial.
- **Recursos:** hasta 5 trabajos simultaneos y 4 GB por trabajo como techos,
  reducidos al arrancar segun el equipo y su memoria disponible.
- **Salida:** hasta 2 GB. No hay tope fijo de paginas por defecto, pero siguen
  aplicando cuotas de peso, tiempo, pixeles y memoria.
- **Red:** usar HTTPS para proteger documentos y claves en LAN; HTTP no cifra
  el trafico. EVA PDF Enterprise no configura firewall ni certificados automaticamente.
- **Almacenamiento:** borrado logico, no forense. Tras un corte electrico,
  los temporales se purgan al siguiente arranque. La politica de EVA PDF Enterprise no borra
  las descargas del usuario ni copias que creen proxies o sistemas externos.
- **Disponibilidad:** escritorio, camara e impresion estan marcados en
  construccion. Consultar mas abajo las capacidades pendientes.

---

## Manual tecnico y operacion

La portada muestra una presentacion original de EVA PDF Enterprise a pantalla completa, sin
marco, sobre la pagina principal desenfocada con `backdrop-filter`.
Incluye relieve de papel plegado, profundidad, bruma, haces de luz y estelas
de particulas, sin sonido ni recursos
externos, durante 4.5 segundos como maximo. No reproduce paisajes, coronas de
estrellas, tipografias ni musica de estudios cinematograficos. No tiene boton de
omitir; conserva Escape para accesibilidad y cierre automatico.
Se reproduce cada vez que se entra a la portada o se
recarga la pagina, sin depender del almacenamiento local. Con movimiento
reducido se omite. No se guardan documentos ni datos personales para ello.

Plataforma web independiente en Windows, sin cuentas ni historial de trabajos.
El servidor procesa documentos localmente; los clientes solo necesitan navegador.
No conecta, copia ni modifica las bases de FALCON o Help Desk.

## Documentacion y proxima release offline

- [Proceso completo y decisiones](docs/HISTORIAL_IMPLEMENTACION.md).
- [Receta de ejecutable, instalador offline y publicacion](docs/DISTRIBUCION_OFFLINE.md).
- [Configuracion y operacion LAN](docs/CONFIGURACION_PROYECTO_BLANCO.md).
- [Cambios por build](CHANGELOG.md).

### Instalador offline 3.1.0 (Windows 10/11 x64)

Generado `dist/EVA-PDF-Enterprise-Offline-3.1.0-win-x64.zip` (120 MB, SHA256 en el
`.sha256.txt` adjunto): EVA-PDF.exe autocontenido con CPython 3.13, todas las
librerias, VC++ runtime y modelos OCR; no requiere Python ni Internet.
Descomprimir y ejecutar `INSTALAR.bat` (sin administrador): instala en
`%LOCALAPPDATA%\EVA-PDF-Enterprise`, verifica integridad y crea accesos "EVA PDF Enterprise"
(local) y "EVA PDF Enterprise (compartir en LAN)". Complementos opcionales
(LibreOffice para Office a PDF, firewall LAN, WIA) en
`COMPLEMENTOS_ADICIONALES.txt` dentro del ZIP. Receta, regeneracion y
validacion en [DISTRIBUCION_OFFLINE](docs/DISTRIBUCION_OFFLINE.md).
Binarios sin firma; revisar licencias (PyMuPDF AGPL) antes de distribuir
fuera de la entidad.

## Inicio desde codigo fuente

Requisitos: Python 3.13, Windows 10/11 o Server y un navegador moderno.

```powershell
# Desde la carpeta clonada del repositorio:
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\install-ocr.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\run-lan.ps1 -LocalOnly
```

Abrir `http://127.0.0.1:8090`. Para la LAN omitir `-LocalOnly`.
El puerto predeterminado es 8090, independiente de los otros proyectos.
El lanzador no detiene procesos ni modifica tareas, firewall o servicios.

LibreOffice debe estar instalado para convertir Office a PDF. Se detecta en
Program Files o PATH; tambien se puede configurar su ejecutable explicitamente.
Los demas motores se instalan con `requirements.txt`. OCR utiliza Tesseract
integrado en PyMuPDF y modelos `spa` y `eng`, sin ejecutable Tesseract adicional.
Solo la instalacion de dependencias/modelos necesita Internet; el procesamiento
no utiliza APIs externas, CDN, fuentes remotas ni telemetria propia.

## Paleta visual

La interfaz utiliza negro `#000000`, violeta `#6259AA`, purpura `#5A2666`,
lima `#A4DB59` y amarillo `#F9BB2C`, con tonos derivados para fondos y bordes.
Las acciones principales son purpuras en modo claro y lima en modo oscuro.
`static/palette.css` centraliza los colores de portada, dialogos y editor;
el editor recupera la preferencia de tema elegida en la portada.
Los colores del PDF, el papel, las firmas y las muestras de formato no cambian.
El violeta delimita selecciones sobre el papel en ambos temas para mantener
contraste. Las combinaciones se probaron primero en un HTML independiente.

## Herramientas

La version ampliada presenta **46 accesos**. Algunos reutilizan el mismo motor:
por ejemplo Anotar/Censurar usan el editor, y Extraer/Eliminar usan seleccion
de paginas. No se cuenta como disponible ninguna capacidad futura.

La pestaña **Edición múltiple** abre una sesión local para un solo PDF y muestra
en una barra lateral las acciones compatibles. Cada resultado PDF sustituye al
documento activo para la siguiente acción; el archivo y los cambios intermedios
permanecen en la pestaña del navegador, no en el servidor. Descarga el último
resultado antes de cerrar la sesión. Las herramientas que producen informes o
archivos distintos de PDF, y las que requieren un segundo documento, siguen
disponibles fuera de esta sesión.

### Guardado de texto en LAN

El editor solicita en una sola operación el PDF editado y la vista de la página
actual. El servidor genera ambos dentro del mismo proceso aislado y los entrega
como respuesta multipart binaria: el navegador no vuelve a subir el resultado
para actualizar la vista. El endpoint conserva su respuesta PDF habitual cuando
no se solicita `editor_preview: true`.

Las bibliotecas de Word, Excel y PowerPoint se cargan solo al usar esas
conversiones. La extracción de bloques del editor omite los datos de imágenes;
estas se conservan en el PDF y en el renderizado de fondo. Se mantienen las
cuotas, el aislamiento por trabajo y la eliminación de temporales. No se mantiene
una copia del documento en el servidor entre solicitudes.

| Herramienta | Alcance |
| --- | --- |
| Unir | Varios PDF en el orden de la lista; botones para mover archivos. |
| Dividir | Un PDF por pagina o grupos como `1-3;4-6;7`, entregados en ZIP. |
| Organizar | Seleccion y orden, por ejemplo `3,1,5-4`; omite las otras paginas. |
| Rotar | 90, 180 o 270 grados sobre paginas seleccionadas. |
| Comprimir | Estructural sin perdida o rasterizacion JPEG con perdida. Si no reduce el peso devuelve el original con aviso explicito. |
| OCR | Rasteriza y agrega texto buscable en espanol/ingles. Enderezado opcional hasta 5 grados y limpieza en blanco y negro; no corrige giros de 90/180 grados. La limpieza puede perder sellos o trazos tenues. |
| Office a PDF | DOCX, XLSX, PPTX, ODT, ODS y ODP con LibreOffice local. Rechaza vinculos externos, macros y objetos incrustados detectados. No admite formatos binarios antiguos. |
| PDF a Word | Texto editable con fuente, tamano, color, negrita y cursiva; tablas detectadas con anchos, combinaciones y rellenos simples; texto y tablas en su posicion original (marcos y tablas flotantes) sobre un fondo sin el texto reconstruido que conserva logos, firmas, marcas y bordes. Misma paginacion; disposicion fija sin reflujo. |
| PDF a Excel | Tablas editables con combinaciones, estilos por celda, rellenos simples, anchos y alturas; conserva tambien texto fuera de tablas. Hoja Original por pagina con referencia visual completa. Neutraliza formulas procedentes del PDF; no inventa formulas ni tipos numericos. |
| PDF a PowerPoint | Texto horizontal y tablas como objetos editables sobre fondo raster sin el texto reconstruido. Conserva imagenes, trazos y texto girado en el fondo; escala y centra paginas de distinto tamano. |
| Imagenes a PDF | PNG, JPEG, TIFF de un fotograma, WebP, BMP y HEIC/HEIF de un fotograma. |
| PDF a imagenes | PNG por pagina dentro de un ZIP. |
| Extraer texto | TXT UTF-8; si no hay texto solicita ejecutar OCR. |
| Editar PDF | Edicion de fragmentos de texto horizontal en una pestana independiente, sin mascaras blancas. La vista previa usa el fondo real del PDF y el guardado retira solo texto, conservando imagenes y trazos. Mantiene la linea base al reemplazar un fragmento. Si el texto no cabe, exige ajustar el cuadro o el tamano. Las fuentes se sustituyen por Helvetica/Times/Courier compatibles; no es reconstruccion de parrafos como Acrobat ni edicion del texto dibujado dentro de imagenes. |
| Marca de agua | Texto superpuesto en paginas seleccionadas. |
| Proteger | Clave de apertura AES-256; minimo 8 caracteres, maximo 40 bytes UTF-8. |
| Desbloquear | Retira cifrado con la clave conocida. No rompe ni recupera claves. |

### Fidelidad de conversion a Office

El modulo `office_export` reconstruye el contenido con las bibliotecas locales
existentes, sin servicios externos ni nuevas dependencias. Los archivos siguen
descargandose como `EVA00` con su extension y los lotes mantienen el orden.

Las tablas se detectan geometricamente: bordes, combinaciones, rellenos y estilos
se aproximan; las tablas sin lineas o de estructura compleja pueden no detectarse.
En Excel se usa el estilo del primer fragmento de cada celda y se conserva el
contenido como texto, no como formulas ejecutables. Las hojas Original permiten
consultar imagenes, graficos y cualquier contenido no representable en celdas.
Word coloca cada linea en un marco anclado a la pagina segun su linea base y
las tablas como tablas flotantes, sobre un fondo raster de la pagina sin el
texto reconstruido; conserva la paginacion y ajusta el espaciado por palabra.
Textos nuevos largos no reacomodan el resto de la pagina. Para detectar tablas
solo se usan trazos rectos: curvas y diagonales de firmas o marcas de agua no
crean filas ni columnas. Fuentes sin metricas conocidas pueden desplazarse.
PowerPoint conserva graficos e imagenes en el fondo, no como objetos editables.

Las paginas escaneadas, sin texto visible o con rotacion de pagina se conservan
como imagen y se informa en el resultado; no se promete editabilidad de esas
paginas. Un OCR previo puede recuperar texto, pero no reconstruye por si solo
el formato ni garantiza su exactitud. Fuentes PDF no instaladas pueden sustituirse
al abrir Office. No se reconstruyen formulas matematicas, SmartArt, macros,
enlaces ni formularios como objetos equivalentes. Revisar siempre el resultado;
no equivale a la conversion propietaria de Acrobat ni garantiza identidad visual.

### Herramientas ampliadas

| Herramienta | Alcance y limites |
| --- | --- |
| Extraer / eliminar paginas | Accesos independientes; eliminar exige una seleccion explicita y no permite quitar todas. |
| Numeracion | Formato `X / Y`, inicio configurable, arriba/abajo y tamano. Quitar primero la rotacion. |
| Extraer imagenes | Imagenes incrustadas unicas en ZIP; reconstruye mascara alfa cuando existe. No extrae vectores ni recompone todos los fragmentos de una pagina. |
| Recortar | Caja dibujada sobre vista previa o porcentajes de la pagina visible. **No elimina el contenido oculto** ni sustituye una redaccion. |
| Cambiar tamano | A4, carta y oficio/legal con ajuste proporcional. |
| Varias paginas por hoja | 2 o 4 paginas por hoja; contenido visual vectorial, sin interactividad. |
| Superponer PDF | Documento primero, plantilla despues; plantilla de una pagina o igual cantidad de paginas. Fondo o primer plano. |
| Comparar | ZIP con informe PDF, diferencias de texto y mapas de diferencias a 96 DPI. Negro: sin diferencia visual. No es comparacion semantica ni validacion de firmas. |
| Firma visual / imagen | PDF primero, PNG/JPEG despues. Firma dibujada en canvas o imagen cargada; caja porcentual. **No firma digital con certificado.** |
| Anotar | Resaltados rectangulares, rectangulos y notas mediante cajas por raton/tactil o teclado. No seleccion semantica de palabras ni dibujo libre de anotaciones. |
| Censurar | Acceso al editor con redaccion seleccionada por defecto; conserva los limites de revision integral ya documentados. |
| Eliminar metadatos | Borra Info y XMP del documento. No sanea adjuntos, comentarios o datos del contenido. |
| Escala de grises / rasterizar | Reconstruye paginas con imagenes; pierde texto seleccionable, enlaces, formularios y estructura accesible. |
| Aplanar | Integra apariencia de anotaciones y widgets con MuPDF; no requiere rasterizar. Revisar resultado. |
| Reparar | Recuperacion estructural con qpdf/pikepdf y comprobacion de sintaxis. Si persisten inconsistencias, falla. No recupera informacion perdida. |
| Optimizar para web | Linealizacion verificada con qpdf, no simple compresion. Puede aumentar el peso. |
| Detectar blancos | Informe JSON de candidatas, excluyendo paginas con texto, anotaciones o campos. Heuristica conservadora; revisar sellos y firmas tenues. |
| Eliminar blancos revisados | Seleccion explicita tras revisar el informe; vuelve a comprobar las paginas y rechaza las no candidatas. Nunca elimina todas. |
| Consultar formulario | Informe JSON con nombres, tipos y valores de campos AcroForm; contiene potencialmente datos sensibles. |
| Rellenar formulario | JSON `{"nombre_del_campo":"valor"}`. Texto, casillas y listas compatibles; sin XFA, radio, JavaScript o firmas. Rechaza campos inexistentes, solo lectura y valores no validos. |
| Armar expediente | Multiples anexos PDF en el orden elegido, con portada opcional mediante la casilla "Incluir pagina inicial (portada)", marcada por defecto. Al desmarcarla se omite la portada y se deshabilita su titulo. Sin el limite de 5 archivos: cuota conjunta de 1 GB y tope tecnico de 200 archivos. Sin tope fijo de paginas; sujeto al presupuesto de memoria y tiempo. |
| PDF a imagenes ampliado | PNG, JPG y TIFF individual por pagina, en ZIP. No TIFF multipagina. |
| PDF a SVG | SVG por pagina en ZIP con textos como trazados, sin interactividad. |
| HTML local a PDF | Solo texto de HTML UTF-8 hasta 2 MB; ignora CSS, imagenes y scripts. No descarga URLs ni conserva diseno. |
| HEIC a JPEG | Foto HEIC/HEIF de un fotograma. Aplica orientacion y fondo blanco a transparencias; JPEG con perdida, sin HDR ni metadatos originales. |
| EPUB a PDF | EPUB sin DRM, refluido a A4 con MuPDF. Verificar tipografia, imagenes y saltos. Limite de paginas y de peso descomprimido; sin interactividad ni descargas remotas. |
| PDF a EPUB de texto | EPUB 3 con indice y una seccion por pagina. Solo texto extraible; sin reconstruir diseno, tablas ni imagenes. Admite lotes con ZIP; usar OCR antes para escaneos. |
| Comprobar firmas offline | JSON con integridad de bytes firmados, comprobacion criptografica, cobertura y cambios. No evalua identidad, cadena de confianza, revocacion ni validez legal. No admite PDF cifrados ni crea firmas. |

Las transformaciones de tamano, N-up y exportacion SVG no conservan formularios,
anotaciones y enlaces interactivos: aplanarlos antes si se necesita su apariencia.
La reparacion/linealizacion puede retirar cifrado al entregar una nueva copia;
usar Proteger PDF despues si corresponde. Cualquier modificacion puede invalidar
firmas existentes.

## Funciones de escritorio y captura

La seccion de escritorio esta cerrada en la interfaz con el aviso
**Funcion en Construccion**. Los accesos al complemento, camara y captura
estan deshabilitados mientras se completa su desarrollo. El panel ambar
es un indicador de desarrollo, no una alarma del sistema. Las herramientas
PDF permanecen disponibles. La ruta de descarga del complemento existente
se conserva para compatibilidad; no se anuncia como lista desde la portada.

El complemento existente `desktop\EVA-Desktop.ps1` esta preparado para ejecutarlo
en **cada equipo cliente**, no en el servidor para controlar equipos remotos:

```powershell
powershell -NoProfile -STA -File .\EVA-Desktop.ps1
```

Revisar el script con TI. No necesita administrador, no modifica ExecutionPolicy,
no registra servicio/protocolo/tarea, no instala controladores ni abre un listener.
Si una politica institucional impide ejecutar scripts, TI debe aprobarlo; no
sortear la restriccion.

- Escanear: dialogo WIA nativo, guarda una imagen PNG en la ruta elegida por el
  usuario. Luego se importa manualmente a Imagenes a PDF. No automatiza lotes,
  TWAIN ni controladores de red; requiere escaner y controlador WIA compatibles.
- Imprimir: seleccion de PDF local y confirmacion expresa; envia la solicitud
  `Print` a la aplicacion PDF asociada. No garantiza impresion fisica. Si no hay
  asociacion, abrir PDF y usar Ctrl+P. Para elegir impresora/opciones usar Ctrl+P.
- Impresoras: abre la configuracion nativa de Windows; no cambia valores.
- Impresora virtual: usar **Microsoft Print to PDF** si ya esta habilitada.
  EVA PDF Enterprise no instala ni administra controladores o colas remotas.
- Diagnostico sin captura/impresion: `-Action Diagnose` devuelve estado WIA,
  servicio de impresion y existencia de Microsoft Print to PDF.
- Los escaneos elegidos y las colas de impresion estan fuera del borrado del
  servidor: son documentos locales intencionales y estado administrado por Windows.

La web agrega camara y captura de pantalla con permiso explicito. En HTTP LAN
los navegadores normalmente las bloquean: usar HTTPS con certificado confiable.
Loopback puede permitirlas por ser contexto seguro. No se toma una foto hasta
pulsar Capturar; la camara se cierra al terminar/cerrar/ocultar la pagina.
La captura de pantalla usa el selector del navegador y detiene la transmision
al obtener una imagen. Ambas generan una imagen local para Imagenes a PDF.
Sin dispositivos/permisos adecuados se muestra el error, no una captura ficticia.

### Capacidades pendientes, no anunciadas como operativas

- PDF/A certificado: requiere definir perfil de archivo, motor de conversion
  y validador como veraPDF. No se sustituye por una etiqueta en los metadatos.
- Creacion de firma digital y verificacion de confianza/revocacion: pyHanko
  ya comprueba integridad offline, pero faltan certificados, politica de claves
  y, segun el caso, TSA/OCSP/CRL. La firma visual no cumple ese papel.
- Fax: necesita infraestructura o proveedor, y politica de retencion.
- Capturar URLs arbitrarias: no habilitado, para evitar que el servidor consulte
  recursos internos/externos sin una politica de acceso expresa.
- OCR con correccion automatica de orientacion a 90/180 grados y restauracion
  de escaneos deteriorados: no implementados. El enderezado acotado y la limpieza
  opcional ya estan disponibles.
- Lector/impresora virtual PDF24, gestores remotos y perfiles del producto:
  componentes de escritorio de terceros; no se redistribuyen ni imitan instaladores.

Modificar un PDF puede invalidar firmas digitales y afectar formularios,
marcadores o interactividad. La compresion visual y OCR reconstruyen paginas:
no conservan estructura accesible, formularios, enlaces ni firmas.
No se implementan ClearScan, XFA, certificacion PDF/A/PDF/X, preflight certificado,
edicion semantica avanzada ni los motores propietarios descritos en el TXT.
No se utiliza JBIG2 con perdida ni sustitucion de simbolos.

## Privacidad y base de datos

- SQLite central en `instance\platform.sqlite3`: solo configuracion tecnica,
  sin documentos, nombres originales, contrasenas, usuarios o historial.
- Patron tomado de ambos proyectos: Flask, Waitress, SQLite local al servidor,
  conexiones cortas, timeout de bloqueo y WAL. SQLite no se comparte por SMB
  ni abre un puerto a los clientes.
- Las cargas se escriben en archivos anonimos dentro de `runtime\spool`
  (Waitress y Werkzeug), abiertos con borrado al cerrar; asi un archivo de
  1 GB no ocupa RAM. La carpeta se purga en cada arranque.
- Cada trabajo se procesa en un subproceso y directorio aleatorio exclusivo
  dentro de `runtime`. Se sustituyen los nombres originales por nombres genericos.
- Perfil de LibreOffice, archivos intermedios y contrasenas temporales viven
  en el mismo espacio. Se eliminan en exito, error o timeout, **antes de responder**.
- Resultados de hasta 64 MB se responden desde RAM (`X-PDF-Cleanup: complete`).
  Resultados mayores se mueven a `runtime\outgoing`, el espacio del trabajo se
  elimina antes de responder y la copia de entrega se borra al terminar o
  cancelarse la descarga (`X-PDF-Cleanup: on-delivery`). En el navegador el
  resultado vive en un Blob de la pestana hasta cerrar la herramienta/pagina.
  No hay URL permanente ni descarga futura.
- Respuestas `no-store`, sin service worker ni almacenamiento de documentos
  en localStorage/IndexedDB. Solo se conserva la preferencia de tema en el navegador.
- Un Job Object de Windows termina el arbol de procesos al cerrar el trabajo,
  incluso si muere el servidor. Timeout y bloqueo de instancia previenen
  procesos de conversion huerfanos e interferencia en temporales. El arbol
  de cada trabajo tiene un limite de memoria comprometida configurable
  (`max_job_memory_mb`, 4096 MB por defecto).
- Si falla el borrado, no se entrega el resultado y se bloquean nuevos trabajos;
  el administrador debe resolver el problema y reiniciar.
- Si Windows se apaga abruptamente pueden quedar temporales hasta el siguiente
  inicio. Se purgan antes de aceptar solicitudes. **No se promete borrado
  fisico forense**: paginacion, SSD, antivirus, copias del SO y equipos cliente
  quedan fuera de esta garantia. Usar cifrado de disco y excluir temporales
  de copias de seguridad segun las politicas de la organizacion.

## Configuracion y despliegue

Copiar `config\site_config.example.json` a `config\site_config.json` y ajustar.
No introducir direcciones institucionales en codigo o archivos publicables.
El JSON es la fuente de configuracion; SQLite guarda su estado tecnico efectivo
en cada arranque, sin ofrecer una consola publica de administracion.

Limites iniciales por **sesion de procesamiento** (cada envio de una
herramienta): maximo **5 archivos** (`max_files`) con un **peso conjunto de
1 GB** (`max_upload_mb`); un archivo puede pesar hasta 1 GB (`max_file_mb`),
pero en ese caso es el unico de la sesion. Las herramientas masivas admiten
**tantos PDF como quepan en 1 GB** (tope tecnico `max_batch_files`, 200):
Armar expediente tambien admite multiples PDF dentro de esta cuota, sin el
limite de 5 archivos. Unir PDF e Imagenes a PDF combinan todo en un PDF;
Dividir, Comprimir, PDF a imagen/texto/Word/Excel/
PowerPoint/SVG/EPUB y Extraer imagenes procesan cada PDF por separado y devuelven un
ZIP numerado en el orden de seleccion (`01-…`, `02/…`), porque los nombres
originales no se conservan. Un error en cualquier archivo cancela el lote
indicando su numero. No hay tope fijo de paginas: `max_pages` y
`max_batch_pages` valen 0 (un administrador puede establecer topes positivos).
Ademas: 2 GB por resultado (`max_output_mb`), 16 millones de pixeles por pagina
renderizada y **120 segundos de motor por trabajo o lote completo** (excluye
carga y descarga). Si se agota el tiempo, se cancela el arbol de procesos y se
eliminan sus temporales; no se entrega un resultado parcial.
Los 5 trabajos (`max_parallel_jobs`) y 4 GB por trabajo (`max_job_memory_mb`)
son techos: al arrancar se reducen segun CPU y RAM disponible, reservando como
minimo la mitad de la RAM total y el 40% de la disponible para otros usos.
En este prototipo hay cola acotada: solo se responde 429 al agotar sus plazas
o presupuesto de entrada; HTTP 503 al agotar la espera. El perfil de produccion
conserva las cuotas de 1 GiB de entrada y 2 GiB de salida.
El navegador rechaza al seleccionar los archivos que exceden la cuota y muestra
el peso usado; el servidor vuelve a validar. En el peor caso el servidor
necesita unos 20 GB de RAM para los motores y espacio libre en disco para
cargas, temporales y resultados (reserve al menos 15 GB en la unidad de `runtime`).

### Calibracion interna de rendimiento

Con EVA PDF Enterprise detenido y desde la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe .\server.py --calibrate
```

El comando requiere el bloqueo exclusivo de la instancia. Un subproceso limitado
en memoria y a 120 s genera documentos sinteticos, mide tres ejecuciones de
combinacion, render JPEG a 150 DPI y OCR a 200 DPI (si existen los modelos) y
elimina entradas y salidas al finalizar. Solo persiste el perfil tecnico en
`instance\performance.json`, sin documentos ni informacion de usuarios.
Si faltan modelos, `ocr_tested` es falso y no se inventa una medicion OCR.
Un fallo de calibracion se informa y no reemplaza el perfil anterior.

Al siguiente arranque, CPU/RAM y latencia medida de render ajustan la concurrencia;
el perfil y los limites efectivos se consultan en `/api/capabilities`.
Las estimaciones de paginas usan el ensayo mas lento y el 50% del tiempo
disponible. **Son orientativas, no topes de paginas ni garantias**:
imagenes, fuentes, OCR, Office y firmas pueden tener costos muy distintos.
Office y firmas no se calibran con estos ensayos. Recalibrar tras cambiar
maquina, motores o carga habitual. No se ejecuta un benchmark por cada carga.
La vista previa vuelve a enviar el archivo por cada pagina; con archivos de
cientos de MB conviene omitirla salvo para editar o recortar.
Una solicitud que supera limites se rechaza; no se encola ni conserva.

`PDF_HOST` y `PDF_PORT`, o `--host` y `--port`, sobrescriben el JSON.
`secure_transport` sirve para documentar la terminacion TLS elegida; no activa
HTTPS automaticamente ni confia en encabezados enviados por el cliente.

Ver [guia LAN y configuracion](docs/CONFIGURACION_PROYECTO_BLANCO.md).

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Las pruebas generan documentos sinteticos y bases temporales, nunca abren bases
operativas. Office y OCR se verifican si sus motores/modelos estan disponibles;
las ausencias se reportan como pruebas omitidas, no como exitos.

### Verificacion local realizada

La ampliacion local supera **67 pruebas en una misma ejecucion**, sin omisiones.
Agrega pruebas sinteticas de HEIC, ida/vuelta EPUB,
limites de descompresion y DRM, mejora medible del enderezado, limpieza binaria,
OCR real y firmas autofirmadas de prueba. Se comprueban firmas intactas,
bytes alterados y revisiones posteriores, bloqueando conexiones externas en la
prueba directa. Esto no sustituye una validacion de confianza institucional.
En navegador se verificaron 46 accesos, las opciones OCR y las cuatro nuevas
herramientas sin errores JavaScript. PDF a EPUB devolvio HTTP 200, archivo
`libro.epub` y confirmacion de limpieza temporal.

Ampliacion Toolbox: **56 pruebas en una misma ejecucion, todas superadas**,
incluidas las 20 pruebas nuevas y las 36 de regresion. Verificados linealizacion
real con qpdf, formularios rellenados/aplanados, comparacion de documentos
iguales/diferentes, transparencia de imagenes extraidas, SVG/JPEG/TIFF, HTML
sin ejecucion ni recursos remotos, limites y limpieza de temporales.
En navegador se abrieron y cerraron los 42 accesos sin errores JavaScript;
se dibujo y aplico una firma y se selecciono/aplico un recorte visual por LAN.
Se comprobo el aviso de falta de contexto seguro para camara por HTTP LAN.

El diagnostico Windows encontro Microsoft Print to PDF y el servicio de
impresion activo, pero ningun escaner WIA conectado. No se realizo escaneo ni
impresion fisica ni se probaron camara/pantalla con HTTPS y dispositivos reales.
No se instalaron controladores, servicios nuevos ni certificados.

El 2026-10-16 se completaron 36 casos distintos: una ejecucion de 33 pruebas
y otra dirigida de nueve comprobaciones tras los ajustes (incluye tres casos
nuevos). Ningun motor se omitio: OCR espanol/ingles y conversion de DOCX,
XLSX y PPTX a PDF se ejecutaron realmente.

Se verificaron redacciones, cifrado y clave incorrecta, compresion con reduccion
medida, conversiones, concurrencia, limites, timeout, bloqueo de instancia y
eliminacion antes de crear la respuesta. Tambien se comprobo carga/descarga
HTTP real con Waitress y PDF resultante legible, sin temporales restantes.
En navegador se revisaron vista previa, edicion, resultado, liberacion del Blob,
temas y adaptacion a 390 y 1440 pixeles sin desbordamiento horizontal.

Se habilito en este servidor una regla de firewall exclusiva para TCP 8090,
limitada a la subred autorizada por el operador y perfiles Dominio/Privado.
Se confirmo la respuesta por la direccion LAN desde el propio servidor.
Los valores concretos de red permanecen en la configuracion del sistema,
no en codigo publicable. Falta comprobar desde otro equipo fisico, instalar
el arranque automatico con cuenta dedicada y preparar HTTPS antes de tratar
documentos sensibles. No se modificaron FALCON ni Help Desk.

## Licencias y limites

El proyecto implementa herramientas propias; no incorpora codigo de Acrobat
ni iLovePDF. PyMuPDF/MuPDF usa licencia AGPL o comercial: revisar obligaciones
de publicacion del codigo para uso por red, o contratar licencia comercial
antes de distribuir un producto cerrado. LibreOffice y los modelos Tesseract
tienen sus propias licencias. La instalacion descarga modelos oficiales de
`tesseract-ocr/tessdata_fast`, revision fijada en el script (Apache-2.0).
La ampliacion utiliza pikepdf (MPL-2.0) y su motor qpdf; revisar sus avisos
y obligaciones de distribucion junto con los de las otras dependencias.
OCR avanzado utiliza OpenCV/NumPy; HEIC utiliza pillow-heif/libheif y sus codecs;
la comprobacion de firmas utiliza pyHanko y cryptography. Revisar tambien
licencias y posibles requisitos de patentes de los codecs antes de distribuir.

Esta aplicacion no es una caja de aislamiento de seguridad del sistema operativo.
Desplegar con una cuenta dedicada **sin privilegios administrativos**, sin acceso
a otras bases o carpetas sensibles; mantener motores actualizados y restringir
salida de red del procesador en el entorno de produccion. No ejecutar como SYSTEM.
Para documentos no confiables se recomienda una maquina/VM dedicada.

## Recuperacion operativa

Durante el envio, la espera, el procesamiento y la descarga, el aviso inferior
derecho muestra el recurso `loadinggif.mp4` junto al estado. La animacion se
reproduce sin sonido, en bucle y con bordes difuminados; se detiene y libera al
finalizar o cancelar. Respeta la preferencia de movimiento reducido. El recurso
publicado se sirve desde `static/loadinggif.mp4`; si se reemplaza el original,
actualizar tambien esta copia. Un fallo del video no interrumpe el procesamiento.

Los tres servicios (EVA PDF Enterprise, HelpDesk y Falcon) disponen de eventos rotativos,
scripts de reinicio manual y supervisor con reintentos limitados ante fallos de
memoria, limpieza y E/S. Consulte [RECUPERACION_SERVICIOS.md](RECUPERACION_SERVICIOS.md)
para los comandos, ubicaciones de logs, limites y advertencias de interrupcion.
Los limites de carga y la cola EVA PDF Enterprise se conservan sin cambios.

La limpieza de un trabajo espera hasta 3,1 segundos adicionales cuando Windows
informa un bloqueo transitorio de archivo (codigos 32/33/145). Si el bloqueo no
desaparece, se mantiene el cierre de admision y la recuperacion controlada; no se
ignoran errores de permisos ni se dejan temporales deliberadamente. Los eventos
de fallo incluyen operacion, clase y codigos del sistema, sin rutas de documentos.
El limite de 1 GiB es de admision: no garantiza que cualquier PDF de ese tamano
termine dentro de los 120 segundos o del presupuesto de memoria del motor.
