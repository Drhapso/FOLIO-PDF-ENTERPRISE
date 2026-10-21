"use strict";

// Helper de base de datos IndexedDB para pasar el archivo PDF a una pestaña independiente
const DB_NAME = "FolioAcrobatDB";
const STORE_NAME = "pending_edits";

function saveFileForEditor(file) {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE_NAME);
    req.onsuccess = () => {
      const db = req.result;
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).put(file, "active_pdf");
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    };
    req.onerror = () => reject(req.error);
  });
}

function retrieveFileForEditor() {
  return new Promise((resolve) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE_NAME);
    req.onsuccess = () => {
      const db = req.result;
      const tx = db.transaction(STORE_NAME, "readwrite");
      const getReq = tx.objectStore(STORE_NAME).get("active_pdf");
      getReq.onsuccess = () => {
        const file = getReq.result;
        if (file) {
          // Limpiar inmediatamente para no dejar copias residuales en el navegador (Privacy by Design)
          tx.objectStore(STORE_NAME).delete("active_pdf");
        }
        resolve(file);
      };
      getReq.onerror = () => resolve(null);
    };
    req.onerror = () => resolve(null);
  });
}

window.saveFileForEditor = saveFileForEditor;
window.retrieveFileForEditor = retrieveFileForEditor;

(function() {
  const regionLabels = { highlight: "Resaltado", rectangle: "Rectángulo", note: "Nota", redact: "Censura irreversible" };
  const savedTheme = localStorage.getItem("folio-theme");
  if (savedTheme === "dark" || savedTheme === "light") document.documentElement.dataset.theme = savedTheme;

  // Estado del Editor Acrobat Pro
  const state = {
    processing: false,
    file: null,
    totalPages: 1,
    currentPage: 1,
    pageWidth: 612,
    pageHeight: 792,
    zoom: 1.0,
    activeTool: "edit",
    showOutlines: true,
    pageBlocks: [],     // Bloques originales de la página actual
    background: null,
    allPageBlocks: new Map(), // Historial de bloques por página
    selectedId: null,
    // Cambios persistidos: mapa de clave `${page}_${blockId}` -> objeto de cambio
    changes: new Map(),
    // Bloques nuevos agregados por página: mapa de página -> lista de bloques nuevos
    addedBlocks: new Map(),
    // Bloques eliminados: Set de claves `${page}_${blockId}`
    deletedBlocks: new Set(),
    isDragging: false,
    isResizing: false,
    dragStart: { x: 0, y: 0 },
    initialBox: null,
    currentScale: 1.0,
  };

  const dom = {};

  function initDom() {
    dom.dialog = document.getElementById("acrobat-dialog");
    dom.standalone = document.getElementById("acrobat-container");
    dom.dropPrompt = document.getElementById("acro-drop-prompt");
    dom.promptFile = document.getElementById("acro-prompt-file");
    dom.standaloneFile = document.getElementById("acro-standalone-file");
    dom.viewport = document.getElementById("acro-viewport");
    dom.pageWrapper = document.getElementById("acro-page-wrapper");
    dom.pageImg = document.getElementById("acro-page-img");
    dom.overlay = document.getElementById("acro-overlay");
    dom.regionTool = document.getElementById("acro-region-tool");
    dom.noteText = document.getElementById("acro-note-text");
    dom.regionList = document.getElementById("acro-region-list");
    dom.pageCurrent = document.getElementById("acro-page-num");
    dom.pageTotal = document.getElementById("acro-page-total");
    dom.btnPrev = document.getElementById("acro-prev-page");
    dom.btnNext = document.getElementById("acro-next-page");
    dom.btnToolEdit = document.getElementById("acro-tool-edit");
    dom.btnToolAdd = document.getElementById("acro-tool-add");
    dom.btnToolOutlines = document.getElementById("acro-tool-outlines");
    dom.btnToolFind = document.getElementById("acro-tool-find");
    dom.btnToolDelete = document.getElementById("acro-tool-delete");
    dom.findBar = document.getElementById("acro-find-bar");
    dom.findInput = document.getElementById("acro-find-text");
    dom.replaceInput = document.getElementById("acro-replace-text");
    dom.btnFindNext = document.getElementById("acro-find-next");
    dom.btnReplaceOne = document.getElementById("acro-replace-one");
    dom.btnReplaceAll = document.getElementById("acro-replace-all");
    dom.btnFindClose = document.getElementById("acro-find-close");
    dom.zoomSelect = document.getElementById("acro-zoom-select");
    dom.btnSave = document.getElementById("acro-btn-save");
    dom.btnReturn = document.getElementById("acro-btn-return");
    dom.btnClose = document.getElementById("acro-btn-close");
    dom.statusNotice = document.getElementById("acro-status-notice");
    dom.statusDot = document.getElementById("acro-status-dot");

    // Controles del Panel RHP (Formato Acrobat DC)
    dom.fontName = document.getElementById("acro-font-name");
    dom.fontSize = document.getElementById("acro-font-size");
    dom.btnSizeDec = document.getElementById("acro-size-dec");
    dom.btnSizeInc = document.getElementById("acro-size-inc");
    dom.fontColor = document.getElementById("acro-font-color");
    dom.colorSwatch = document.getElementById("acro-color-swatch");
    dom.btnBold = document.getElementById("acro-btn-bold");
    dom.btnItalic = document.getElementById("acro-btn-italic");
    dom.btnUnderline = document.getElementById("acro-btn-underline");
    dom.btnStrike = document.getElementById("acro-btn-strike");
    dom.btnSuper = document.getElementById("acro-btn-super");
    dom.btnSub = document.getElementById("acro-btn-sub");
    dom.btnAlignLeft = document.getElementById("acro-align-left");
    dom.btnAlignCenter = document.getElementById("acro-align-center");
    dom.btnAlignRight = document.getElementById("acro-align-right");
    dom.btnAlignJustify = document.getElementById("acro-align-justify");
    dom.lineSpacing = document.getElementById("acro-line-spacing");
    dom.btnRotateCCW = document.getElementById("acro-rotate-ccw");
    dom.btnRotateCW = document.getElementById("acro-rotate-cw");
    dom.posX = document.getElementById("acro-pos-x");
    dom.posY = document.getElementById("acro-pos-y");
    dom.posW = document.getElementById("acro-pos-w");
    dom.posH = document.getElementById("acro-pos-h");

    bindEvents();
    if (dom.btnReturn) {
      dom.btnReturn.hidden = !dom.standalone;
      dom.btnReturn.addEventListener("click", () => {
        if (!confirmExit()) return;
        if (!state.file) { setStatusNotice("Selecciona un PDF antes de volver a las herramientas.", true); return; }
        if (!window.saveFileForEditor) { setStatusNotice("No se pudo preparar el PDF para continuar.", true); return; }
        window.saveFileForEditor(state.file).then(() => {
          window.location.href = new URLSearchParams(window.location.search).get("multi") === "1"
            ? "/?resume=1&multi=1" : "/?resume=1";
        }).catch(error => setStatusNotice("No se pudo transferir el PDF: " + error.message, true));
      });
    }
  }

  function bindEvents() {
    if (dom.btnClose) {
      dom.btnClose.addEventListener("click", () => {
        if (confirmExit()) {
          if (dom.dialog) dom.dialog.close();
          else window.location.href = "/";
        }
      });
    }

    if (dom.dialog) {
      dom.dialog.addEventListener("cancel", (e) => {
        e.preventDefault();
        if (confirmExit()) dom.dialog.close();
      });
    }

    // Carga de archivo en modo pestaña independiente
    if (dom.promptFile) {
      dom.promptFile.addEventListener("change", (e) => {
        if (e.target.files && e.target.files[0]) window.openAcrobatEditor(e.target.files[0]);
      });
    }
    if (dom.standaloneFile) {
      dom.standaloneFile.addEventListener("change", (e) => {
        if (e.target.files && e.target.files[0]) window.openAcrobatEditor(e.target.files[0]);
      });
    }

    // Drag and drop en modo pestaña independiente
    window.addEventListener("dragover", (e) => e.preventDefault());
    window.addEventListener("drop", (e) => {
      e.preventDefault();
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        const file = e.dataTransfer.files[0];
        if (file.name.toLowerCase().endsWith(".pdf")) {
          window.openAcrobatEditor(file);
        }
      }
    });

    dom.btnPrev.addEventListener("click", () => {
      if (state.currentPage > 1) loadPage(state.currentPage - 1);
    });

    dom.btnNext.addEventListener("click", () => {
      if (state.currentPage < state.totalPages) loadPage(state.currentPage + 1);
    });

    dom.pageCurrent.addEventListener("change", () => {
      const p = parseInt(dom.pageCurrent.value, 10);
      if (p >= 1 && p <= state.totalPages) loadPage(p);
      else dom.pageCurrent.value = state.currentPage;
    });

    dom.btnToolEdit.addEventListener("click", () => setTool("edit"));
    dom.btnToolAdd.addEventListener("click", () => setTool("add"));
    dom.regionTool.addEventListener("change", () => setTool(dom.regionTool.value || "edit"));
    document.getElementById("acro-region-add").addEventListener("click", () => {
      const [x, y, w, h] = ["x", "y", "w", "h"].map(key => Number(document.getElementById("acro-region-" + key).value) / 100);
      addRegion([x * state.pageWidth, y * state.pageHeight, (x + w) * state.pageWidth, (y + h) * state.pageHeight]);
    });
    let regionStart = null;
    const regionPoint = event => {
      const rect = dom.overlay.getBoundingClientRect();
      return [
        Math.max(0, Math.min(state.pageWidth, (event.clientX - rect.left) / state.currentScale)),
        Math.max(0, Math.min(state.pageHeight, (event.clientY - rect.top) / state.currentScale)),
      ];
    };
    const regionBox = event => {
      const end = regionPoint(event);
      return [Math.min(regionStart[0], end[0]), Math.min(regionStart[1], end[1]),
        Math.max(regionStart[0], end[0]), Math.max(regionStart[1], end[1])];
    };
    dom.overlay.addEventListener("pointerdown", event => {
      if (!regionLabels[state.activeTool] || !state.file || state.processing || event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      deselectBlock();
      regionStart = regionPoint(event);
      dom.overlay.setPointerCapture(event.pointerId);
    }, true);
    dom.overlay.addEventListener("pointermove", event => {
      if (!regionStart) return;
      dom.overlay.querySelector(".acro-region-draft")?.remove();
      renderRegion({ action: state.activeTool, bbox: regionBox(event) }, true);
    });
    dom.overlay.addEventListener("pointerup", event => {
      if (!regionStart) return;
      const bbox = regionBox(event);
      regionStart = null;
      dom.overlay.releasePointerCapture(event.pointerId);
      dom.overlay.querySelector(".acro-region-draft")?.remove();
      addRegion(bbox);
    });
    dom.overlay.addEventListener("pointercancel", () => {
      regionStart = null;
      dom.overlay.querySelector(".acro-region-draft")?.remove();
    });

    dom.btnToolOutlines.addEventListener("click", () => {
      state.showOutlines = !state.showOutlines;
      dom.btnToolOutlines.classList.toggle("active", state.showOutlines);
      dom.overlay.classList.toggle("acro-show-outlines", state.showOutlines);
    });

    dom.btnToolFind.addEventListener("click", () => {
      dom.findBar.hidden = !dom.findBar.hidden;
      dom.btnToolFind.classList.toggle("active", !dom.findBar.hidden);
      if (!dom.findBar.hidden) dom.findInput.focus();
    });

    dom.btnFindClose.addEventListener("click", () => {
      dom.findBar.hidden = true;
      dom.btnToolFind.classList.remove("active");
    });

    dom.btnToolDelete.addEventListener("click", deleteActiveBlock);

    dom.zoomSelect.addEventListener("change", () => {
      const z = dom.zoomSelect.value;
      if (z === "fit-page") {
        const availableHeight = dom.viewport.clientHeight - 60;
        state.zoom = Math.min(1.5, Math.max(0.4, availableHeight / state.pageHeight));
      } else if (z === "fit-width") {
        const availableWidth = dom.viewport.clientWidth - 80;
        state.zoom = Math.min(2.0, Math.max(0.4, availableWidth / state.pageWidth));
      } else {
        state.zoom = parseFloat(z);
      }
      applyZoom();
    });

    // Clic sobre el lienzo para agregar texto o deseleccionar
    dom.overlay.addEventListener("click", (e) => {
      if (state.activeTool === "add" && e.target === dom.overlay) {
        const rect = dom.overlay.getBoundingClientRect();
        const ptX = (e.clientX - rect.left) / state.currentScale;
        const ptY = (e.clientY - rect.top) / state.currentScale;
        addNewBlock(ptX, ptY);
        setTool("edit");
      } else if (e.target === dom.overlay) {
        deselectBlock();
      }
    });

    // Guardar cambios
    dom.btnSave.addEventListener("click", saveChanges);

    // Controles RHP de Formato
    dom.fontName.addEventListener("change", () => updateActiveFormat("font", dom.fontName.value));
    dom.fontSize.addEventListener("change", () => updateActiveFormat("size", parseFloat(dom.fontSize.value)));
    dom.btnSizeInc.addEventListener("click", () => {
      const cur = parseFloat(dom.fontSize.value) || 12;
      dom.fontSize.value = cur + 1;
      updateActiveFormat("size", cur + 1);
    });
    dom.btnSizeDec.addEventListener("click", () => {
      const cur = parseFloat(dom.fontSize.value) || 12;
      if (cur > 6) {
        dom.fontSize.value = cur - 1;
        updateActiveFormat("size", cur - 1);
      }
    });

    dom.fontColor.addEventListener("input", () => {
      dom.colorSwatch.style.backgroundColor = dom.fontColor.value;
      updateActiveFormat("color", dom.fontColor.value);
    });

    document.querySelectorAll(".acro-mini-swatch").forEach(sw => {
      sw.addEventListener("click", () => {
        const c = sw.dataset.color;
        dom.fontColor.value = c;
        dom.colorSwatch.style.backgroundColor = c;
        updateActiveFormat("color", c);
      });
    });

    dom.btnBold.addEventListener("click", () => {
      const active = !dom.btnBold.classList.contains("active");
      dom.btnBold.classList.toggle("active", active);
      updateActiveFormat("bold", active);
    });

    dom.btnItalic.addEventListener("click", () => {
      const active = !dom.btnItalic.classList.contains("active");
      dom.btnItalic.classList.toggle("active", active);
      updateActiveFormat("italic", active);
    });

    dom.btnUnderline.addEventListener("click", () => {
      const active = !dom.btnUnderline.classList.contains("active");
      dom.btnUnderline.classList.toggle("active", active);
      updateActiveFormat("underline", active);
    });

    [dom.btnAlignLeft, dom.btnAlignCenter, dom.btnAlignRight, dom.btnAlignJustify].forEach(btn => {
      btn.addEventListener("click", () => {
        [dom.btnAlignLeft, dom.btnAlignCenter, dom.btnAlignRight, dom.btnAlignJustify].forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        updateActiveFormat("align", btn.dataset.align);
      });
    });

    dom.lineSpacing.addEventListener("change", () => updateActiveFormat("line_spacing", parseFloat(dom.lineSpacing.value)));
    dom.btnRotateCW.addEventListener("click", () => rotateActiveBlock(90));
    dom.btnRotateCCW.addEventListener("click", () => rotateActiveBlock(-90));

    // Buscar y reemplazar
    dom.btnFindNext.addEventListener("click", findNext);
    dom.btnReplaceOne.addEventListener("click", replaceCurrent);
    dom.btnReplaceAll.addEventListener("click", replaceAll);

    // Teclas de acceso rápido estilo Acrobat
    window.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        dom.findBar.hidden = false;
        dom.btnToolFind.classList.add("active");
        dom.findInput.focus();
      }
      if (e.key === "Escape") {
        if (!dom.findBar.hidden) {
          dom.findBar.hidden = true;
          dom.btnToolFind.classList.remove("active");
        } else {
          deselectBlock();
        }
      }
    });
  }

  function confirmExit() {
    const totalChanges = state.changes.size + state.deletedBlocks.size + getAddedCount();
    if (totalChanges > 0) {
      return confirm(`Tienes ${totalChanges} cambios sin guardar. ¿Deseas descartarlos y salir?`);
    }
    return true;
  }

  function getAddedCount() {
    let c = 0;
    state.addedBlocks.forEach(list => c += list.length);
    return c;
  }

  function setTool(toolName) {
    if (regionLabels[toolName]) deselectBlock();
    state.activeTool = toolName;
    dom.btnToolEdit.classList.toggle("active", toolName === "edit");
    dom.btnToolAdd.classList.toggle("active", toolName === "add");
    dom.regionTool.value = regionLabels[toolName] ? toolName : "";
    dom.overlay.classList.toggle("acro-region-mode", Boolean(regionLabels[toolName]));
    dom.overlay.style.cursor = toolName === "add" || regionLabels[toolName] ? "crosshair" : "default";
  }

  function applyZoom() {
    state.currentScale = state.zoom;
    dom.pageWrapper.style.width = (state.pageWidth * state.currentScale) + "px";
    dom.pageWrapper.style.height = (state.pageHeight * state.currentScale) + "px";
    refreshBlockPositions();
  }

  // Inicialización y carga de documento
  window.openAcrobatEditor = async function(file) {
    if (!dom.viewport) initDom();
    state.file = file;
    state.currentPage = 1;
    state.changes.clear();
    state.addedBlocks.clear();
    state.deletedBlocks.clear();
    state.allPageBlocks.clear();
    state.selectedId = null;
    state.zoom = 1.0;
    dom.zoomSelect.value = "1.0";
    dom.findBar.hidden = true;
    dom.btnToolFind.classList.remove("active");
    dom.btnToolOutlines.classList.add("active");
    dom.overlay.classList.add("acro-show-outlines");
    if (dom.btnSave) dom.btnSave.disabled = false;
    if (dom.dropPrompt) dom.dropPrompt.hidden = true;
    const requestedTool = new URLSearchParams(window.location.search).get("tool");
    setTool(regionLabels[requestedTool] ? requestedTool : "edit");
    updateStatus();

    if (dom.dialog && !dom.dialog.open) dom.dialog.showModal();
    await loadPage(1);
  };

  async function loadPage(pageNum) {
    if (state.processing) return;
    state.processing = true;
    if (dom.standalone) dom.standalone.inert = true;
    deselectBlock();
    state.currentPage = pageNum;
    dom.pageCurrent.value = pageNum;
    dom.btnPrev.disabled = pageNum <= 1;
    dom.btnNext.disabled = pageNum >= state.totalPages;
    dom.overlay.replaceChildren();

    setStatusNotice("Analizando página y extrayendo bloques de texto estilo Acrobat DC…");

    try {
      const form = new FormData();
      form.append("files", state.file);
      // Inspección a 130 DPI para nitidez visual de maquetación
      form.append("options", JSON.stringify({ page: pageNum, dpi: 130, text_background: true }));

      const res = await window.folioProcess("inspect", form);

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "Error al inspeccionar la página." }));
        throw new Error(err.error);
      }

      const data = await res.json();
      displayPage(data);
    } catch (err) {
      setStatusNotice("Error: " + err.message, true);
    } finally {
      state.processing = false;
      if (dom.standalone) dom.standalone.inert = false;
    }
  }

  function displayPage(data) {
    const pageNum = data.page;
    state.currentPage = pageNum;
    dom.pageCurrent.value = pageNum;
    state.totalPages = data.pages;
    state.pageWidth = data.width;
    state.pageHeight = data.height;
    dom.pageTotal.textContent = data.pages;
    dom.pageCurrent.max = data.pages;
    dom.btnPrev.disabled = pageNum <= 1;
    dom.btnNext.disabled = pageNum >= state.totalPages;

    // Renderizar la imagen de fondo de la página
    if (!data.background) throw new Error("El motor no devolvió el fondo de edición. Reinicia el servidor y recarga la página.");
    state.background = "data:image/png;base64," + data.background;
    dom.pageImg.src = `data:${data.image_mime || "image/jpeg"};base64,` + data.image;
    applyZoom();

    // Guardar y renderizar bloques detectados
    state.pageBlocks = data.blocks || [];
    state.allPageBlocks.set(pageNum, state.pageBlocks);
    renderPageBlocks();

    setStatusNotice(data.scan_notice || (state.pageBlocks.length
      ? `Página ${pageNum}: ${state.pageBlocks.length} fragmentos editables. Fuentes compatibles; revisa la vista final al guardar.`
      : `Página ${pageNum}: sin texto horizontal editable.`));
  }

  function renderPageBlocks() {
    dom.overlay.replaceChildren();

    // 1. Bloques originales
    state.pageBlocks.forEach(block => {
      if (block.editable === false) {
        const blocked = document.createElement("div");
        blocked.className = "acro-scan-blocked";
        blocked.title = block.reason;
        updateElementGeometry(blocked, block.bbox);
        blocked.addEventListener("click", event => {
          event.stopPropagation();
          setStatusNotice(block.reason, true);
        });
        dom.overlay.appendChild(blocked);
        return;
      }
      const key = `${state.currentPage}_${block.id}`;
      createOrigMaskElement(block.bbox, block.id);
      if (state.deletedBlocks.has(key)) {
        createDeletedBlockElement(block.id, block.bbox);
        return;
      }

      const change = state.changes.get(key);
      const isModified = Boolean(change);
      const bbox = change?.bbox || block.bbox;
      const text = change?.text !== undefined ? change.text : block.text;
      const font = change?.font || block.font;
      const size = change?.size || block.size;
      const color = change?.color || block.color;
      const bold = change?.bold !== undefined ? change.bold : block.bold;
      const italic = change?.italic !== undefined ? change.italic : block.italic;
      const align = change?.align || "left";

      createBlockElement(block.id, bbox, text, font, size, color, bold, italic, align, false, isModified);
    });

    // 2. Bloques nuevos agregados en esta página
    const addedList = state.addedBlocks.get(state.currentPage) || [];
    addedList.forEach(block => {
      if (regionLabels[block.action]) renderRegion(block);
      else createBlockElement(block.id, block.bbox, block.text, block.font, block.size, block.color, block.bold, block.italic, block.align, true, true);
    });
    renderRegionList();
  }

  function addRegion(bbox) {
    if (!state.file || state.processing || !regionLabels[state.activeTool]) {
      setStatusNotice("Abre un PDF y elige una herramienta de zona.", true);
      return;
    }
    const [x0, y0, x1, y1] = bbox;
    if (!bbox.every(Number.isFinite) || x0 < 0 || y0 < 0 || x1 > state.pageWidth || y1 > state.pageHeight || x1 - x0 < 1 || y1 - y0 < 1) {
      setStatusNotice("La zona debe tener al menos un punto de ancho y alto y quedar dentro de la página.", true);
      return;
    }
    const text = dom.noteText.value.trim();
    if (state.activeTool === "note" && !text) {
      setStatusNotice("Escribe el contenido de la nota antes de seleccionar la zona.", true);
      return;
    }
    if (!state.addedBlocks.has(state.currentPage)) state.addedBlocks.set(state.currentPage, []);
    state.addedBlocks.get(state.currentPage).push({
      id: "region_" + Date.now() + "_" + getAddedCount(), action: state.activeTool, page: state.currentPage, bbox, text,
    });
    renderPageBlocks();
    updateStatus();
  }

  function renderRegion(region, draft = false) {
    const el = document.createElement("div");
    el.className = `acro-region acro-region-${region.action}` + (draft ? " acro-region-draft" : "");
    updateRegionGeometry(el, region.bbox);
    dom.overlay.appendChild(el);
  }

  function updateRegionGeometry(el, bbox) {
    updateElementGeometry(el, bbox);
    el.style.width = ((bbox[2] - bbox[0]) * state.currentScale) + "px";
    el.style.height = ((bbox[3] - bbox[1]) * state.currentScale) + "px";
  }

  function renderRegionList() {
    dom.regionList.replaceChildren();
    for (const region of state.addedBlocks.get(state.currentPage) || []) {
      if (!regionLabels[region.action]) continue;
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = regionLabels[region.action] + (region.action === "note" ? ": " + region.text : "");
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Quitar";
      remove.addEventListener("click", () => deleteBlock(region.id, true));
      li.append(label, remove);
      dom.regionList.appendChild(li);
    }
  }

  function createOrigMaskElement(bbox, id) {
    const el = document.createElement("div");
    el.className = "acro-orig-mask";
    el.dataset.maskFor = id;
    updateElementGeometry(el, bbox);
    updateBackgroundMask(el);
    dom.overlay.appendChild(el);
  }

  function updateBackgroundMask(el) {
    const key = `${state.currentPage}_${el.dataset.maskFor}`;
    el.hidden = !state.changes.has(key) && !state.deletedBlocks.has(key);
    const [x0, y0, x1, y1] = JSON.parse(el.dataset.bbox);
    const scale = state.currentScale;
    el.style.width = ((x1 - x0) * scale) + "px";
    el.style.height = ((y1 - y0) * scale) + "px";
    el.style.backgroundImage = `url("${state.background}")`;
    el.style.backgroundSize = `${state.pageWidth * scale}px ${state.pageHeight * scale}px`;
    el.style.backgroundPosition = `${-x0 * scale}px ${-y0 * scale}px`;
  }

  function createDeletedBlockElement(id, bbox) {
    const key = `${state.currentPage}_${id}`;
    const el = document.createElement("div");
    el.className = "acro-block deleted";
    el.id = `block-${id}`;
    updateElementGeometry(el, bbox);
    const badge = document.createElement("span");
    badge.className = "acro-deleted-badge";
    badge.title = "Clic para restaurar bloque eliminado";
    badge.innerHTML = "Eliminado ↶";
    badge.style.cursor = "pointer";
    badge.style.pointerEvents = "auto";
    badge.addEventListener("click", (e) => {
      e.stopPropagation();
      state.deletedBlocks.delete(key);
      renderPageBlocks();
      updateStatus();
    });
    el.appendChild(badge);
    dom.overlay.appendChild(el);
  }

  function createBlockElement(id, bbox, text, font, size, color, bold, italic, align, isNew, isModified = false) {
    const el = document.createElement("div");
    el.className = "acro-block" + (isNew ? " is-new" : "") + (isModified ? " modified" : "");
    el.id = `block-${id}`;
    el.dataset.blockId = id;
    el.dataset.isNew = isNew ? "true" : "false";
    el.dataset.fontSize = size;

    // Posición en pantalla según escala
    updateElementGeometry(el, bbox);

    // Barra superior de movimiento
    const toolbar = document.createElement("div");
    toolbar.className = "acro-block-toolbar";
    toolbar.innerHTML = `<span>✥ Mover</span><button type="button" title="Eliminar bloque" class="acro-del-btn">✕</button>`;
    toolbar.querySelector(".acro-del-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteBlock(id, isNew);
    });

    // Iniciador de arrastre (drag)
    toolbar.addEventListener("mousedown", (e) => {
      e.stopPropagation();
      startDrag(e, el, id, isNew);
    });

    // Puntos de control de redimensionamiento (Resize Handles)
    ["nw", "n", "ne", "e", "se", "s", "sw", "w"].forEach(pos => {
      const handle = document.createElement("div");
      handle.className = `acro-handle ${pos}`;
      handle.addEventListener("mousedown", (e) => {
        e.stopPropagation();
        startResize(e, el, id, isNew, pos);
      });
      el.appendChild(handle);
    });

    // Editor de texto in-situ
    const textarea = document.createElement("textarea");
    textarea.className = "acro-block-editor";
    textarea.value = text;
    textarea.spellcheck = false;
    applyStylesToTextarea(textarea, font, size, color, bold, italic, align);

    textarea.addEventListener("input", () => {
      el.classList.add("modified");
      autoFitTextarea(textarea, el);
      recordChange(id, isNew, { text: textarea.value });
    });

    textarea.addEventListener("focus", () => selectBlock(id, isNew, el));
    textarea.addEventListener("mousedown", () => selectBlock(id, isNew, el));

    el.addEventListener("click", (e) => {
      e.stopPropagation();
      selectBlock(id, isNew, el);
    });

    el.appendChild(toolbar);
    el.appendChild(textarea);
    dom.overlay.appendChild(el);
  }

  function updateElementGeometry(el, bbox) {
    const [x0, y0, x1, y1] = bbox;
    const scale = state.currentScale;
    el.style.left = (x0 * scale) + "px";
    el.style.top = (y0 * scale) + "px";
    el.style.width = Math.max(30, (x1 - x0) * scale) + "px";
    el.style.height = Math.max(16, (y1 - y0) * scale) + "px";
    el.dataset.bbox = JSON.stringify(bbox);
    if (el.dataset.maskFor) updateBackgroundMask(el);
  }

  function applyStylesToTextarea(textarea, font, size, color, bold, italic, align) {
    textarea.style.fontFamily = `"${font}", Arial, sans-serif`;
    textarea.style.fontSize = (size * state.currentScale) + "px";
    textarea.style.color = color;
    textarea.style.fontWeight = bold ? "bold" : "normal";
    textarea.style.fontStyle = italic ? "italic" : "normal";
    textarea.style.textAlign = align || "left";
  }

  function autoFitTextarea(textarea, el) {
    if (textarea.scrollHeight > textarea.clientHeight) {
      const extra = (textarea.scrollHeight - textarea.clientHeight) / state.currentScale;
      const bbox = JSON.parse(el.dataset.bbox);
      bbox[3] += extra + 6;
      updateElementGeometry(el, bbox);
      recordChange(el.dataset.blockId, el.dataset.isNew === "true", { bbox: bbox });
    }
  }

  function refreshBlockPositions() {
    dom.overlay.querySelectorAll(".acro-block").forEach(el => {
      const bbox = JSON.parse(el.dataset.bbox);
      updateElementGeometry(el, bbox);
      const textarea = el.querySelector(".acro-block-editor");
      if (textarea) {
        const blkSize = parseFloat(el.dataset.fontSize) || parseFloat(dom.fontSize.value) || 12;
        textarea.style.fontSize = (blkSize * state.currentScale) + "px";
      }
    });
    dom.overlay.querySelectorAll(".acro-orig-mask").forEach(el => {
      if (el.dataset.bbox) {
        const bbox = JSON.parse(el.dataset.bbox);
        updateElementGeometry(el, bbox);
      }
    });
    dom.overlay.querySelectorAll(".acro-region, .acro-scan-blocked").forEach(el => updateRegionGeometry(el, JSON.parse(el.dataset.bbox)));
  }

  function selectBlock(id, isNew, el) {
    if (state.selectedId === id) return;
    deselectBlock();
    state.selectedId = id;
    el.classList.add("selected");

    const textarea = el.querySelector(".acro-block-editor");
    if (textarea && document.activeElement !== textarea) {
      textarea.focus();
    }

    const bbox = JSON.parse(el.dataset.bbox);
    const key = `${state.currentPage}_${id}`;
    let info = null;

    if (isNew) {
      const list = state.addedBlocks.get(state.currentPage) || [];
      info = list.find(b => b.id === id);
    } else {
      const pageList = state.allPageBlocks.get(state.currentPage) || state.pageBlocks;
      const orig = pageList.find(b => b.id === id);
      const mod = state.changes.get(key) || {};
      info = { ...orig, ...mod };
    }

    if (info) {
      dom.fontName.value = info.font || "Arial";
      dom.fontSize.value = Math.round(info.size || 12);
      dom.fontColor.value = info.color || "#000000";
      dom.colorSwatch.style.backgroundColor = info.color || "#000000";
      dom.btnBold.classList.toggle("active", Boolean(info.bold));
      dom.btnItalic.classList.toggle("active", Boolean(info.italic));
      dom.btnUnderline.classList.toggle("active", Boolean(info.underline));

      [dom.btnAlignLeft, dom.btnAlignCenter, dom.btnAlignRight, dom.btnAlignJustify].forEach(b => {
        b.classList.toggle("active", b.dataset.align === (info.align || "left"));
      });

      dom.posX.value = Math.round(bbox[0]);
      dom.posY.value = Math.round(bbox[1]);
      dom.posW.value = Math.round(bbox[2] - bbox[0]);
      dom.posH.value = Math.round(bbox[3] - bbox[1]);
    }
  }

  function deselectBlock() {
    if (state.selectedId) {
      const prev = document.getElementById(`block-${state.selectedId}`);
      if (prev) prev.classList.remove("selected");
      state.selectedId = null;
    }
  }

  function updateActiveFormat(prop, value) {
    if (!state.selectedId) return;
    const el = document.getElementById(`block-${state.selectedId}`);
    if (!el) return;
    const isNew = el.dataset.isNew === "true";
    const textarea = el.querySelector(".acro-block-editor");

    const update = { [prop]: value };
    recordChange(state.selectedId, isNew, update);

    // Actualizar visualmente el bloque en vivo
    if (prop === "font") textarea.style.fontFamily = `"${value}", Arial, sans-serif`;
    if (prop === "size") {
      el.dataset.fontSize = value;
      textarea.style.fontSize = (value * state.currentScale) + "px";
    }
    if (prop === "color") textarea.style.color = value;
    if (prop === "bold") textarea.style.fontWeight = value ? "bold" : "normal";
    if (prop === "italic") textarea.style.fontStyle = value ? "italic" : "normal";
    if (prop === "align") textarea.style.textAlign = value;
  }

  function recordChange(id, isNew, data) {
    const key = `${state.currentPage}_${id}`;
    if (isNew) {
      const list = state.addedBlocks.get(state.currentPage) || [];
      const item = list.find(b => b.id === id);
      if (item) Object.assign(item, data);
    } else {
      const pageList = state.allPageBlocks.get(state.currentPage) || state.pageBlocks;
      const orig = pageList.find(b => b.id === id);
      const existing = state.changes.get(key) || {
        action: "modify",
        page: state.currentPage,
        orig_bbox: orig ? orig.bbox : null,
        source: orig?.source,
        bbox: orig ? orig.bbox : null,
        text: orig ? orig.text : "",
        font: orig ? orig.font : "Arial",
        size: orig ? orig.size : 12,
        color: orig ? orig.color : "#000000",
        bold: orig ? orig.bold : false,
        italic: orig ? orig.italic : false,
        align: "left",
      };
      Object.assign(existing, data);
      state.changes.set(key, existing);
    }
    const el = document.getElementById(`block-${id}`);
    if (el) el.classList.add("modified");
    dom.overlay.querySelectorAll(".acro-orig-mask").forEach(updateBackgroundMask);
    updateStatus();
  }

  function addNewBlock(ptX, ptY) {
    const id = "add_" + Date.now();
    const w = 220;
    const h = 45;
    const bbox = [ptX, ptY, ptX + w, ptY + h];

    const blockData = {
      id: id,
      action: "add",
      page: state.currentPage,
      bbox: bbox,
      text: "Escribe tu texto aquí…",
      font: dom.fontName.value || "Arial",
      size: parseFloat(dom.fontSize.value) || 12,
      color: dom.fontColor.value || "#000000",
      bold: dom.btnBold.classList.contains("active"),
      italic: dom.btnItalic.classList.contains("active"),
      underline: dom.btnUnderline.classList.contains("active"),
      align: "left",
      line_spacing: 1.15,
      rotation: 0,
    };

    if (!state.addedBlocks.has(state.currentPage)) {
      state.addedBlocks.set(state.currentPage, []);
    }
    state.addedBlocks.get(state.currentPage).push(blockData);

    createBlockElement(id, bbox, blockData.text, blockData.font, blockData.size, blockData.color, blockData.bold, blockData.italic, blockData.align, true);
    const newEl = document.getElementById(`block-${id}`);
    selectBlock(id, true, newEl);
    const textarea = newEl.querySelector(".acro-block-editor");
    textarea.focus();
    textarea.select();
    updateStatus();
  }

  function deleteBlock(id, isNew) {
    const key = `${state.currentPage}_${id}`;
    if (isNew) {
      const list = state.addedBlocks.get(state.currentPage) || [];
      const idx = list.findIndex(b => b.id === id);
      if (idx !== -1) list.splice(idx, 1);
    } else {
      state.changes.delete(key);
      state.deletedBlocks.add(key);
    }
    deselectBlock();
    renderPageBlocks();
    updateStatus();
  }

  function deleteActiveBlock() {
    if (!state.selectedId) return;
    const el = document.getElementById(`block-${state.selectedId}`);
    if (el) deleteBlock(state.selectedId, el.dataset.isNew === "true");
  }

  function rotateActiveBlock(deg) {
    if (!state.selectedId) return;
    const el = document.getElementById(`block-${state.selectedId}`);
    if (!el) return;
    const isNew = el.dataset.isNew === "true";
    const key = `${state.currentPage}_${state.selectedId}`;
    const curRot = isNew
      ? (state.addedBlocks.get(state.currentPage)?.find(b => b.id === state.selectedId)?.rotation || 0)
      : (state.changes.get(key)?.rotation || 0);

    const nextRot = (curRot + deg) % 360;
    recordChange(state.selectedId, isNew, { rotation: nextRot });
    el.style.transform = `rotate(${nextRot}deg)`;
  }

  // Lógica de Arrastre (Drag)
  function startDrag(e, el, id, isNew) {
    state.isDragging = true;
    state.dragStart = { x: e.clientX, y: e.clientY };
    state.initialBox = JSON.parse(el.dataset.bbox);

    const onMouseMove = (ev) => {
      if (!state.isDragging) return;
      const dx = (ev.clientX - state.dragStart.x) / state.currentScale;
      const dy = (ev.clientY - state.dragStart.y) / state.currentScale;
      const [x0, y0, x1, y1] = state.initialBox;
      const w = x1 - x0;
      const h = y1 - y0;
      const newX0 = Math.max(0, Math.min(state.pageWidth - w, x0 + dx));
      const newY0 = Math.max(0, Math.min(state.pageHeight - h, y0 + dy));
      const newBbox = [newX0, newY0, newX0 + w, newY0 + h];

      updateElementGeometry(el, newBbox);
      dom.posX.value = Math.round(newX0);
      dom.posY.value = Math.round(newY0);
    };

    const onMouseUp = () => {
      state.isDragging = false;
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      recordChange(id, isNew, { bbox: JSON.parse(el.dataset.bbox) });
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }

  // Lógica de Redimensionamiento (Resize)
  function startResize(e, el, id, isNew, handlePos) {
    state.isResizing = true;
    state.dragStart = { x: e.clientX, y: e.clientY };
    state.initialBox = JSON.parse(el.dataset.bbox);

    const onMouseMove = (ev) => {
      if (!state.isResizing) return;
      const dx = (ev.clientX - state.dragStart.x) / state.currentScale;
      const dy = (ev.clientY - state.dragStart.y) / state.currentScale;
      let [x0, y0, x1, y1] = [...state.initialBox];

      if (handlePos.includes("e")) x1 = Math.max(x0 + 30, x1 + dx);
      if (handlePos.includes("s")) y1 = Math.max(y0 + 16, y1 + dy);
      if (handlePos.includes("w")) x0 = Math.min(x1 - 30, x0 + dx);
      if (handlePos.includes("n")) y0 = Math.min(y1 - 16, y0 + dy);

      const newBbox = [x0, y0, x1, y1];
      updateElementGeometry(el, newBbox);
      dom.posW.value = Math.round(x1 - x0);
      dom.posH.value = Math.round(y1 - y0);
    };

    const onMouseUp = () => {
      state.isResizing = false;
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      recordChange(id, isNew, { bbox: JSON.parse(el.dataset.bbox) });
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }

  // Buscar y Reemplazar
  let currentFindMatches = [];
  let currentMatchIdx = -1;

  function findNext() {
    const q = dom.findInput.value.trim();
    if (!q) return;

    currentFindMatches = [];
    dom.overlay.querySelectorAll(".acro-block").forEach(el => {
      const textarea = el.querySelector(".acro-block-editor");
      if (textarea && textarea.value.toLowerCase().includes(q.toLowerCase())) {
        currentFindMatches.push(el);
      }
    });

    if (currentFindMatches.length === 0) {
      setStatusNotice(`No se encontraron coincidencias para "${q}".`);
      return;
    }

    currentMatchIdx = (currentMatchIdx + 1) % currentFindMatches.length;
    const target = currentFindMatches[currentMatchIdx];
    selectBlock(target.dataset.blockId, target.dataset.isNew === "true", target);
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    setStatusNotice(`Coincidencia ${currentMatchIdx + 1} de ${currentFindMatches.length}.`);
  }

  function replaceCurrent() {
    if (!state.selectedId) {
      findNext();
      return;
    }
    const el = document.getElementById(`block-${state.selectedId}`);
    if (!el) return;
    const textarea = el.querySelector(".acro-block-editor");
    const q = dom.findInput.value;
    const rep = dom.replaceInput.value;
    if (q && textarea.value.toLowerCase().includes(q.toLowerCase())) {
      const regex = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
      textarea.value = textarea.value.replace(regex, rep);
      recordChange(state.selectedId, el.dataset.isNew === "true", { text: textarea.value });
      setStatusNotice(`Texto reemplazado en el bloque.`);
      findNext();
    }
  }

  function replaceAll() {
    const q = dom.findInput.value.trim();
    const rep = dom.replaceInput.value;
    if (!q) return;

    let count = 0;
    dom.overlay.querySelectorAll(".acro-block").forEach(el => {
      const textarea = el.querySelector(".acro-block-editor");
      if (textarea && textarea.value.toLowerCase().includes(q.toLowerCase())) {
        const regex = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
        textarea.value = textarea.value.replace(regex, rep);
        recordChange(el.dataset.blockId, el.dataset.isNew === "true", { text: textarea.value });
        count++;
      }
    });
    setStatusNotice(`Se reemplazaron coincidencias en ${count} bloques de esta página.`);
  }

  function updateStatus() {
    const total = state.changes.size + state.deletedBlocks.size + getAddedCount();
    if (dom.statusNotice) {
      dom.statusNotice.textContent = total === 0 ? "Listo. Selecciona cualquier bloque de texto para editarlo." : `${total} ${total === 1 ? "modificación pendiente" : "modificaciones pendientes"}.`;
    }
    if (dom.statusDot) {
      dom.statusDot.classList.toggle("dirty", total > 0);
    }
  }

  function setStatusNotice(text, isError = false) {
    if (dom.statusNotice) {
      dom.statusNotice.textContent = text;
      dom.statusNotice.style.color = isError ? "var(--error)" : "";
    }
  }

  // Guardar todas las modificaciones y descargar el PDF procesado
  async function saveChanges() {
    if (state.processing) return;
    const payloadChanges = [];

    // 1. Modificaciones
    state.changes.forEach((val) => {
      payloadChanges.push(val);
    });

    // 2. Eliminaciones
    state.deletedBlocks.forEach((key) => {
      const separator = key.indexOf("_");
      const pStr = key.slice(0, separator);
      const blockId = key.slice(separator + 1);
      const p = parseInt(pStr, 10);
      const pageList = state.allPageBlocks.get(p) || state.pageBlocks;
      const orig = pageList.find(b => b.id === blockId);
      if (orig) {
        payloadChanges.push({
          action: "delete",
          page: p,
          orig_bbox: orig.bbox,
          source: orig.source,
        });
      }
    });

    // 3. Bloques nuevos
    state.addedBlocks.forEach((list) => {
      list.forEach(b => payloadChanges.push(b));
    });

    if (payloadChanges.length === 0) {
      alert("No hay modificaciones pendientes para guardar.");
      return;
    }
    if (payloadChanges.some(change => change.action === "redact")
        && !confirm("La censura eliminará contenido de las zonas seleccionadas y los adjuntos del PDF. No se puede deshacer en el archivo guardado. ¿Continuar?")) return;
    if (payloadChanges.some(change => change.source === "scan")
        && !confirm("Se reconstruirá la imagen solo en las palabras escaneadas seleccionadas. El OCR y la reconstrucción pueden tener errores. Revisa la vista previa y el PDF guardado. ¿Continuar?")) return;

    dom.btnSave.disabled = true;
    state.processing = true;
    if (dom.standalone) dom.standalone.inert = true;
    setStatusNotice("Procesando modificaciones vectoriales…");

    try {
      const form = new FormData();
      form.append("files", state.file);
      form.append("options", JSON.stringify({
        changes: payloadChanges, editor_preview: true, page: state.currentPage,
        experimental_preview: new URLSearchParams(window.location.search).get("multi") === "1",
      }));

      const res = await window.folioProcess("edit_text_pro", form);

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "Error en el servidor al guardar el PDF." }));
        throw new Error(err.error);
      }

      if (!["complete", "on-delivery"].includes(res.headers.get("X-PDF-Cleanup"))) {
        throw new Error("El servidor no confirmó la eliminación temporal.");
      }
      const result = await res.formData();
      const blob = result.get("document");
      const preview = result.get("preview");
      if (!(blob instanceof Blob) || blob.type !== "application/pdf" || !(preview instanceof Blob)) {
        throw new Error("El motor no devolvió el PDF y la vista de edición esperados. Actualiza el servidor.");
      }
      const pageData = JSON.parse(await preview.text());
      if (!pageData.background || !Array.isArray(pageData.blocks)) {
        throw new Error("El motor devolvió una vista de edición incompleta.");
      }
      const downloadUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = downloadUrl;
      const baseName = state.file.name.replace(/\.[^/.]+$/, "");
      a.download = `${baseName}_editado_acrobat.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(downloadUrl), 5000);

      setStatusNotice("¡Documento procesado y descargado con éxito!");
      // Limpiar cambios guardados
      state.changes.clear();
      state.addedBlocks.clear();
      state.deletedBlocks.clear();
      state.file = new File([blob], state.file.name, { type: "application/pdf" });
      state.allPageBlocks.clear();
      deselectBlock();
      dom.overlay.replaceChildren();
      displayPage(pageData);
      updateStatus();
      setStatusNotice("Cambios guardados y PDF descargado. Listo para continuar editando.");
    } catch (err) {
      setStatusNotice("Error al guardar: " + err.message, true);
    } finally {
      state.processing = false;
      if (dom.standalone) dom.standalone.inert = false;
      dom.btnSave.disabled = false;
    }
  }

  // Comprobar automáticamente si se abrió en una pestaña independiente (/editor)
  document.addEventListener("DOMContentLoaded", async () => {
    if (!document.getElementById("acrobat-container") && !document.getElementById("acrobat-dialog")) return;
    initDom();
    if (dom.standalone) {
      // Página independiente /editor
      const pendingFile = await retrieveFileForEditor();
      if (pendingFile) {
        if (!state.file) window.openAcrobatEditor(pendingFile);
      } else if (!state.file) {
        if (dom.dropPrompt) dom.dropPrompt.hidden = false;
        setStatusNotice("Arrastra un archivo PDF o pulsa en Seleccionar para abrirlo en el editor.");
      }
    }
  });

})();
