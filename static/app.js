"use strict";
const BUILD = document.querySelector('meta[name="client-build"]').content;
const $ = (id) => document.getElementById(id);
const tools = [
  {id:"merge",name:"Unir PDF",icon:"⊕",category:"organize",desc:"Varios documentos, un solo PDF. En el orden que tú elijas.",multiple:true},
  {id:"split",name:"Dividir PDF",icon:"⊟",category:"organize",desc:"Separa páginas o crea grupos para descargar en un ZIP."},
  {id:"organize",name:"Organizar páginas",icon:"▤",category:"organize",desc:"Reordena, extrae y elimina páginas con una sola selección."},
  {id:"rotate",name:"Rotar PDF",icon:"↻",category:"organize",desc:"Pon cada página en su posición. Gira 90°, 180° o 270°."},
  {id:"compress",name:"Comprimir PDF",icon:"↙",category:"optimize",desc:"Menos peso, más facilidad para compartir. Elige el nivel."},
  {id:"ocr",name:"Reconocer texto · OCR",icon:"A",category:"optimize",desc:"Convierte escaneos en PDF con texto que puedes buscar.",requires:"ocr"},
  {id:"office_to_pdf",name:"Office a PDF",icon:"W",category:"convert",desc:"Convierte Word, Excel, PowerPoint y OpenDocument.",requires:"office",accept:".docx,.xlsx,.pptx,.odt,.ods,.odp"},
  {id:"pdf_to_docx",name:"PDF a Word",icon:"W",category:"convert",desc:"Recupera texto en un documento Word editable.",warning:"Extrae texto por líneas; no reconstruye el diseño exacto de Acrobat. Las páginas escaneadas se incluyen como imagen; usa OCR primero para extraer su texto."},
  {id:"pdf_to_xlsx",name:"PDF a Excel",icon:"X",category:"convert",desc:"Extrae tablas detectadas a un libro de cálculo.",warning:"Las tablas se detectan automáticamente y requieren revisión. Si no hay tablas se extrae texto por línea; no se inventan datos de páginas escaneadas."},
  {id:"pdf_to_pptx",name:"PDF a PowerPoint",icon:"P",category:"convert",desc:"Una página, una diapositiva. Conserva su aspecto.",warning:"Cada página se convierte en una imagen dentro de la diapositiva. Los textos y gráficos no son objetos editables."},
  {id:"images_to_pdf",name:"Imágenes a PDF",icon:"▧",category:"convert",desc:"Reúne fotos e imágenes, incluidas HEIC/HEIF, en un PDF.",multiple:true,accept:".png,.jpg,.jpeg,.tif,.tiff,.webp,.bmp,.heic,.heif"},
  {id:"pdf_to_images",name:"PDF a imágenes",icon:"▣",category:"convert",desc:"Exporta tus páginas como imágenes PNG en un ZIP."},
  {id:"extract_text",name:"Extraer texto",icon:"T",category:"convert",desc:"Llévate el contenido de tu PDF a un archivo de texto."},
  {id:"edit",name:"Editar PDF",icon:"✎",category:"edit",desc:"Reconoce y edita todo el texto, fuentes, párrafos y diseño del archivo en una pestaña independiente al estilo Adobe Acrobat DC.",standaloneTab:true},
  {id:"watermark",name:"Marca de agua",icon:"◈",category:"edit",desc:"Añade una marca de texto sobre las páginas que elijas."},
  {id:"protect",name:"Proteger PDF",icon:"⌑",category:"edit",desc:"Controla su apertura con una contraseña y cifrado AES-256."},
  {id:"unlock",name:"Desbloquear PDF",icon:"⌕",category:"edit",desc:"Retira la contraseña de un PDF que te pertenece.",warning:"Necesitas conocer la contraseña actual. Esta herramienta no recupera ni adivina contraseñas."},
  {id:"extract_pages",name:"Extraer páginas",icon:"▤",category:"organize",desc:"Descarga únicamente las páginas que necesitas."},
  {id:"delete_pages",name:"Eliminar páginas",icon:"−",category:"organize",desc:"Elimina una selección explícita; conserva las demás."},
  {id:"number_pages",name:"Numerar páginas",icon:"123",category:"edit",desc:"Añade números arriba o abajo, con inicio configurable."},
  {id:"extract_images",name:"Extraer imágenes",icon:"▧",category:"convert",desc:"Recupera imágenes incrustadas, no capturas de páginas."},
  {id:"crop",name:"Recortar PDF",icon:"⌗",category:"edit",desc:"Ajusta la región visible usando porcentajes de la página.",warning:"Recorte visual: lo oculto puede seguir en el archivo. Para eliminar información usa Censurar PDF."},
  {id:"resize",name:"Cambiar tamaño",icon:"↔",category:"organize",desc:"Ajusta páginas a A4, carta u oficio conservando proporciones.",warning:"Conserva apariencia vectorial, no formularios, anotaciones ni enlaces interactivos."},
  {id:"nup",name:"Varias páginas por hoja",icon:"▦",category:"organize",desc:"Prepara 2 o 4 páginas por hoja para imprimir.",warning:"No conserva formularios, anotaciones ni enlaces interactivos."},
  {id:"overlay",name:"Superponer PDF",icon:"▱",category:"edit",desc:"Aplica un membrete o plantilla sobre un documento.",multiple:true,warning:"Primero el documento, luego la plantilla PDF. La plantilla debe tener una página o igual cantidad de páginas que el documento."},
  {id:"compare",name:"Comparar PDF",icon:"≠",category:"organize",desc:"Informe, diferencias de texto y mapas visuales en un ZIP.",multiple:true,warning:"Selecciona exactamente dos PDF. Compara apariencia a 96 DPI y texto extraído; no certifica equivalencia ni firmas."},
  {id:"stamp",name:"Firma visual e imágenes",icon:"✍",category:"edit",desc:"Dibuja tu firma o inserta una imagen de firma, sello o logo.",multiple:true,accept:".pdf,.png,.jpg,.jpeg",warning:"Primero el PDF y después una imagen PNG/JPEG. Es una firma visual, no firma digital con certificado. Las coordenadas son porcentajes; quite antes cualquier rotación."},
  {id:"annotate",operation:"edit",name:"Anotar PDF",icon:"✎",category:"edit",desc:"Resalta zonas, dibuja rectángulos y agrega notas.",warning:"Carga la vista previa y dibuja una caja. Notas y resaltados se guardan como anotaciones PDF."},
  {id:"redact",operation:"edit",name:"Censurar PDF",icon:"■",category:"edit",desc:"Elimina contenido de zonas seleccionadas con tachado real.",warning:"Revisa todas las páginas, anotaciones y datos sensibles antes de compartir. No es un saneamiento forense automático."},
  {id:"remove_metadata",name:"Eliminar metadatos",icon:"ⓘ",category:"edit",desc:"Limpia autor, título y metadatos Info/XMP del documento.",warning:"No elimina adjuntos, comentarios, texto ni datos personales dentro del contenido."},
  {id:"grayscale",name:"Escala de grises",icon:"◐",category:"optimize",desc:"Crea una copia monocromática rasterizada.",warning:"Pierde texto seleccionable, estructura accesible, enlaces y campos interactivos."},
  {id:"rasterize",name:"Rasterizar PDF",icon:"▦",category:"convert",desc:"Convierte las páginas en imágenes dentro de un nuevo PDF.",warning:"Pierde texto seleccionable, estructura accesible, enlaces y campos interactivos."},
  {id:"flatten",name:"Aplanar PDF",icon:"▰",category:"edit",desc:"Integra visualmente anotaciones y campos de formulario.",warning:"Verifica que todos los campos y anotaciones mantengan su apariencia."},
  {id:"repair",name:"Reparar estructura",icon:"⚒",category:"optimize",desc:"Recupera y reescribe estructuras PDF que qpdf pueda leer.",warning:"No recupera contenido perdido ni certifica integridad visual. Si persisten errores estructurales se rechaza."},
  {id:"web_optimize",name:"Optimizar para web",icon:"↗",category:"optimize",desc:"Linealiza el PDF para permitir lectura progresiva.",warning:"No garantiza menor tamaño ni cambia la política de borrado de Folio."},
  {id:"blank_report",name:"Detectar páginas en blanco",icon:"□",category:"organize",desc:"Genera una lista JSON de candidatas para revisión.",warning:"Heurística conservadora: verifica visualmente sellos, firmas tenues y páginas escaneadas antes de eliminar."},
  {id:"remove_blank",name:"Eliminar blancos revisados",icon:"⊟",category:"organize",desc:"Elimina páginas confirmadas que pasan la comprobación de blanco.",warning:"Primero usa Detectar páginas en blanco. Indica explícitamente los números revisados; nunca se eliminan todas las páginas."},
  {id:"form_fields",name:"Consultar formulario",icon:"☷",category:"edit",desc:"Descarga nombres, tipos y valores de campos AcroForm.",warning:"No admite formularios XFA. El informe puede contener datos sensibles: se descarga a tu equipo."},
  {id:"fill_form",name:"Rellenar formulario",icon:"☑",category:"edit",desc:"Completa campos AcroForm por sus nombres.",warning:"Consulta primero los nombres de campos. No ejecuta JavaScript ni firma certificados; no admite XFA ni botones radio."},
  {id:"dossier",name:"Armar expediente",icon:"▣",category:"organize",desc:"Reúne anexos PDF en el orden elegido, con portada opcional.",multiple:true},
  {id:"html_to_pdf",name:"HTML local a PDF",icon:"<>",category:"convert",desc:"Extrae el texto de un archivo HTML UTF-8 sin conexiones externas.",accept:".html,.htm",warning:"Conversión de texto, no captura de una página web: ignora diseño, CSS, imágenes y scripts. Máximo 2 MB. No acepta URLs."},
  {id:"pdf_to_svg",name:"PDF a SVG",icon:"◇",category:"convert",desc:"Exporta páginas como gráficos SVG con texto convertido en trazados."},
  {id:"heic_to_jpg",name:"HEIC a JPEG",icon:"▧",category:"convert",desc:"Convierte una foto HEIC o HEIF de un fotograma a JPEG.",accept:".heic,.heif",warning:"JPEG con pérdida. No conserva HDR ni metadatos originales; máximo de píxeles igual que las demás imágenes."},
  {id:"epub_to_pdf",name:"EPUB a PDF",icon:"E",category:"convert",desc:"Convierte un libro EPUB sin DRM a páginas A4.",accept:".epub",warning:"Refluye el libro; revisa imágenes, tipografía y saltos. No elimina DRM ni conserva interactividad."},
  {id:"pdf_to_epub",name:"PDF a EPUB de texto",icon:"E",category:"convert",desc:"Crea un libro de texto con una sección por página.",warning:"Solo texto extraíble, sin reconstruir diseño, tablas ni imágenes. Usa OCR primero si es un escaneo."},
  {id:"verify_signatures",name:"Comprobar firmas · offline",icon:"✓",category:"edit",desc:"Informe de integridad criptográfica y cobertura de firmas PDF.",warning:"No certifica identidad, confianza, revocación ni validez legal. Sin consultas OCSP/CRL/TSA. Revisa cobertura y cambios: una firma correcta puede cubrir una versión anterior. No admite PDF cifrados ni crea firmas."},
];
// Herramientas por lote: tantos PDF como quepan en la cuota de peso; cada uno se procesa por separado.
const BATCH_TOOLS=new Set(["split","compress","pdf_to_images","extract_text","pdf_to_docx","pdf_to_xlsx","pdf_to_pptx","pdf_to_svg","extract_images","pdf_to_epub"]);
const BULK_TOOLS=new Set([...BATCH_TOOLS,"merge","images_to_pdf","dossier"]);
const SESSION_TOOL_IDS=new Set([
  "edit","organize","rotate","compress","ocr","watermark","protect","unlock","extract_pages","delete_pages",
  "number_pages","crop","resize","nup","annotate","redact","remove_metadata","grayscale","rasterize",
  "flatten","repair","web_optimize","remove_blank","fill_form",
]);
const MULTI_EDIT_START={id:"multi_edit",name:"Edición múltiple",icon:"✎",category:"edit",
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
const theme = localStorage.getItem("folio-theme");
if (theme === "dark" || theme === "light") document.documentElement.dataset.theme = theme;
$("theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("folio-theme", next);
});
function normalized(value) { return value.normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase(); }
function renderTools() {
  const query = normalized($("search").value);
  $("tool-grid").replaceChildren();
  const visible = tools.filter(t => (activeCategory === "all" || t.category === activeCategory) && normalized(t.name+" "+t.desc).includes(query));
  for (const tool of visible) {
    const card = document.createElement("button");
    card.className = "tool-card"; card.dataset.category = tool.category;
    const icon = document.createElement("span"); icon.className="tool-icon"; icon.textContent=tool.icon; icon.setAttribute("aria-hidden","true");
    const title = document.createElement("h3"); title.textContent=tool.name;
    const desc = document.createElement("p"); desc.textContent=tool.desc;
    const arrow = document.createElement("span"); arrow.className="card-arrow"; arrow.textContent="↗"; arrow.setAttribute("aria-hidden","true");
    card.append(icon, title, desc, arrow);
    if (caps && tool.requires && !caps[tool.requires]) {
      const badge = document.createElement("span"); badge.className="badge"; badge.textContent="MOTOR PENDIENTE"; card.append(badge);
    }
    card.addEventListener("click", () => openTool(tool));
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
  if(!window.saveFileForEditor) {
    throw new Error("No se pudo preparar el PDF para el editor.");
  }
  window.saveFileForEditor(file).then(()=>{
    window.location.href="/editor?session=1";
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
  openTool(editTool);
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
  const missing=caps && tool.requires && !caps[tool.requires];
  $("tool-warning").hidden=!tool.warning && !missing;
  $("tool-warning").textContent=missing ? "Este motor aún no está disponible. Contacta al administrador para completar su instalación local." : (tool.warning || "");
  $("files").accept=tool.accept || ".pdf"; $("files").multiple=Boolean(tool.multiple && !keepSessionFile);
  $("upload-limits").textContent=uploadLimits(tool);
  if (!["multi_edit","images_to_pdf","office_to_pdf","html_to_pdf","heic_to_jpg","epub_to_pdf","verify_signatures"].includes(tool.id)) field("password","Contraseña actual (si el PDF tiene)",{type:"password"});
  if (["organize","rotate","pdf_to_images","extract_text","watermark","pdf_to_docx","pdf_to_xlsx","pdf_to_pptx"].includes(tool.id))
    field("pages",tool.id === "organize" ? "Páginas en el orden deseado" : "Páginas a procesar",{placeholder:"Ej. 1,3,5-8",hint:tool.id === "organize" ? "Las páginas omitidas se eliminan. Puedes invertir rangos: 5-1." : "Vacío: todas las páginas."});
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
  $("editor").hidden=!(tool.operation==="edit" || tool.id==="crop");
  document.querySelector(".editor-controls").hidden=tool.id==="crop";
  document.querySelector("#editor > .hint").textContent=tool.id==="crop"?
    "Carga la vista y dibuja la zona que deseas conservar. Sus porcentajes se aplicarán a las páginas seleccionadas. El contenido oculto no se elimina; revisa el recorte en páginas de distinto tamaño.":
    "Carga la vista y dibuja una caja sobre la página. El tachado elimina contenido; resaltados y notas son anotaciones. Revisa todo el documento antes de compartir.";
  $("edit-kind").value=tool.id==="redact"?"redact":tool.id==="annotate"?"highlight":"text";
  $("signature-editor").hidden=tool.id!=="stamp";
  clearSignature();
  if(tool.id==="edit" || tool.standaloneTab) {
    const tabBtn=document.createElement("button");
    tabBtn.type="button";
    tabBtn.className="primary";
    tabBtn.style.cssText="width:100%; margin:8px 0 14px 0; padding:12px; font-weight:600; text-align:center; cursor:pointer;";
    tabBtn.textContent="Abrir editor en pestaña aparte ↗";
    tabBtn.addEventListener("click", () => {
      try {
        if(sessionActive && files[0]) openTextEditorSession(files[0]);
        else { closeWorkspace(); window.open("/editor", "_blank"); }
      } catch(error) { setStatus(error.message,true); }
    });
    $("options").append(tabBtn);
    $("process").textContent="Abrir en pestaña de edición →";
  } else {
    $("process").innerHTML='Procesar documento <span aria-hidden="true">→</span>';
  }
  $("process").disabled=Boolean(missing) || !caps;
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
    closeWorkspace();
    const newTab = window.open("/editor", "_blank");
    if(window.saveFileForEditor) {
      window.saveFileForEditor(target).then(() => {
        if(newTab) newTab.focus();
      });
    }
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
  if(current.id==="edit" || current.operation==="edit") result.edits=edits;
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
  return `${scope}${usage} · ${tool.accept || "PDF"} · ${pages} · motor: máximo ${budget} s`;
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
  const response=await fetch("/api/process/"+operation,{method:"POST",body:form,headers:{"X-PDF-Client":BUILD},signal});
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
    $("process").disabled=!caps || Boolean(current.requires && !caps[current.requires]); renderFiles();
  }
  renderSessionTools();
  if(value) $("process").textContent="Procesando…";
  else if(current?.id==="edit" || current?.standaloneTab) $("process").textContent="Abrir en pestaña de edición →";
  else $("process").innerHTML='Procesar documento <span aria-hidden="true">→</span>';
}
$("process-form").addEventListener("submit",async event=>{
  event.preventDefault(); if(busy)return;
  if(current?.id==="multi_edit") return;
  if(!sessionActive) clearResult();
  try{
    if(current.id==="edit" || current.standaloneTab) {
        if(sessionActive && files[0]) {
          openTextEditorSession(files[0]);
          return;
        }
        if(files.length > 0) {
        const target = files[0];
        closeWorkspace();
        const newTab = window.open("/editor", "_blank");
        if(window.saveFileForEditor) {
          window.saveFileForEditor(target).then(() => {
            if(newTab) newTab.focus();
          });
        }
        return;
      } else {
        closeWorkspace();
        window.open("/editor", "_blank");
        return;
      }
    }
    validateFiles();
    if(current.id==="merge" && files.length<2) throw new Error("Selecciona al menos dos PDF.");
    if(current.operation==="edit" && !edits.length) throw new Error("Añade al menos una edición en la vista previa.");
    if(["overlay","compare","stamp"].includes(current.id) && files.length!==2) throw new Error("Selecciona exactamente dos archivos en el orden indicado.");
    const payload=options();
    setBusy(true); setStatus("Procesando localmente. No cierres esta pestaña…");
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
    if(edit.kind==="text"){ctx.fillStyle="#121812";ctx.font=`${(edit.size||14)*1.25}px sans-serif`;ctx.textAlign="left";ctx.fillText(edit.text || "",x*canvas.width+3,y*canvas.height+(edit.size||14)*1.4,w*canvas.width-6);}
  }
  $("page-label").textContent=`Página ${pageNumber} de ${pageCount}`;
}
function point(event) {const rect=$("preview").getBoundingClientRect();return{x:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y:Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))};}
function makeEdit(box) {return {...box,kind:$("edit-kind").value,page:pageNumber,text:$("edit-text").value,size:Number($("edit-size").value)};}
function appendEdit(box) {
  if(busy || !previewImage || previewFile!==files[0]) {setStatus("Carga la vista previa primero.",true);return;}
  const edit=makeEdit(box);
  if(current.id==="crop") {
    if(!Object.values(box).every(Number.isFinite) || box.w<=0 || box.h<=0 || box.x<0 || box.y<0 || box.x+box.w>1.001 || box.y+box.h>1.001){setStatus("La caja debe quedar dentro de la página.",true);return;}
    for(const [key,value] of Object.entries({x:box.x,y:box.y,width:box.w,height:box.h})) $("option-"+key).value=(value*100).toFixed(2);
    edits=[{...edit,kind:"highlight"}];clearResult();drawPreview();setStatus("Zona de recorte elegida. Procesa para aplicarla a la selección de páginas.");return;
  }
  if(["text","note"].includes(edit.kind) && !edit.text.trim()) {setStatus("Escribe el texto antes de dibujar una caja.",true);return;}
  if(!Object.values(box).every(Number.isFinite) || box.w<=0 || box.h<=0 || box.x<0 || box.y<0 || box.x+box.w>1.001 || box.y+box.h>1.001){setStatus("La caja debe quedar dentro de la página.",true);return;}
  if(edits.length>=100){setStatus("Máximo 100 ediciones por documento.",true);return;}
  edits.push(edit);clearResult();renderEdits();drawPreview();setStatus("Edición añadida. Procesa el documento para aplicarla.");
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
    const labels={redact:"tachado irreversible",highlight:"resaltado",rectangle:"rectángulo",note:"nota: "+edit.text,text:"texto: "+edit.text};
    span.className="file-name";span.textContent=`Pág. ${edit.page}: ${labels[edit.kind]}`;
    remove.type="button";remove.textContent="Quitar";remove.addEventListener("click",()=>{if(busy)return;edits.splice(index,1);clearResult();renderEdits();drawPreview();});
    li.append(span,remove);$("edit-list").append(li);
  });
}
window.addEventListener("pagehide",()=>{clearResult();files=[];edits=[];previewImage=null;previewFile=null;stopCamera();clearSignature();});
renderTools();
fetch("/api/capabilities").then(response=>{if(!response.ok)throw new Error();return response.json();}).then(data=>{
  caps=data; const engines=[data.office?"Office listo":"Office pendiente",data.ocr?"OCR español/inglés listo":"OCR pendiente"];
  $("connection").textContent=`Motor local conectado · ${engines.join(" · ")} · ${limitLabel(data.max_upload_mb)} por sesión`;
  renderTools();
  if($("workspace").open && current) {
    $("process").disabled=Boolean(current.requires && !caps[current.requires]);
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
