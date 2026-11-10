"use strict";
const BUILD = document.querySelector('meta[name="client-build"]').content;
const $ = (id) => document.getElementById(id);
const LEVEL_LABELS = {basic:"Edición básica",advanced:"Edición avanzada",professional:"Edición profesional"};
const tools = [
  {id:"merge",name:"Unir PDF",icon:"⊕",category:"organize",level:"basic",desc:"Varios documentos, un solo PDF. En el orden que tú elijas.",detail:"Combina dos o más PDF en el orden exacto que definas en la lista antes de descargar un único PDF unificado.",io:"Entrada: varios .pdf · Salida: PDF unido",multiple:true},
  {id:"split",name:"Dividir PDF",icon:"⊟",category:"organize",level:"basic",desc:"Separa páginas o crea grupos para descargar en un ZIP.",detail:"Divide un PDF por cada página individual o según rangos personalizados (ej. 1-3;4-6) dentro de un paquete ZIP.",io:"Entrada: .pdf · Salida: archivo .zip"},
  {id:"organize",name:"Organizar páginas",icon:"▤",category:"organize",level:"basic",desc:"Reordena, extrae y elimina páginas con una sola selección.",detail:"Indica el orden o rango exacto (p. ej. 3,1,5-2); las páginas omitidas quedan fuera del documento final.",io:"Entrada: .pdf · Salida: PDF reorganizado"},
  {id:"rotate",name:"Rotar PDF",icon:"↻",category:"organize",level:"basic",desc:"Pon cada página en su posición. Gira 90°, 180° o 270°.",detail:"Endereza páginas escaneadas de lado o boca abajo seleccionando páginas concretas y el ángulo de giro exacto.",io:"Entrada: .pdf · Salida: PDF rotado"},
  {id:"compress",name:"Comprimir PDF",icon:"↙",category:"optimize",level:"basic",desc:"Menos peso, más facilidad para compartir. Elige el nivel.",detail:"Reduce el tamaño en modo estructural sin pérdida (conserva texto/vectores) o en modo visual más ligero.",io:"Entrada: .pdf · Salida: PDF optimizado"},
  {id:"extract_pages",name:"Extraer páginas",icon:"▤",category:"organize",level:"basic",desc:"Descarga únicamente las páginas que necesitas.",detail:"Crea un nuevo PDF conservando únicamente los números y rangos de página que especifiques.",io:"Entrada: .pdf · Salida: PDF extraído"},
  {id:"delete_pages",name:"Eliminar páginas",icon:"−",category:"organize",level:"basic",desc:"Elimina una selección explícita; conserva las demás.",detail:"Quita de forma permanente las páginas indicadas conservando intacto el resto del documento.",io:"Entrada: .pdf · Salida: PDF depurado"},
  {id:"number_pages",name:"Numerar páginas",icon:"123",category:"edit",level:"basic",desc:"Añade números arriba o abajo, con inicio configurable.",detail:"Inserta numeración limpia en encabezado o pie de página eligiendo tamaño tipográfico y número inicial.",io:"Entrada: .pdf · Salida: PDF numerado"},
  {id:"watermark",name:"Marca de agua",icon:"◈",category:"edit",level:"basic",desc:"Añade una marca de texto sobre las páginas que elijas.",detail:"Estampa un rótulo semitransparente (p. ej. CONFIDENCIAL o COPIA) centrado sobre las páginas seleccionadas.",io:"Entrada: .pdf · Salida: PDF marcado"},
  {id:"protect",name:"Proteger PDF",icon:"⌑",category:"edit",level:"basic",desc:"Controla su apertura con una contraseña y cifrado AES-256.",detail:"Cifra el documento completo con clave de apertura AES-256 sin guardar la contraseña en el servidor.",io:"Entrada: .pdf · Salida: PDF cifrado AES-256"},
  {id:"unlock",name:"Desbloquear PDF",icon:"⌕",category:"edit",level:"basic",desc:"Retira la contraseña de un PDF que te pertenece.",detail:"Genera una copia sin clave a partir de un PDF protegido cuya contraseña actual conoces e introduces.",io:"Entrada: .pdf protegido · Salida: PDF sin clave",warning:"Necesitas conocer la contraseña actual. Esta herramienta no recupera ni adivina contraseñas."},
  {id:"images_to_pdf",name:"Imágenes a PDF",icon:"▧",category:"convert",level:"basic",desc:"Reúne fotos e imágenes, incluidas HEIC/HEIF, en un PDF.",detail:"Convierte lotes de fotografías o capturas PNG, JPEG, TIFF, WebP o HEIC en un PDF multipágina manteniendo el orden.",io:"Entrada: imágenes · Salida: PDF multipágina",multiple:true,accept:".png,.jpg,.jpeg,.tif,.tiff,.webp,.bmp,.heic,.heif"},
  {id:"pdf_to_images",name:"PDF a imágenes",icon:"▣",category:"convert",level:"basic",desc:"Exporta tus páginas como imágenes PNG en un ZIP.",detail:"Renderiza las páginas seleccionadas a PNG, JPEG o TIFF con DPI elegible (72-300) dentro de un ZIP.",io:"Entrada: .pdf · Salida: ZIP con imágenes"},
  {id:"extract_text",name:"Extraer texto",icon:"T",category:"convert",level:"basic",desc:"Llévate el contenido de tu PDF a un archivo de texto.",detail:"Extrae el texto nativo u OCR existente manteniendo orden de lectura en un archivo .txt UTF-8.",io:"Entrada: .pdf · Salida: archivo .txt"},
  {id:"extract_images",name:"Extraer imágenes",icon:"▧",category:"convert",level:"basic",desc:"Recupera imágenes incrustadas, no capturas de páginas.",detail:"Extrae directamente las fotos o gráficos raster embebidos dentro del PDF tal como están almacenados.",io:"Entrada: .pdf · Salida: ZIP con imágenes"},
  {id:"heic_to_jpg",name:"HEIC a JPEG",icon:"▧",category:"convert",level:"basic",desc:"Convierte una foto HEIC o HEIF de un fotograma a JPEG.",detail:"Transforma fotos Apple/móviles HEIC/HEIF en archivos JPEG compatibles listos para compartir.",io:"Entrada: .heic/.heif · Salida: imagen .jpg",accept:".heic,.heif",warning:"JPEG con pérdida. No conserva HDR ni metadatos originales; máximo de píxeles igual que las demás imágenes."},
  {id:"remove_metadata",name:"Eliminar metadatos",icon:"ⓘ",category:"edit",level:"basic",desc:"Limpia autor, título y metadatos Info/XMP del documento.",detail:"Borra campos de autoría, software creador, fechas y paquetes XMP antes de distribuir el archivo.",io:"Entrada: .pdf · Salida: PDF sin metadatos",warning:"No elimina adjuntos, comentarios, texto ni datos personales dentro del contenido."},
  {id:"dossier",name:"Armar expediente",icon:"▣",category:"organize",level:"basic",desc:"Reúne anexos PDF en el orden elegido, con portada opcional.",detail:"Une varios anexos PDF generando automáticamente una página de portada inicial titulada para entrega formal.",io:"Entrada: varios .pdf · Salida: expediente PDF",multiple:true},
  {id:"edit",name:"Editor Acrobat · Editar PDF",icon:"✎",category:"edit",level:"advanced",desc:"Reemplaza texto, cambia su formato, anota y censura. Escaneos: reconstrucción local de palabras sobre fondos simples; las zonas complejas se bloquean.",detail:"Abre el editor visual interactivo para editar texto in-situ sin parches blancos, cambiar fuentes/color, anotar y censurar.",io:"Entrada: .pdf · Salida: editor visual + PDF",standaloneTab:true},
  {id:"annotate",name:"Anotar PDF",icon:"✎",category:"edit",level:"advanced",desc:"Resalta zonas, dibuja rectángulos y agrega notas en el editor Acrobat.",detail:"Inicia el lienzo Acrobat enfocado en herramientas de resaltado, recuadros de énfasis y notas adhesivas.",io:"Entrada: .pdf · Salida: PDF anotado",standaloneTab:true},
  {id:"redact",name:"Censurar PDF",icon:"■",category:"edit",level:"advanced",desc:"Elimina contenido de zonas seleccionadas con censura real en el editor Acrobat.",detail:"Destruye texto, imágenes y metadatos dentro de las regiones marcadas de forma irreversible sobre el archivo final.",io:"Entrada: .pdf · Salida: PDF censurado",standaloneTab:true,warning:"Revisa todas las páginas, anotaciones y datos sensibles antes de compartir. No es un saneamiento forense automático."},
  {id:"ocr",name:"Reconocer texto · OCR",icon:"A",category:"optimize",level:"advanced",desc:"Convierte escaneos en PDF con texto que puedes buscar.",detail:"Aplica reconocimiento óptico Tesseract local (español/inglés) con enderezado opcional de hasta 5° y limpieza de papel.",io:"Entrada: PDF escaneado · Salida: PDF buscable",requires:"ocr"},
  {id:"office_to_pdf",name:"Office a PDF",icon:"W",category:"convert",level:"advanced",desc:"Convierte Word, Excel, PowerPoint y OpenDocument.",detail:"Transforma documentos Office y OpenDocument mediante LibreOffice local, con opción para vectorizar capturas incrustadas.",io:"Entrada: .docx/.xlsx/.pptx/.odt · Salida: PDF",requires:"office",accept:".docx,.xlsx,.pptx,.odt,.ods,.odp"},
  {id:"pdf_to_docx",name:"PDF a Word",icon:"W",category:"convert",level:"advanced",desc:"Recupera texto con estilos, tablas e imágenes.",detail:"Exporta texto editable, tablas y formato a .docx; si contiene escaneos, activa OCR + reconstrucción vectorial automática.",io:"Entrada: .pdf · Salida: documento .docx",warning:"Coloca texto y tablas editables en su posición original sobre un fondo con logos, firmas y bordes; mantiene la paginación. Disposición fija: los textos nuevos largos no reacomodan la página; revisa fuentes. Las páginas escaneadas o giradas se conservan como imagen; usa OCR para recuperar texto."},
  {id:"pdf_to_xlsx",name:"PDF a Excel",icon:"X",category:"convert",level:"advanced",desc:"Tablas con formato, texto y referencia visual del original.",detail:"Extrae tablas hacia hojas de cálculo Excel conservando celdas combinadas y una hoja visual de referencia por página.",io:"Entrada: .pdf · Salida: libro .xlsx",warning:"Conserva tablas detectadas, celdas combinadas, estilos y texto fuera de tablas. Cada hoja Original contiene la página como imagen. No infiere fórmulas ni datos de escaneos; revisa la estructura detectada."},
  {id:"pdf_to_pptx",name:"PDF a PowerPoint",icon:"P",category:"convert",level:"advanced",desc:"Diapositivas con texto y tablas editables.",detail:"Genera diapositivas .pptx editables por cada página del PDF, incluyendo reconstrucción OCR/vectorial de diagramas en escaneos.",io:"Entrada: .pdf · Salida: presentación .pptx",warning:"Reconstruye texto horizontal y tablas sobre un fondo limpio; activa el modo escaneo OCR + vectores para páginas escaneadas o diagramas."},
  {id:"crop",name:"Recortar PDF",icon:"⌗",category:"edit",level:"advanced",desc:"Ajusta la región visible usando porcentajes de la página.",detail:"Dibuja visualmente sobre la vista previa o define márgenes porcentuales exactos para recortar bordes no deseados.",io:"Entrada: .pdf · Salida: PDF recortado",warning:"Recorte visual: lo oculto puede seguir en el archivo. Para eliminar información usa Censurar PDF."},
  {id:"resize",name:"Cambiar tamaño",icon:"↔",category:"organize",level:"advanced",desc:"Ajusta páginas a A4, carta u oficio conservando proporciones.",detail:"Estandariza documentos con hojas mixtas hacia dimensiones uniformes A4, Carta u Oficio preservando nitidez vectorial.",io:"Entrada: .pdf · Salida: PDF estandarizado",warning:"Conserva apariencia vectorial, no formularios, anotaciones ni enlaces interactivos."},
  {id:"nup",name:"Varias páginas por hoja",icon:"▦",category:"organize",level:"advanced",desc:"Prepara 2 o 4 páginas por hoja para imprimir.",detail:"Reagrupa 2 o 4 páginas originales en una sola hoja A4, Carta u Oficio para ahorrar papel o revisar borradores.",io:"Entrada: .pdf · Salida: PDF multipágina (2 o 4-up)",warning:"No conserva formularios, anotaciones ni enlaces interactivos."},
  {id:"overlay",name:"Superponer PDF",icon:"▱",category:"edit",level:"advanced",desc:"Aplica un membrete o plantilla sobre un documento.",detail:"Combina tu PDF principal encima o debajo de un segundo PDF plantilla/membrete respetando transparencias.",io:"Entrada: 2 archivos .pdf · Salida: PDF fusionado",multiple:true,warning:"Primero el documento, luego la plantilla PDF. La plantilla debe tener una página o igual cantidad de páginas que el documento."},
  {id:"compare",name:"Comparar PDF",icon:"≠",category:"organize",level:"advanced",desc:"Informe, diferencias de texto y mapas visuales en un ZIP.",detail:"Coteja dos versiones PDF página a página para localizar cambios textuales y mapas visuales resaltados.",io:"Entrada: 2 archivos .pdf · Salida: ZIP con informe",multiple:true,warning:"Selecciona exactamente dos PDF. Compara apariencia a 96 DPI y texto extraído; no certifica equivalencia ni firmas."},
  {id:"stamp",name:"Firma visual e imágenes",icon:"✍",category:"edit",level:"advanced",desc:"Dibuja tu firma o inserta una imagen de firma, sello o logo.",detail:"Permite trazar una firma manuscrita en pantalla o cargar un sello PNG/JPEG y ubicarlo por coordenadas sobre el PDF.",io:"Entrada: PDF + PNG/JPEG · Salida: PDF estampado",multiple:true,accept:".pdf,.png,.jpg,.jpeg",warning:"Primero el PDF y después una imagen PNG/JPEG. Es una firma visual, no firma digital con certificado. Las coordenadas son porcentajes; quite antes cualquier rotación."},
  {id:"grayscale",name:"Escala de grises",icon:"◐",category:"optimize",level:"advanced",desc:"Crea una copia monocromática rasterizada.",detail:"Convierte páginas en color a escala de grises uniforme con DPI configurable útil para impresión en blanco y negro.",io:"Entrada: .pdf · Salida: PDF monocromático",warning:"Pierde texto seleccionable, estructura accesible, enlaces y campos interactivos."},
  {id:"rasterize",name:"Rasterizar PDF",icon:"▦",category:"convert",level:"advanced",desc:"Convierte las páginas en imágenes dentro de un nuevo PDF.",detail:"Aplana cada página como fotografía a una resolución fija impidiendo copiar o editar fuentes y trazos vectoriales.",io:"Entrada: .pdf · Salida: PDF rasterizado",warning:"Pierde texto seleccionable, estructura accesible, enlaces y campos interactivos."},
  {id:"flatten",name:"Aplanar PDF",icon:"▰",category:"edit",level:"advanced",desc:"Integra visualmente anotaciones y campos de formulario.",detail:"Consolida campos rellenados, sellos y comentarios en el flujo visual estático de la página para evitar cambios.",io:"Entrada: .pdf · Salida: PDF aplanado",warning:"Verifica que todos los campos y anotaciones mantengan su apariencia."},
  {id:"repair",name:"Reparar estructura",icon:"⚒",category:"optimize",level:"advanced",desc:"Recupera y reescribe estructuras PDF que qpdf pueda leer.",detail:"Reconstruye tablas de referencias cruzadas y objetos dañados en archivos PDF corruptos o mal exportados.",io:"Entrada: .pdf dañado · Salida: PDF reparado",warning:"No recupera contenido perdido ni certifica integridad visual. Si persisten errores estructurales se rechaza."},
  {id:"web_optimize",name:"Optimizar para web",icon:"↗",category:"optimize",level:"advanced",desc:"Linealiza el PDF para permitir lectura progresiva.",detail:"Reordena los objetos del archivo (Fast Web View) para acelerar la carga página a página en navegadores y servidores.",io:"Entrada: .pdf · Salida: PDF linealizado",warning:"No garantiza menor tamaño ni cambia la política de borrado de EVA PDF Enterprise."},
  {id:"blank_report",name:"Detectar páginas en blanco",icon:"□",category:"organize",level:"advanced",desc:"Genera una lista JSON de candidatas para revisión.",detail:"Analiza tinta, densidad de píxeles y texto de cada página para detectar hojas en blanco sospechosas antes de borrar.",io:"Entrada: .pdf · Salida: informe .json",warning:"Heurística conservadora: verifica visualmente sellos, firmas tenues y páginas escaneadas antes de eliminar."},
  {id:"remove_blank",name:"Eliminar blancos revisados",icon:"⊟",category:"organize",level:"advanced",desc:"Elimina páginas confirmadas que pasan la comprobación de blanco.",detail:"Borra únicamente las páginas en blanco que tú confirmas explícitamente tras revisar el informe previo.",io:"Entrada: .pdf · Salida: PDF sin hojas blancas",warning:"Primero usa Detectar páginas en blanco. Indica explícitamente los números revisados; nunca se eliminan todas las páginas."},
  {id:"form_fields",name:"Consultar formulario",icon:"☷",category:"edit",level:"advanced",desc:"Descarga nombres, tipos y valores de campos AcroForm.",detail:"Lista todos los nombres técnicos y valores actuales de los campos AcroForm del PDF en JSON para automatizar rellenos.",io:"Entrada: .pdf con formulario · Salida: esquema .json",warning:"No admite formularios XFA. El informe puede contener datos sensibles: se descarga a tu equipo."},
  {id:"fill_form",name:"Rellenar formulario",icon:"☑",category:"edit",level:"advanced",desc:"Completa campos AcroForm por sus nombres.",detail:"Inyecta texto y estados en campos de formulario AcroForm enviando un diccionario JSON de clave-valor.",io:"Entrada: .pdf + JSON · Salida: formulario relleno",warning:"Consulta primero los nombres de campos. No ejecuta JavaScript ni firma certificados; no admite XFA ni botones radio."},
  {id:"html_to_pdf",name:"HTML local a PDF",icon:"<>",category:"convert",level:"advanced",desc:"Extrae el texto de un archivo HTML UTF-8 sin conexiones externas.",detail:"Convierte un documento HTML local aislado a PDF limpio leyendo solo su texto y estructura sin cargar scripts ni enlaces.",io:"Entrada: .html/.htm · Salida: PDF de texto",accept:".html,.htm",warning:"Conversión de texto, no captura de una página web: ignora diseño, CSS, imágenes y scripts. Máximo 2 MB. No acepta URLs."},
  {id:"pdf_to_svg",name:"PDF a SVG",icon:"◇",category:"convert",level:"advanced",desc:"Exporta páginas como gráficos SVG con texto convertido en trazados.",detail:"Convierte páginas seleccionadas a archivos vectoriales SVG individuales listos para software de diseño e ilustración.",io:"Entrada: .pdf · Salida: SVG o ZIP con SVGs"},
  {id:"epub_to_pdf",name:"EPUB a PDF",icon:"E",category:"convert",level:"advanced",desc:"Convierte un libro EPUB sin DRM a páginas A4.",detail:"Maqueta automáticamente capítulos e imágenes de un libro electrónico .epub hacia un PDF paginado en A4.",io:"Entrada: .epub sin DRM · Salida: PDF A4",accept:".epub",warning:"Refluye el libro; revisa imágenes, tipografía y saltos. No elimina DRM ni conserva interactividad."},
  {id:"pdf_to_epub",name:"PDF a EPUB de texto",icon:"E",category:"convert",level:"advanced",desc:"Crea un libro de texto con una sección por página.",detail:"Extrae el contenido textual de un PDF en capítulos estructurados para lectores de libros electrónicos .epub.",io:"Entrada: .pdf · Salida: libro .epub",warning:"Solo texto extraíble, sin reconstruir diseño, tablas ni imágenes. Usa OCR primero si es un escaneo."},
  {id:"anti_track",name:"Purga Anti-Rastreo",icon:"🛡",category:"edit",level:"advanced",isV2:true,desc:"Elimina JavaScript, píxeles baliza ocultos y parámetros utm/tracking de enlaces PDF.",detail:"Desactiva acciones JavaScript OpenAction/Names, elimina enlaces baliza 1x1 y limpia parámetros utm/fbclid/gclid de URLs.",io:"Entrada: .pdf · Salida: PDF saneado"},
  {id:"scan_to_office",name:"PDF Escaneado a Office Editable",icon:"✨",category:"convert",level:"professional",isV2:true,desc:"Estilo Acrobat Pro: OCR local de texto + vectorización de tablas, cajas, flechas y diagramas hacia PowerPoint, Word, Excel o PDF.",detail:"Reconoce por OCR texto con color y formato, reconstruye tablas (con/sin bordes y celdas combinadas), vectoriza cajas/flechas de diagramas y limpia texto fantasma del fondo.",io:"Entrada: PDF escaneado o imagen · Salida: .pptx/.docx/.xlsx/.pdf",keywords:"office pdf powerpoint word excel escaneo ocr vectores diagramas acrobat pptx docx xlsx",multiple:true,accept:".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,.bmp",warning:"Reconstruye texto OCR con estilo/color, tablas editables (con y sin bordes), formas vectoriales y conectores; borra texto/tablas duplicadas del fondo."},
  {id:"verify_signatures",name:"Comprobar firmas · offline",icon:"✓",category:"edit",level:"professional",desc:"Informe de integridad criptográfica y cobertura de firmas PDF.",detail:"Audita firmas digitales PAdES/PKCS#7 sin red externa para verificar si el hash permanece íntegro o hubo modificaciones posteriores.",io:"Entrada: .pdf firmado · Salida: informe técnico",warning:"No certifica identidad, confianza, revocación ni validez legal. Sin consultas OCSP/CRL/TSA. Revisa cobertura y cambios: una firma correcta puede cubrir una versión anterior. No admite PDF cifrados ni crea firmas."},
  {id:"forensic_sanitize",name:"Desinfección Forense Profunda",icon:"🧹",category:"edit",level:"professional",isV2:true,desc:"Reconstruye el árbol COS a revisión única (%%EOF=1) eliminando rastros e historial oculto.",detail:"Aplica redacción por patrón y recompila la estructura COS en una única revisión limpia eliminando historial incremental, capas y texto oculto.",io:"Entrada: .pdf · Salida: PDF + reporte forense",warning:"Elimina historial incremental, texto invisible, adjuntos, PieceInfo y capas ocultas."},
  {id:"extract_vectors_svg",name:"Cosechador Vectorial SVG/EPS",icon:"📐",category:"convert",level:"professional",isV2:true,desc:"Extrae gráficos y diagramas vectoriales en SVG editables separados en capas (#vectors/#labels).",detail:"Separa los trazados geométricos de las etiquetas textuales en grupos SVG (#vectors y #labels) con exportación opcional a EPS.",io:"Entrada: .pdf · Salida: ZIP con SVG/EPS"},
  {id:"table_bridge_extract",name:"Puente Tabular Tipado (.xlsx)",icon:"📊",category:"convert",level:"professional",isV2:true,desc:"Extrae tablas con y sin bordes con tipado automático (divisas, fechas, %) y coordenadas de retorno.",detail:"Convierte tablas en Excel con formato real (números, monedas, porcentajes) y hoja oculta _EVA_COORDS para reinyectar cambios al PDF.",io:"Entrada: .pdf · Salida: .xlsx/.json/.zip"},
  {id:"scan_enhance_3d",name:"De-warping 3D y MRC",icon:"📷",category:"optimize",level:"professional",isV2:true,desc:"Corrige perspectiva de cámara, curvatura de lomo, sombras y comprime en capas MRC lossless.",detail:"Endereza fotografías oblicuas de documentos, ilumina papel sombreado y separa texto de fondo fotográfico (MRC).",io:"Entrada: PDF o imagen · Salida: PDF mejorado",multiple:true,accept:".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,.bmp,.heic,.heif"},
  {id:"edit_reflow",name:"Motor Reflujo Inteligente",icon:"¶",category:"optimize",level:"professional",isV2:true,desc:"Reordena columnas mediante XY-Cut y repagina el texto conservando ilustraciones sin solapamientos.",detail:"Detecta columnas reales con XY-Cut y refluye texto actualizado en párrafos adaptables preservando figuras incrustadas.",io:"Entrada: .pdf · Salida: PDF refluido"},
  {id:"liquid_compile",name:"Compilador Liquid PDF",icon:"📱",category:"convert",level:"professional",isV2:true,desc:"Adapta el flujo del PDF a lectores Kindle 6\", móviles o tabletas como HTML5/PDF líquido.",detail:"Recompila documentos densos para pantallas pequeñas (Kindle 6\", móvil 320px, tablet 16:9) conservando lectura continua.",io:"Entrada: .pdf · Salida: PDF líquido o HTML5"},
  {id:"accessibility_tagger",name:"Normalizador WCAG / Audio-Tags",icon:"♿",category:"optimize",level:"professional",isV2:true,desc:"Genera /StructTreeRoot PDF/UA completo, textos alternativos y guion offline Web Speech.",detail:"Construye jerarquía lógica PDF/UA (/H1, /H2, /P, /Figure), audita accesibilidad y genera guion narrable offline.",io:"Entrada: .pdf · Salida: paquete WCAG ZIP/.pdf"},
  {id:"translate_layout",name:"Traductor Vectorial In-Situ",icon:"🌐",category:"convert",level:"professional",isV2:true,desc:"Traduce bloques preservando las cajas de coordenadas y geometría original del documento.",detail:"Traduce español ↔ inglés con red neuronal CTranslate2 100% offline sobre párrafos completos y escaneos OCR sin mover el diseño.",io:"Entrada: .pdf (nativo o escaneado) · Salida: PDF traducido"},
  {id:"research_link",name:"Enlazador Académico BibTeX/DOI",icon:"🎓",category:"convert",level:"professional",isV2:true,desc:"Vincula citas internas/cruzadas entre PDFs y genera paquetes .bib, .ris y CSL APA7.",detail:"Detecta DOIs y referencias [1] entre múltiples artículos PDF creando hipervínculos internos/cruzados y bibliografía estructurada.",io:"Entrada: varios .pdf/.bib · Salida: ZIP con PDFs + .bib/.ris",multiple:true,accept:".pdf,.bib"},
  {id:"forensic_audit",name:"Auditor Custodia y Corpus Local",icon:"⚖",category:"edit",level:"professional",isV2:true,desc:"Analiza historial %%EOF, firmas offline pyHanko, citas huérfanas y similitud de corpus local.",detail:"Audita revisiones incrementales, firmas digitales, referencias sin bibliografía y coincidencia textual comparada localmente.",io:"Entrada: PDF(s) y .txt · Salida: ZIP/JSON forense",multiple:true,accept:".pdf,.txt"},
  {id:"v2_pipeline_studio",name:"Pipeline Batch Sin Código →",icon:"⚙",category:"organize",level:"professional",isV2:true,desc:"Divide PDFs por regex, enruta carpetas, nombra contextualmente y compila plantillas CSV.",detail:"Abre el estudio visual sin código para encadenar reglas de división por regex, enrutamiento de carpetas y plantillas CSV masivas.",io:"Estudio dedicado: /pipeline",workspaceUrl:"/pipeline"},
  {id:"v2_canvas_studio",name:"Canvas Infinito Multidocumento →",icon:"🗺",category:"organize",level:"professional",isV2:true,desc:"Tablero de investigación con extractos sincronizados, enlaces visuales y comparador V1/V2.",detail:"Abre el tablero interactivo para fijar extractos SHA-256 de múltiples PDFs, trazar conexiones y detectar cambios entre versiones.",io:"Estudio dedicado: /canvas",workspaceUrl:"/canvas"},
  {id:"v2_vault_studio",name:"Bóveda Cripto Multi-Rol (.evacrypt) →",icon:"🔐",category:"edit",level:"professional",isV2:true,desc:"Compila contenedores duales AES-256-GCM por rol con descifrado 100% cliente en navegador.",detail:"Empaqueta un PDF en bóveda dual AES-256-GCM con vistas censuradas distintas por cada rol (Auditor, Dirección, Legal, etc.).",io:"Estudio dedicado: /vault",workspaceUrl:"/vault"},
];
// Herramientas por lote: tantos PDF como quepan en la cuota de peso; cada uno se procesa por separado.
const BATCH_TOOLS=new Set(["split","compress","pdf_to_images","extract_text","pdf_to_docx","pdf_to_xlsx","pdf_to_pptx","pdf_to_svg","extract_images","pdf_to_epub"]);
const BULK_TOOLS=new Set([...BATCH_TOOLS,"merge","images_to_pdf","dossier","semantic_replace","pipeline_run","research_link","forensic_audit"]);
const SESSION_TOOL_IDS=new Set([
  "edit","organize","rotate","compress","ocr","watermark","protect","unlock","extract_pages","delete_pages",
  "number_pages","crop","resize","nup","annotate","redact","remove_metadata","grayscale","rasterize",
  "flatten","repair","web_optimize","remove_blank","fill_form",
]);
const MULTI_EDIT_START={id:"multi_edit",name:"Edición múltiple",icon:"✎",category:"edit",level:"advanced",
  desc:"Carga un PDF y elige en la barra lateral las acciones compatibles para modificarlo en esta sesión.",
  accept:".pdf"};
tools.forEach(tool=>{
  if(BATCH_TOOLS.has(tool.id)) {tool.multiple=true; tool.batch=true; tool.desc+=" Admite varios PDF: cada uno se procesa por separado y recibes un ZIP.";}
  if(BULK_TOOLS.has(tool.id)) tool.bulk=true;
});
$("tool-count").textContent=`${tools.length} herramientas · procesamiento local`;
let caps = null, activeCategory = "all", current = null, files = [], edits = [];
let busy = false, resultUrl = null, pageNumber = 1, pageCount = 1, previewImage = null;
let pointerStart = null, viewController = null, previewFile = null;
let sessionActive = false, sessionBaseName = "";
let tooltipTimer = null, tooltipTargetCard = null;
const theme = localStorage.getItem("folio-theme");
if (theme === "dark" || theme === "light") document.documentElement.dataset.theme = theme;
$("theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("folio-theme", next);
});
function normalized(value) { return value.normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase(); }
function unavailableInBackend(tool) {
  if (!caps || !tool || tool.workspaceUrl || tool.standaloneTab) return false;
  const isV2 = Boolean(tool.isV2 || tool.category === "v2" || (Array.isArray(tool.categories) && tool.categories.includes("v2")));
  if (!isV2 || !Array.isArray(caps.v2_operations)) return false;
  return !caps.v2_operations.some(op => op.id === tool.id);
}
function hideToolTooltip() {
  if (tooltipTimer) { clearTimeout(tooltipTimer); tooltipTimer = null; }
  tooltipTargetCard = null;
  const tip = $("tool-tooltip");
  if (!tip) return;
  tip.classList.remove("visible");
  tip.hidden = true;
  tip.setAttribute("aria-hidden", "true");
}
function positionToolTooltip(card, tip) {
  const rect = card.getBoundingClientRect();
  const vw = window.innerWidth, vh = window.innerHeight;
  tip.style.left = "12px";
  tip.style.top = "12px";
  tip.hidden = false;
  const tipRect = tip.getBoundingClientRect();
  const gap = 10;
  let top = rect.bottom + gap;
  if (top + tipRect.height > vh - 12 && rect.top - gap - tipRect.height >= 12) {
    top = rect.top - gap - tipRect.height;
  } else {
    top = Math.max(12, Math.min(vh - tipRect.height - 12, top));
  }
  let left = rect.left + (rect.width - tipRect.width) / 2;
  left = Math.max(12, Math.min(vw - tipRect.width - 12, left));
  tip.style.left = `${Math.round(left)}px`;
  tip.style.top = `${Math.round(top)}px`;
}
function showToolTooltip(tool, card) {
  const tip = $("tool-tooltip");
  if (!tip || !card.isConnected) return;
  tooltipTargetCard = card;
  tip.replaceChildren();
  const head = document.createElement("div"); head.className = "tool-tooltip-head";
  const ico = document.createElement("span"); ico.className = "tool-tooltip-icon"; ico.textContent = tool.icon; ico.setAttribute("aria-hidden", "true");
  const title = document.createElement("span"); title.className = "tool-tooltip-title"; title.textContent = tool.name;
  const tier = document.createElement("span"); tier.className = "tool-tooltip-tier"; tier.textContent = LEVEL_LABELS[tool.level] || "Local";
  head.append(ico, title, tier);
  const body = document.createElement("p"); body.className = "tool-tooltip-body"; body.textContent = tool.detail || tool.desc;
  tip.append(head, body);
  if (tool.io || tool.requires) {
    const meta = document.createElement("p"); meta.className = "tool-tooltip-meta";
    const parts = [];
    if (tool.io) parts.push(tool.io);
    if (tool.id === "translate_layout" && caps?.addons) {
      parts.push(caps.addons.nmt_offline ? "NMT neuronal offline ES↔EN listo" : "Requiere modelo NMT u Opciones IA");
    } else if (tool.requires && caps && !caps[tool.requires]) {
      parts.push("Requiere instalar motor local adicional");
    }
    meta.textContent = parts.join(" · ");
    tip.append(meta);
  }
  tip.setAttribute("aria-hidden", "false");
  positionToolTooltip(card, tip);
  requestAnimationFrame(() => { if (tooltipTargetCard === card && !tip.hidden) tip.classList.add("visible"); });
}
function scheduleToolTooltip(tool, card, delay = 220) {
  if ($("workspace")?.open) return;
  if (tooltipTimer) clearTimeout(tooltipTimer);
  tooltipTargetCard = card;
  tooltipTimer = setTimeout(() => {
    tooltipTimer = null;
    if (tooltipTargetCard === card) showToolTooltip(tool, card);
  }, delay);
}
window.addEventListener("scroll", hideToolTooltip, {passive:true});
window.addEventListener("resize", hideToolTooltip);
document.addEventListener("keydown", e => { if (e.key === "Escape") hideToolTooltip(); });
function renderTools() {
  hideToolTooltip();
  const query = normalized($("search").value);
  $("tool-grid").replaceChildren();
  const visible = tools.filter(t => (activeCategory === "all" || t.level === activeCategory) && normalized(t.name+" "+t.desc+" "+(t.detail||"")+" "+(t.keywords||"")+" "+(LEVEL_LABELS[t.level]||"")).includes(query));
  for (const tool of visible) {
    const card = document.createElement("button");
    card.className = "tool-card"; card.dataset.category = tool.category; card.dataset.level = tool.level || "basic";
    const icon = document.createElement("span"); icon.className="tool-icon"; icon.textContent=tool.icon; icon.setAttribute("aria-hidden","true");
    const title = document.createElement("h3"); title.textContent=tool.name;
    const desc = document.createElement("p"); desc.textContent=tool.desc;
    const levelPill = document.createElement("span"); levelPill.className="tool-level"; levelPill.dataset.level=tool.level || "basic"; levelPill.textContent=LEVEL_LABELS[tool.level] || "Local";
    const arrow = document.createElement("span"); arrow.className="card-arrow"; arrow.textContent="↗"; arrow.setAttribute("aria-hidden","true");
    card.append(icon, title, desc, levelPill, arrow);
    if (unavailableInBackend(tool)) {
      const badge = document.createElement("span"); badge.className="badge"; badge.textContent="REINICIAR SERVIDOR"; card.append(badge);
    } else if (caps && tool.requires && !caps[tool.requires]) {
      const badge = document.createElement("span"); badge.className="badge"; badge.textContent="MOTOR PENDIENTE"; card.append(badge);
    }
    card.addEventListener("pointerenter", e => { if (e.pointerType !== "touch") scheduleToolTooltip(tool, card); });
    card.addEventListener("pointerleave", hideToolTooltip);
    card.addEventListener("pointerdown", hideToolTooltip);
    card.addEventListener("focus", () => { if (card.matches(":focus-visible")) scheduleToolTooltip(tool, card, 60); });
    card.addEventListener("blur", hideToolTooltip);
    card.addEventListener("click", () => {
      hideToolTooltip();
      if (tool.workspaceUrl) {
        window.location.href = tool.workspaceUrl;
        return;
      }
      openTool(tool);
    });
    $("tool-grid").append(card);
  }
  $("empty").hidden = visible.length > 0;
}
document.querySelectorAll(".filter").forEach(button => button.addEventListener("click", () => {
  if(button.id==="multi-edit-tab") {
    document.querySelectorAll(".filter").forEach(item => {
      item.classList.toggle("active",item===button);
      item.setAttribute("aria-pressed",String(item===button));
    });
    startMultiEdit();
    return;
  }
  activeCategory=button.dataset.category;
  document.querySelectorAll(".filter").forEach(item => { item.classList.toggle("active", item === button); item.setAttribute("aria-pressed",String(item === button)); });
  renderTools();
}));
$("search").addEventListener("input", renderTools);
function startMultiEdit() {
  if($("workspace").open) return;
  activeCategory="all";
  sessionActive=true;
  sessionBaseName="";
  $("workspace").classList.add("multi-edit-workspace");
  openTool(MULTI_EDIT_START,{keepSessionFile:true});
}
function field(name, label, {type="text",value="",hint="",choices=null,min=null,max=null,placeholder=""}={}) {
  const wrapper=document.createElement("label"); wrapper.textContent=label;
  const input=document.createElement(choices ? "select" : type==="textarea" ? "textarea" : "input"); input.name=name; input.id="option-"+name;
  if (choices) choices.forEach(([key,text]) => { const opt=document.createElement("option"); opt.value=key; opt.textContent=text; input.append(opt); });
  else { if(type!=="textarea") input.type=type; if(type==="number") input.step="any"; input.placeholder=placeholder; input.autocomplete=type === "password" ? "new-password" : "off"; input.maxLength=10000; }
  input.value=value; if(min !== null) input.min=min; if(max !== null) input.max=max;
  wrapper.append(input);
  if(hint) { const small=document.createElement("small"); small.textContent=hint; wrapper.append(small); }
  $("options").append(wrapper);
  return input;
}
function clearResult() { if(resultUrl) URL.revokeObjectURL(resultUrl); resultUrl=null; $("download").hidden=true; $("download-link").removeAttribute("href"); }
function setStatus(text, error=false) { $("status").textContent=text; $("status").classList.toggle("error",error); }
function renderSessionTools() {
  const nav=$("session-tools"), list=$("session-tool-list");
  if(!nav || !list) return;
  nav.hidden=!sessionActive;
  $("workspace-body").classList.toggle("has-session-tools",sessionActive);
  list.replaceChildren();
  if(!sessionActive)return;
  $("session-document").textContent=files[0]?.name || (sessionBaseName ? `${sessionBaseName}.pdf` : "Sin PDF cargado");
  for(const tool of tools.filter(item=>SESSION_TOOL_IDS.has(item.id))) {
    const button=document.createElement("button");
    button.type="button";
    button.className="session-tool";
    button.classList.toggle("active",tool.id===current.id);
    button.disabled=busy;
    button.setAttribute("aria-current",tool.id===current.id?"page":"false");
    button.textContent=`${tool.icon} ${tool.name}`;
    button.addEventListener("click",()=>openTool(tool,{keepSessionFile:true}));
    list.append(button);
  }
}
function openTextEditorSession(file) {
  const params=new URLSearchParams();
  params.set("tool",current?.id==="redact" ? "redact" : current?.id==="annotate" ? "highlight" : "edit");
  if(sessionActive) params.set("session","1");
  if($("workspace").classList.contains("multi-edit-workspace")) params.set("multi","1");
  const target="/editor?"+params;
  if(!file) { window.location.href=target; return; }
  if(!window.saveFileForEditor) {
    throw new Error("No se pudo preparar el PDF para el editor.");
  }
  window.saveFileForEditor(file).then(()=>{
    window.location.href=target;
  }).catch(error=>setStatus("No se pudo abrir el editor: "+error.message,true));
}
document.addEventListener("DOMContentLoaded",async()=>{
  if(new URLSearchParams(window.location.search).get("resume")!=="1")return;
  const file=window.retrieveFileForEditor && await window.retrieveFileForEditor();
  if(!file) {
    $("connection").textContent="No se encontró el PDF para continuar la sesión. Selecciónalo de nuevo.";
    return;
  }
  const editTool=tools.find(tool=>tool.id==="edit");
  if(new URLSearchParams(window.location.search).get("multi")==="1") {
    startMultiEdit();
    openTool(editTool,{keepSessionFile:true});
  } else {
    openTool(editTool);
    sessionActive=true;
  }
  addFiles([file]);
});
function openTool(tool,{keepSessionFile=false}={}) {
  if(!keepSessionFile) {
    files=[];
    sessionActive=false;
    sessionBaseName="";
  }
  current=tool; edits=[]; pageNumber=1; pageCount=1; previewImage=null; previewFile=null;
  if(!keepSessionFile) clearResult();
  setStatus(""); $("process-form").reset(); $("options").replaceChildren();
  const choosingSessionTool=tool.id==="multi_edit";
  $("options").hidden=choosingSessionTool;
  $("process").hidden=choosingSessionTool;
  $("form-footer").hidden=choosingSessionTool;
  $("global-warning").hidden=choosingSessionTool;
  $("workspace").querySelector(".workspace-heading .eyebrow").textContent=
    $("workspace").classList.contains("multi-edit-workspace")
      ? "EDICIÓN MÚLTIPLE · UNA SESIÓN · SIN HISTORIAL"
      : "ESPACIO TEMPORAL · SIN HISTORIAL";
  $("workspace-title").textContent=tool.name; $("tool-description").textContent=tool.desc;
  const staleBackend=unavailableInBackend(tool);
  const missing=caps && tool.requires && !caps[tool.requires];
  const missingNmt=tool.id==="translate_layout" && caps && !caps.addons?.nmt_offline && !caps.addons?.loopback_slm && !caps.addons?.edge_ai_opt_in;
  $("tool-warning").hidden=!tool.warning && !missing && !staleBackend && !missingNmt;
  $("tool-warning").textContent=staleBackend
    ? "El servidor EVA PDF en ejecución tiene una versión anterior en memoria que aún no registra esta herramienta. Cierra y reinicia 'servidor local.bat' (o run-lan.ps1) y recarga esta página (Ctrl+F5)."
    : missing
      ? "Este motor aún no está disponible. Contacta al administrador para completar su instalación local."
      : missingNmt
        ? "Modelos neuronales NMT offline (addons/pack-nmt) no detectados: se usará el glosario básico. Ejecuta deploy\\install-nmt.ps1 para traducción completa ES↔EN."
        : (tool.warning || "");
  $("files").accept=tool.accept || ".pdf"; $("files").multiple=Boolean(tool.multiple && !keepSessionFile);
  $("upload-limits").textContent=uploadLimits(tool);
  if (!["multi_edit","images_to_pdf","office_to_pdf","html_to_pdf","heic_to_jpg","epub_to_pdf","verify_signatures"].includes(tool.id)) field("password","Contraseña actual (si el PDF tiene)",{type:"password"});
  if (["organize","rotate","pdf_to_images","extract_text","watermark","pdf_to_docx","pdf_to_xlsx","pdf_to_pptx","scan_to_office"].includes(tool.id))
    field("pages",tool.id === "organize" ? "Páginas en el orden deseado" : "Páginas a procesar",{placeholder:"Ej. 1,3,5-8",hint:tool.id === "organize" ? "Las páginas omitidas se eliminan. Puedes invertir rangos: 5-1." : "Vacío: todas las páginas (o todas las imágenes cargadas)."});
  if(tool.id==="split") field("groups","Grupos de páginas",{placeholder:"Ej. 1-3;4-6;7",hint:"Separa grupos con punto y coma. Vacío: un PDF por página."});
  if(tool.id==="rotate") field("angle","Ángulo de giro",{choices:[["90","90° a la derecha"],["180","180°"],["270","90° a la izquierda"]],value:"90"});
  if(tool.id==="compress") {
    field("compression","Tipo de compresión",{choices:[["lossless","Estructural, sin pérdida"],["raster","Visual, con pérdida (120 DPI)"]],value:"lossless",hint:"La compresión visual elimina texto seleccionable, OCR, formularios y enlaces. No se usa JBIG2 con pérdida."});
  }
  if(["ocr","pdf_to_images"].includes(tool.id)) field("dpi","Resolución (DPI)",{type:"number",value:tool.id==="ocr"?"200":"144",min:tool.id==="ocr"?100:72,max:300});
  if(tool.id==="ocr") field("preprocess","Preparación del escaneo",{choices:[["none","Sin preprocesamiento"],["deskew","Enderezar hasta 5°"],["clean","Enderezar y limpiar en blanco y negro"]],value:"none",hint:"No corrige giros de 90°/180°. La limpieza puede eliminar sellos o trazos tenues; revisa el resultado."});
  if(tool.id==="watermark") field("text","Texto de la marca",{placeholder:"Ej. COPIA DE TRABAJO"});
  if(tool.id==="protect") field("new_password","Nueva contraseña",{type:"password",hint:"Mínimo 8 caracteres, máximo 40 bytes UTF-8. Guárdala: no podemos recuperarla."});
  const pageTools=["extract_pages","delete_pages","number_pages","extract_images","crop","resize","nup","overlay","stamp","grayscale","rasterize","remove_blank","blank_report","pdf_to_svg"];
  if(pageTools.includes(tool.id)) field("pages","Páginas seleccionadas",{placeholder:"Ej. 1,3,5-8",hint:["delete_pages","remove_blank"].includes(tool.id)?"Obligatorio: páginas que confirmas eliminar.":"Vacío: todas."});
  if(tool.id==="number_pages") {
    field("start","Número inicial",{type:"number",value:"1",min:0,max:1000000});
    field("size","Tamaño del número",{type:"number",value:"11",min:6,max:36});
    field("position","Posición",{choices:[["bottom","Abajo"],["top","Arriba"]],value:"bottom"});
  }
  if(["crop","stamp"].includes(tool.id)) for(const [key,label,value] of [
    ["x","Izquierda %","10"],["y","Arriba %",tool.id==="stamp"?"70":"10"],
    ["width","Ancho %",tool.id==="stamp"?"30":"80"],["height","Alto %",tool.id==="stamp"?"15":"80"],
  ]) field(key,label,{type:"number",value,min:key==="width"||key==="height"?1:0,max:100});
  if(["resize","nup"].includes(tool.id)) field("paper","Papel de salida",{choices:[["a4","A4"],["letter","Carta"],["legal","Oficio / Legal"]],value:"a4"});
  if(tool.id==="nup") field("per_sheet","Páginas por hoja",{choices:[["2","2"],["4","4"]],value:"4"});
  if(tool.id==="overlay") field("layer","Plantilla",{choices:[["foreground","Encima del documento"],["background","Como fondo"]],value:"foreground"});
  if(tool.id==="dossier") {
    const cover=field("include_cover","Incluir página inicial (portada)",{type:"checkbox"});
    cover.checked=true;
    const title=field("text","Título de la portada",{value:"Expediente documental"});
    cover.addEventListener("change",()=>{title.disabled=!cover.checked;});
  }
  if(tool.id==="fill_form") field("fields","Campos y valores (JSON)",{type:"textarea",value:'{"nombre_del_campo": "valor"}',hint:"Los valores son textos; para casillas usa Off o su estado activo."});
  if(["grayscale","rasterize"].includes(tool.id)) field("dpi","Resolución (DPI)",{type:"number",value:"144",min:72,max:300});
  if(tool.id==="pdf_to_images") field("image_format","Formato",{choices:[["png","PNG"],["jpg","JPEG"],["tiff","TIFF por página"]],value:"png"});
  if(tool.id==="scan_to_office") {
    field("target_format","Formato exportado editable",{choices:[["pptx","PowerPoint editable (.pptx) · Modo Acrobat Pro"],["docx","Word editable (.docx)"],["xlsx","Excel editable (.xlsx)"],["pdf","PDF vectorial + OCR limpio (.pdf)"]],value:"pptx"});
    field("ocr_dpi","Resolución de análisis y OCR",{choices:[["150","150 DPI · Rápido"],["200","200 DPI · Recomendado"],["300","300 DPI · Alta precisión"]],value:"200"});
    field("preprocess","Limpieza previa de escaneo",{choices:[["auto","Automático (enderezado si requiere)"],["deskew","Enderezar inclinación (hasta 5°)"],["clean","Enderezar y limpiar sombras/papel"],["none","Sin preprocesamiento"]],value:"auto"});
    const vt=field("vectorize_tables","Reconocer y reconstruir tablas editables (con y sin bordes)",{type:"checkbox"}); vt.checked=true;
    const vd=field("vectorize_diagrams","Vectorizar formas, cajas y flechas de diagramas",{type:"checkbox"}); vd.checked=true;
    field("ocr_mode","Lectura de texto OCR",{choices:[["auto","Automático (OCR local si es escaneo)"],["force","Forzar nueva lectura OCR en todas las páginas"],["existing_only","Solo capa OCR oculta existente"]],value:"auto"});
  }
  if(["pdf_to_pptx","pdf_to_docx","pdf_to_xlsx"].includes(tool.id)) {
    const sem=field("scan_editable_mode","Refinar escaneos (OCR + vectores de tablas y diagramas · estilo Acrobat Pro)",{type:"checkbox",hint:"Cuando una página sea un escaneo o esté girada, ejecuta OCR local, reconstruye tablas y diagramas vectoriales editables y limpia texto fantasma del fondo."});
    sem.checked=true;
    const vd=field("vectorize_diagrams","Vectorizar cajas, conectores y diagramas en páginas escaneadas",{type:"checkbox"}); vd.checked=true;
    field("ocr_dpi","DPI de reconocimiento (solo si es escaneo)",{choices:[["150","150 DPI"],["200","200 DPI (Recomendado)"],["300","300 DPI"]],value:"200"});
    field("preprocess","Preprocesamiento de escaneo",{choices:[["auto","Automático"],["deskew","Enderezar"],["clean","Enderezar + limpiar fondo"],["none","Sin cambios"]],value:"auto"});
    sem.addEventListener("change",()=>{
      const on=sem.checked;
      vd.disabled=!on;
      $("option-ocr_dpi").disabled=!on;
      $("option-preprocess").disabled=!on;
    });
  }
  if(tool.id==="office_to_pdf") {
    field("refine_scans","Refinar imágenes escaneadas incrustadas (OCR buscable + vectorizar tablas/diagramas)",{type:"checkbox",hint:"Opcional: si tu archivo de Office contiene capturas o escaneos pegados, intenta reconstruir tablas/diagramas vectoriales y capa de texto buscable en el PDF."});
  }
  if(tool.id==="liquid_compile") field("preset","Tamaño de pantalla objetivo",{choices:[["kindle_6","Kindle 6\""],["mobile","Móvil (320px)"],["tablet_16_9","Tablet 16:9"],["a4","A4"],["letter","Carta"]],value:"kindle_6"});
  if(tool.id==="translate_layout") {
    field("source_lang","Idioma origen",{choices:[["es","Español"],["en","Inglés"]],value:"es"});
    const nmtReady=Boolean(caps?.addons?.nmt_offline);
    const pairs=Array.isArray(caps?.addons?.nmt_pairs) && caps.addons.nmt_pairs.length
      ? caps.addons.nmt_pairs.map(p=>p.replace("_","→").toUpperCase()).join(", ")
      : "ES↔EN";
    field("target_lang","Idioma destino",{
      choices:[["en","Inglés"],["es","Español"]],
      value:"en",
      hint:nmtReady
        ? `Motor neuronal CTranslate2 100% offline activo (${pairs}). Incluye OCR automático si el PDF es un escaneo.`
        : "Modo glosario básico (instala addons/pack-nmt con deploy\\install-nmt.ps1 para traducción neuronal completa)."
    });
  }
  if(tool.id==="accessibility_tagger") field("lang","Idioma del árbol PDF/UA",{value:"es-ES"});
  if(tool.id==="anti_track") field("strip_external_uris","Eliminar también enlaces externos http/https",{type:"checkbox"});
  $("editor").hidden=tool.id!=="crop";
  $("signature-editor").hidden=tool.id!=="stamp";
  clearSignature();
  if(tool.id==="edit" || tool.standaloneTab) {
    const tabBtn=document.createElement("button");
    tabBtn.type="button";
    tabBtn.className="primary";
    tabBtn.style.cssText="width:100%; margin:8px 0 14px 0; padding:12px; font-weight:600; text-align:center; cursor:pointer;";
    tabBtn.textContent="Abrir editor Acrobat →";
    tabBtn.addEventListener("click", () => {
      try {
        openTextEditorSession(files[0]);
      } catch(error) { setStatus(error.message,true); }
    });
    $("options").append(tabBtn);
    $("process").textContent="Abrir editor Acrobat →";
  } else {
    $("process").innerHTML='Procesar documento <span aria-hidden="true">→</span>';
  }
  $("process").disabled=Boolean(missing || staleBackend) || !caps;
  renderFiles(); renderEdits(); drawPreview(); renderSessionTools();
  if(!$("workspace").open) $("workspace").showModal();
}
function closeWorkspace() {
  if(busy) { setStatus("Espera a que termine el trabajo. El servidor eliminará sus temporales al finalizar."); return; }
  if(viewController) viewController.abort();
  const wasMultiEdit=$("workspace").classList.contains("multi-edit-workspace");
  $("workspace").close(); $("workspace").classList.remove("multi-edit-workspace");
  const multiEditTab=$("multi-edit-tab");
  if(wasMultiEdit && multiEditTab) {
    multiEditTab.classList.remove("active");
    multiEditTab.setAttribute("aria-pressed","false");
    const allTab=document.querySelector('.filter[data-category="all"]');
    if(allTab) {
      allTab.classList.add("active");
      allTab.setAttribute("aria-pressed","true");
      activeCategory="all";
      renderTools();
    }
  }
  files=[]; edits=[]; sessionActive=false; sessionBaseName=""; previewImage=null; previewFile=null; $("files").value="";
  $("process-form").reset(); clearResult(); renderFiles(); drawPreview();
  $("options").replaceChildren(); $("edit-list").replaceChildren(); clearSignature(); renderSessionTools();
}
$("close-workspace").addEventListener("click", closeWorkspace);
$("workspace").addEventListener("cancel", event => { event.preventDefault(); closeWorkspace(); });
function addFiles(incoming) {
  if(busy) return;
  const selected=Array.from(incoming);
  const singleSessionFile=sessionActive && (SESSION_TOOL_IDS.has(current?.id) || current?.id==="multi_edit");
  if(singleSessionFile && (selected.length>1 || selected.some(file=>!file.name.toLowerCase().endsWith(".pdf")))) {
    setStatus("La sesión de modificaciones solo admite un PDF cada vez.",true);
    $("files").value="";
    return;
  }
  const next=singleSessionFile ? selected.slice(0,1) : current.multiple ? files.concat(selected) : selected.slice(0,1);
  const problem=quotaProblem(next);
  if(problem) { setStatus(problem+" No se agregaron los archivos.",true); $("files").value=""; return; }
  files=next;
  if((current?.id === "edit" || current?.standaloneTab || current?.id === "edit_text_pro")
    && !SESSION_TOOL_IDS.has(current?.id) && files.length > 0) {
    const target = files[0];
    openTextEditorSession(target);
    return;
  }
  if(singleSessionFile && files.length===1 && files[0].name.toLowerCase().endsWith(".pdf")) {
    sessionActive=true;
    sessionBaseName=files[0].name.replace(/\.pdf$/i,"");
    $("files").multiple=false;
  }
  edits=[]; previewImage=null; previewFile=null; pageNumber=1; pageCount=1;
  clearResult(); setStatus(""); renderFiles(); renderEdits(); drawPreview(); renderSessionTools();
}
$("files").addEventListener("change", e => addFiles(e.target.files));
$("dropzone").addEventListener("keydown", event => { if(event.key==="Enter" || event.key===" ") { event.preventDefault(); if(!busy) $("files").click(); } });
["dragenter","dragover"].forEach(name => $("dropzone").addEventListener(name,event => {event.preventDefault(); if(!busy) $("dropzone").classList.add("dragging");}));
["dragleave","drop"].forEach(name => $("dropzone").addEventListener(name,event => {event.preventDefault(); $("dropzone").classList.remove("dragging");}));
$("dropzone").addEventListener("drop", event => addFiles(event.dataTransfer.files));
function renderFiles() {
  $("file-list").replaceChildren();
  files.forEach((file,index) => {
    const row=document.createElement("li"), name=document.createElement("span"), size=document.createElement("span");
    name.className="file-name"; name.textContent=`${index+1}. ${file.name}`;
    size.className="file-size"; size.textContent=(file.size/1024/1024).toFixed(2)+" MB"; row.append(name,size);
    if(current && current.multiple) for(const [label,delta] of [["↑",-1],["↓",1]]) {
      const button=document.createElement("button"); button.type="button"; button.textContent=label; button.disabled=busy || index+delta<0 || index+delta>=files.length;
      button.setAttribute("aria-label",`${delta<0?"Subir":"Bajar"} ${file.name}`);
      button.addEventListener("click",()=>{[files[index],files[index+delta]]=[files[index+delta],files[index]];clearResult();renderFiles();}); row.append(button);
    }
    const remove=document.createElement("button"); remove.type="button"; remove.textContent="×"; remove.disabled=busy; remove.setAttribute("aria-label",`Quitar ${file.name}`);
    remove.addEventListener("click",()=>{ files.splice(index,1); if(!files.length)sessionBaseName=""; edits=[]; previewImage=null;previewFile=null;clearResult();renderFiles();renderEdits();drawPreview();renderSessionTools(); });row.append(remove);
    $("file-list").append(row);
  });
  if(current) $("upload-limits").textContent=uploadLimits(current);
}
function options() {
  const result={};
  $("options").querySelectorAll("input,select,textarea").forEach(input=>{
    if(!input.disabled) result[input.name]=input.type==="checkbox" ? input.checked : input.value;
  });
  if(current.id==="fill_form") {
    try { result.fields=JSON.parse(result.fields); } catch { throw new Error("Los campos deben ser un objeto JSON válido."); }
  }
  return result;
}
function limitLabel(mb) {
  return mb>=1024 ? `${Number((mb/1024).toFixed(1))} GB` : `${mb} MB`;
}
function sizeLabel(bytes) {
  return bytes>=1024**3 ? `${(bytes/1024**3).toFixed(2)} GB` : `${(bytes/1024**2).toFixed(1)} MB`;
}
function quota() {
  const count=current?.bulk ? (caps?.max_batch_files || 200) : (caps?.max_files || 5);
  return {count, perFile:(caps?.max_file_mb || 1024)*1024*1024, total:(caps?.max_upload_mb || 1024)*1024*1024};
}
// Cuota por sesion de procesamiento: maximo de archivos y peso conjunto.
function quotaProblem(list) {
  const limit=quota(), used=list.reduce((sum,file)=>sum+file.size,0);
  if(list.length>limit.count) return `Máximo ${limit.count} archivos por sesión de procesamiento.`;
  if(list.some(file=>file.size>limit.perFile)) return `Cada archivo debe pesar como máximo ${sizeLabel(limit.perFile)}.`;
  if(used>limit.total) return `El peso conjunto (${sizeLabel(used)}) supera el límite de ${sizeLabel(limit.total)} por sesión.`;
  return "";
}
function uploadLimits(tool) {
  const limit=quota(), used=files.reduce((sum,file)=>sum+file.size,0);
  const scope=sessionActive ? `un PDF de hasta ${sizeLabel(limit.perFile)}`
    : tool.bulk ? `tantos archivos como quepan en ${sizeLabel(limit.total)}`
    : tool.multiple ? `hasta ${limit.count} archivos · ${sizeLabel(limit.total)} en conjunto` : `un archivo de hasta ${sizeLabel(limit.perFile)}`;
  const usage=files.length ? ` · usado ${sizeLabel(used)} de ${sizeLabel(limit.total)} (${files.length} ${files.length===1?"archivo":"archivos"})` : "";
  const budget=caps?.timeout_seconds || 120;
  const pages=caps?.max_pages ? `hasta ${caps.max_pages} páginas por PDF` : "sin tope fijo de páginas";
  const recommended=caps?.queue
    ? ` · recomendado: hasta ${caps.queue.recommended_upload_mb} MB en conjunto; desde ${caps.queue.heavy_upload_mb} MB, carga pesada`
    : "";
  return `${scope}${usage} · ${tool.accept || "PDF"} · ${pages} · motor: máximo ${budget} s${recommended}`;
}
function validateFiles() {
  if(!files.length) throw new Error("Selecciona un archivo antes de continuar.");
  const problem=quotaProblem(files); if(problem) throw new Error(problem);
  const allowed=(current.accept || ".pdf").split(",");
  if(files.some(file=>!allowed.some(ext=>file.name.toLowerCase().endsWith(ext)))) throw new Error("Hay un formato no admitido en la selección.");
}
async function send(operation, extra={}, signal) {
  validateFiles();
  const form=new FormData(); files.forEach(file=>form.append("files",file)); form.append("options",JSON.stringify({...options(),...extra}));
  const response=await window.folioProcess(operation,form,{signal});
  if(!response.ok) {
    const json=await response.json().catch(()=>({error:"El servidor rechazó la solicitud."}));
    throw new Error(json.error);
  }
  return response;
}
function setBusy(value) {
  busy=value; $("process-form").setAttribute("aria-busy",String(value));
  $("process-form").querySelectorAll("button,input,select,textarea").forEach(element=>element.disabled=value);
  if(!value) {
    $("process").disabled=!caps || Boolean(current.requires && !caps[current.requires]) || unavailableInBackend(current); renderFiles();
  }
  renderSessionTools();
  if(value) $("process").textContent="Procesando…";
  else if(current?.id==="edit" || current?.standaloneTab) $("process").textContent="Abrir editor Acrobat →";
  else $("process").innerHTML='Procesar documento <span aria-hidden="true">→</span>';
}
$("process-form").addEventListener("submit",async event=>{
  event.preventDefault(); if(busy)return;
  if(current?.id==="multi_edit") return;
  if(!sessionActive) clearResult();
  try{
    if(current.id==="edit" || current.standaloneTab) {
      openTextEditorSession(files[0]);
      return;
    }
    validateFiles();
    if(current.id==="merge" && files.length<2) throw new Error("Selecciona al menos dos PDF.");
    if(["overlay","compare","stamp"].includes(current.id) && files.length!==2) throw new Error("Selecciona exactamente dos archivos en el orden indicado.");
    const payload=options();
    setBusy(true); setStatus("Enviando al servidor. El aviso mostrará la espera o el procesamiento…");
    // Los controles deshabilitados no se serializan con FormData; options se toma explícitamente.
    const response=await send(current.operation || current.id,payload);
    const blob=await response.blob();
    if(!["complete","on-delivery"].includes(response.headers.get("X-PDF-Cleanup"))) throw new Error("El servidor no confirmó la eliminación temporal.");
    if(sessionActive) {
      if(!response.headers.get("Content-Type")?.toLowerCase().includes("application/pdf")) {
        throw new Error("Esta acción no devolvió un PDF y no puede continuar dentro de la sesión.");
      }
      files=[new File([blob],`${sessionBaseName} (sesion).pdf`,{type:"application/pdf"})];
      $("files").value="";
      renderFiles();
      renderSessionTools();
    }
    clearResult();
    resultUrl=URL.createObjectURL(blob); const link=$("download-link"); link.href=resultUrl;
    const disposition=response.headers.get("Content-Disposition") || "";
    const match=disposition.match(/filename="?([^";]+)"?/); link.download=match ? match[1] : "resultado";
    $("result-notice").textContent=response.headers.get("X-PDF-Notice") || "Documento procesado correctamente.";
    $("download").hidden=false; setStatus(sessionActive
      ? "Listo. El PDF actualizado está disponible para la siguiente modificación de esta sesión."
      : "Listo. Los originales y temporales ya se eliminaron del servidor.");
    $("option-password") && ($("option-password").value=""); $("option-new_password") && ($("option-new_password").value="");
    link.focus();
  }catch(error){setStatus(error instanceof TypeError ? "Se perdió la conexión. El servidor continuará la limpieza al finalizar; vuelve a intentar cuando esté disponible." : error.message,true);}
  finally{setBusy(false);}
});
async function loadPreview(nextPage=pageNumber) {
  if(busy)return;
  try {
    validateFiles(); const payload=options(); viewController=new AbortController();
    setBusy(true); setStatus("Creando vista previa temporal…");
    const response=await send("inspect",{...payload,page:nextPage},viewController.signal); const data=await response.json();
    const image=new Image();
    await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(new Error("No se pudo mostrar la vista previa."));image.src="data:image/jpeg;base64,"+data.image;});
    previewImage=image; previewFile=files[0];pageNumber=data.page;pageCount=data.pages;drawPreview();
    setStatus("Vista lista. Dibuja una caja o usa las coordenadas por teclado.");
  }catch(error){if(error.name!=="AbortError")setStatus(error.message,true);}
  finally{viewController=null;setBusy(false);}
}
$("load-preview").addEventListener("click",()=>loadPreview());
$("previous").addEventListener("click",()=>{if(pageNumber>1)loadPreview(pageNumber-1);});
$("next").addEventListener("click",()=>{if(pageNumber<pageCount)loadPreview(pageNumber+1);});
function drawPreview(draft=null) {
  const canvas=$("preview"), ctx=canvas.getContext("2d");
  if(!previewImage) {canvas.width=600;canvas.height=180;ctx.clearRect(0,0,600,180);ctx.fillStyle=getComputedStyle(document.documentElement).getPropertyValue("--paper-muted").trim();ctx.font="16px Segoe UI";ctx.textAlign="center";ctx.fillText("Carga un PDF para abrir su vista previa",300,95);return;}
  canvas.width=previewImage.naturalWidth;canvas.height=previewImage.naturalHeight;
  ctx.drawImage(previewImage,0,0);
  const display=edits.filter(edit=>edit.page===pageNumber);if(draft)display.push(draft);
  for(const edit of display){
    const {x,y,w,h}=edit;ctx.fillStyle=edit.kind==="redact"?"rgba(0,0,0,.85)":"rgba(98,89,170,.14)";
    ctx.strokeStyle=edit.kind==="redact"?"#333":"#6259aa";ctx.lineWidth=2;
    ctx.fillRect(x*canvas.width,y*canvas.height,w*canvas.width,h*canvas.height);
    ctx.strokeRect(x*canvas.width,y*canvas.height,w*canvas.width,h*canvas.height);
  }
  $("page-label").textContent=`Página ${pageNumber} de ${pageCount}`;
}
function point(event) {const rect=$("preview").getBoundingClientRect();return{x:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y:Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))};}
function makeEdit(box) {return {...box,kind:"highlight",page:pageNumber};}
function appendEdit(box) {
  if(busy || !previewImage || previewFile!==files[0]) {setStatus("Carga la vista previa primero.",true);return;}
  const edit=makeEdit(box);
  if(current.id!=="crop") return;
  if(!Object.values(box).every(Number.isFinite) || box.w<=0 || box.h<=0 || box.x<0 || box.y<0 || box.x+box.w>1.001 || box.y+box.h>1.001){setStatus("La caja debe quedar dentro de la página.",true);return;}
  for(const [key,value] of Object.entries({x:box.x,y:box.y,width:box.w,height:box.h})) $("option-"+key).value=(value*100).toFixed(2);
  edits=[edit];clearResult();renderEdits();drawPreview();setStatus("Zona de recorte elegida. Procesa para aplicarla a la selección de páginas.");
}
$("preview").addEventListener("pointerdown",event=>{if(!previewImage || busy)return;pointerStart=point(event);$("preview").setPointerCapture(event.pointerId);});
$("preview").addEventListener("pointermove",event=>{if(!pointerStart)return;const end=point(event);drawPreview(makeEdit({x:Math.min(pointerStart.x,end.x),y:Math.min(pointerStart.y,end.y),w:Math.abs(end.x-pointerStart.x),h:Math.abs(end.y-pointerStart.y)}));});
$("preview").addEventListener("pointerup",event=>{if(!pointerStart)return;const end=point(event),start=pointerStart;pointerStart=null;const box={x:Math.min(start.x,end.x),y:Math.min(start.y,end.y),w:Math.abs(end.x-start.x),h:Math.abs(end.y-start.y)};if(box.w>.005&&box.h>.005)appendEdit(box);else drawPreview();});
$("preview").addEventListener("pointercancel",()=>{pointerStart=null;drawPreview();});
$("add-box").addEventListener("click",()=>appendEdit({x:Number($("box-x").value)/100,y:Number($("box-y").value)/100,w:Number($("box-w").value)/100,h:Number($("box-h").value)/100}));
function renderEdits() {
  $("edit-list").replaceChildren();
  edits.forEach((edit,index)=>{
    const li=document.createElement("li"),span=document.createElement("span"),remove=document.createElement("button");
    span.className="file-name";span.textContent=`Pág. ${edit.page}: zona de recorte`;
    remove.type="button";remove.textContent="Quitar";remove.addEventListener("click",()=>{if(busy)return;edits.splice(index,1);clearResult();renderEdits();drawPreview();});
    li.append(span,remove);$("edit-list").append(li);
  });
}
window.addEventListener("pagehide",()=>{clearResult();files=[];edits=[];previewImage=null;previewFile=null;stopCamera();clearSignature();});
renderTools();
fetch("/api/capabilities").then(response=>{if(!response.ok)throw new Error();return response.json();}).then(data=>{
  caps=data; const engines=[data.office?"Office listo":"Office pendiente",data.ocr?"OCR español/inglés listo":"OCR pendiente",data.addons?.nmt_offline?"Traducción ES↔EN offline lista":"Traducción NMT pendiente"];
  if (data.scanners && data.scanners.available) engines.push(`Escáner listo (${data.scanners.count})`);
  const hasStaleTools=tools.some(unavailableInBackend);
  $("connection").textContent=`Motor local conectado · ${engines.join(" · ")} · ${limitLabel(data.max_upload_mb)} por sesión` +
    (hasStaleTools ? " · ⚠ Servidor en memoria desactualizado: reinicia 'servidor local.bat' y recarga (Ctrl+F5)." : "");
  renderTools();
  applyDesktopCapabilities(data);
  if($("workspace").open && current) {
    $("process").disabled=Boolean(current.requires && !caps[current.requires]) || unavailableInBackend(current);
    $("upload-limits").textContent=uploadLimits(current);
  }
}).catch(()=>{$("connection").textContent="Sin conexión con el motor. Recarga la página cuando el servidor esté disponible.";});

let signatureDrawing=false, signatureHasInk=false, cameraStream=null, cameraStarting=false;
function clearSignature() {
  const canvas=$("signature-pad");
  canvas.getContext("2d").clearRect(0,0,canvas.width,canvas.height);
  signatureHasInk=false; signatureDrawing=false;
}
function signaturePoint(event) {
  const rect=$("signature-pad").getBoundingClientRect();
  return {x:(event.clientX-rect.left)*600/rect.width,y:(event.clientY-rect.top)*180/rect.height};
}
$("signature-pad").addEventListener("pointerdown",event=>{
  if(busy)return;
  const ctx=$("signature-pad").getContext("2d"),point=signaturePoint(event);
  ctx.beginPath();ctx.moveTo(point.x,point.y);ctx.strokeStyle="#111";ctx.lineWidth=2;ctx.lineCap="round";
  signatureDrawing=true;$("signature-pad").setPointerCapture(event.pointerId);
});
$("signature-pad").addEventListener("pointermove",event=>{
  if(!signatureDrawing || busy)return;
  const ctx=$("signature-pad").getContext("2d"),point=signaturePoint(event);
  ctx.lineTo(point.x,point.y);ctx.stroke();signatureHasInk=true;
});
for(const name of ["pointerup","pointercancel"]) $("signature-pad").addEventListener(name,()=>signatureDrawing=false);
$("signature-clear").addEventListener("click",()=>{if(!busy)clearSignature();});
$("signature-use").addEventListener("click",()=>{
  if(busy)return;
  if(!signatureHasInk){setStatus("Dibuja una firma primero.",true);return;}
  if(files.length!==1 || !files[0].name.toLowerCase().endsWith(".pdf")){setStatus("Selecciona primero un solo PDF; luego usa la firma.",true);return;}
  $("signature-pad").toBlob(blob=>{
    if(!blob || busy || !current || current.id!=="stamp")return;
    addFiles([new File([blob],"firma-visual.png",{type:"image/png"})]);
    setStatus("Firma añadida como segundo archivo. Ajusta sus porcentajes y procesa el PDF.");
  },"image/png");
});
function stopCamera() {
  if(cameraStream) cameraStream.getTracks().forEach(track=>track.stop());
  cameraStream=null;$("camera-video").srcObject=null;
}
function closeCamera() { stopCamera();if($("camera-dialog").open)$("camera-dialog").close(); }
$("camera-close").addEventListener("click",closeCamera);
$("camera-dialog").addEventListener("cancel",event=>{event.preventDefault();closeCamera();});
document.addEventListener("visibilitychange",()=>{if(document.hidden)closeCamera();});
async function captureFile(video,name) {
  if(!video.videoWidth || !video.videoHeight)throw new Error("La fuente de vídeo aún no está lista.");
  const ratio=Math.min(1,2400/Math.max(video.videoWidth,video.videoHeight));
  const canvas=document.createElement("canvas");canvas.width=Math.round(video.videoWidth*ratio);canvas.height=Math.round(video.videoHeight*ratio);
  canvas.getContext("2d").drawImage(video,0,0,canvas.width,canvas.height);
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/jpeg",0.92));
  canvas.width=1;canvas.height=1;
  if(!blob)throw new Error("No se pudo crear la imagen.");
  return new File([blob],name,{type:"image/jpeg"});
}
function captureError(error) {
  const messages={NotAllowedError:"Permiso denegado o captura cancelada. No se tomó ninguna imagen.",
    NotFoundError:"No se encontró una cámara o fuente compatible.",NotReadableError:"El dispositivo está ocupado o no puede utilizarse."};
  $("connection").textContent=messages[error.name] || error.message;
}
$("camera-open").addEventListener("click",async()=>{
  if(cameraStarting)return;
  if(!window.isSecureContext || !navigator.mediaDevices?.getUserMedia){
    $("connection").textContent="Cámara no disponible: usa HTTPS en la LAN o importa una foto desde tu equipo.";return;
  }
  cameraStarting=true;stopCamera();$("camera-status").textContent="Solicitando permiso…";$("camera-shot").disabled=true;$("camera-dialog").showModal();
  try{
    const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:"environment"},width:{ideal:1920},height:{ideal:1080}},audio:false});
    if(!$("camera-dialog").open || document.hidden){stream.getTracks().forEach(track=>track.stop());return;}
    cameraStream=stream;$("camera-video").srcObject=stream;await $("camera-video").play();
    $("camera-status").textContent="Cámara activa. Pulsa Capturar cuando estés listo.";$("camera-shot").disabled=false;
  }catch(error){closeCamera();captureError(error);}
  finally{cameraStarting=false;}
});
$("camera-shot").addEventListener("click",async()=>{
  $("camera-shot").disabled=true;
  try{
    const file=await captureFile($("camera-video"),"captura-camara.jpg");
    closeCamera();openTool(tools.find(tool=>tool.id==="images_to_pdf"));addFiles([file]);
  }catch(error){closeCamera();captureError(error);}
});
$("screen-capture").addEventListener("click",async()=>{
  if(!window.isSecureContext || !navigator.mediaDevices?.getDisplayMedia){
    $("connection").textContent="Captura no disponible: usa HTTPS y un navegador compatible, o importa una captura guardada.";return;
  }
  let stream=null,video=null;
  try{
    stream=await navigator.mediaDevices.getDisplayMedia({video:true,audio:false});
    video=document.createElement("video");video.muted=true;video.srcObject=stream;await video.play();
    const file=await captureFile(video,"captura-pantalla.jpg");
    openTool(tools.find(tool=>tool.id==="images_to_pdf"));addFiles([file]);
  }catch(error){captureError(error);}
  finally{if(stream)stream.getTracks().forEach(track=>track.stop());if(video)video.srcObject=null;}
});

function applyDesktopCapabilities(data) {
  if (!data || !data.scanners || !data.scanners.available) {
    const desc = $("construction-description");
    if (desc) desc.textContent = "No se detectaron controladores de escáner en este equipo. Conecte un escáner WIA o instale su controlador para habilitar estas funciones.";
    return;
  }
  const devicesText = data.scanners.devices && data.scanners.devices.length
    ? data.scanners.devices.join(", ")
    : "Controlador WIA / Image instalado";
  const eyebrow = $("desktop-eyebrow");
  if (eyebrow) eyebrow.innerHTML = '<span></span>MÓDULO LOCAL · DISPOSITIVOS DETECTADOS';
  const notice = $("desktop-notice");
  if (notice) notice.classList.add("active");
  const code = $("desktop-code");
  if (code) code.textContent = "EVA PDF ENTERPRISE / HARDWARE: VINCULADO";
  const heading = $("desktop-heading");
  if (heading) heading.textContent = "Dispositivos Habilitados";
  const desc = $("construction-description");
  if (desc) desc.textContent = `Controlador(es) de escáner detectados: ${devicesText}. Las funciones de escaneo local, cámara para PDF e impresión están activas.`;
  const caption = $("desktop-caption");
  if (caption) caption.textContent = "HARDWARE LOCAL VINCULADO · PROCESAMIENTO PRIVADO";
  const legend = $("desktop-legend");
  if (legend) legend.textContent = "Herramientas de escritorio activas:";
  const actions = $("desktop-actions");
  if (actions) {
    actions.removeAttribute("disabled");
    actions.classList.add("enabled");
    for (const btn of actions.querySelectorAll("button")) {
      btn.removeAttribute("disabled");
    }
  }
  const detectedList = $("desktop-detected-list");
  if (detectedList) detectedList.textContent = `Dispositivos detectados: ${devicesText}`;

  if (!sessionStorage.getItem("eva_desktop_guide_shown")) {
    sessionStorage.setItem("eva_desktop_guide_shown", "1");
    const guide = $("desktop-guide-dialog");
    if (guide && !guide.open) guide.showModal();
  }
}

$("desktop-help")?.addEventListener("click", () => {
  const guide = $("desktop-guide-dialog");
  if (guide && !guide.open) guide.showModal();
});
$("close-desktop-guide")?.addEventListener("click", () => {
  $("desktop-guide-dialog")?.close();
});
$("desktop-guide-ok")?.addEventListener("click", () => {
  $("desktop-guide-dialog")?.close();
});
$("desktop-scan")?.addEventListener("click", async () => {
  try {
    setStatus("Abriendo asistente de escaneo local en Windows...");
    const res = await fetch("/desktop/launch/Scan", {method: "POST"});
    const result = await res.json();
    if (result.ok) {
      setStatus("Diálogo de escaneo abierto en tu equipo. Guarda el escaneo y selecciónalo en Imágenes a PDF.");
    } else if (result.local_only) {
      window.location.href = "/desktop/download";
    } else {
      setStatus(result.error || "No se pudo iniciar el escáner.", true);
    }
  } catch {
    window.location.href = "/desktop/download";
  }
});
$("desktop-print")?.addEventListener("click", async () => {
  try {
    setStatus("Abriendo selector de impresión local...");
    const res = await fetch("/desktop/launch/Print", {method: "POST"});
    const result = await res.json();
    if (result.ok) {
      setStatus("Selector de impresión abierto en Windows.");
    } else if (result.local_only) {
      window.print();
    } else {
      setStatus(result.error || "No se pudo iniciar la impresión.", true);
    }
  } catch {
    window.print();
  }
});
