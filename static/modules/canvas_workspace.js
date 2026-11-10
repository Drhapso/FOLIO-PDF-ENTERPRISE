"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const theme = localStorage.getItem("folio-theme");
  if (theme === "dark" || theme === "light") document.documentElement.dataset.theme = theme;
  $("theme")?.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("folio-theme", next);
  });

  const NS = "http://www.w3.org/2000/svg";
  const state = {
    files: [],
    nodes: [],
    edges: [],
    panX: 40,
    panY: 40,
    zoom: 1,
    connectMode: false,
    connectSource: null,
  };
  let downloadUrl = null;
  let wasmWorker = null;

  fetch("/api/capabilities")
    .then((r) => (r.ok ? r.json() : null))
    .then((caps) => {
      if (caps?.addons?.wasm_pdfium) {
        $("canvas-render-mode").textContent = "PDFium-Wasm Listo";
        try {
          wasmWorker = new Worker("/static/modules/canvas_worker.js");
          wasmWorker.postMessage({ id: 1, action: "ping" });
        } catch {
          wasmWorker = null;
        }
      } else {
        $("canvas-render-mode").textContent = "Render JS Local";
      }
    })
    .catch(() => {});

  function setStatus(msg, kind = "") {
    const bar = $("canvas-status");
    bar.textContent = msg;
    bar.className = "v2-status-bar" + (kind ? " " + kind : "");
  }

  function applyWorldTransform() {
    $("canvas-world").style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
    $("canvas-zoom-label").textContent = `${Math.round(state.zoom * 100)}%`;
  }

  function renderEdges() {
    const svg = $("canvas-edges");
    svg.replaceChildren();
    for (const edge of state.edges) {
      const n1 = state.nodes.find((n) => n.id === edge.from);
      const n2 = state.nodes.find((n) => n.id === edge.to);
      if (!n1 || !n2) continue;
      const line = document.createElementNS(NS, "line");
      line.setAttribute("x1", String(n1.x + 130));
      line.setAttribute("y1", String(n1.y + 70));
      line.setAttribute("x2", String(n2.x + 130));
      line.setAttribute("y2", String(n2.y + 70));
      line.setAttribute("stroke", "#6259aa");
      line.setAttribute("stroke-width", "2.5");
      line.setAttribute("stroke-dasharray", "6 4");
      svg.append(line);
    }
  }

  function renderNodes() {
    const world = $("canvas-world");
    const svg = $("canvas-edges");
    world.replaceChildren(svg);
    for (const node of state.nodes) {
      const card = document.createElement("article");
      card.className = "canvas-node";
      if (node.drifted) card.classList.add("drifted");
      if (state.connectSource === node.id) card.classList.add("selected");
      card.style.left = `${node.x}px`;
      card.style.top = `${node.y}px`;

      const head = document.createElement("div");
      head.className = "canvas-node-head";
      const titleSpan = document.createElement("span");
      titleSpan.textContent = node.title;
      const closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.textContent = "×";
      closeBtn.className = "secondary";
      closeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        state.nodes = state.nodes.filter((x) => x.id !== node.id);
        state.edges = state.edges.filter((ed) => ed.from !== node.id && ed.to !== node.id);
        renderNodes();
      });
      head.append(titleSpan, closeBtn);
      card.append(head);

      if (node.thumb) {
        const img = document.createElement("img");
        img.className = "canvas-thumb";
        img.src = "data:image/jpeg;base64," + node.thumb;
        img.alt = node.title;
        card.append(img);
      }

      const body = document.createElement("div");
      body.className = "canvas-node-body";
      body.textContent = node.text || "(Sin texto)";
      card.append(body);

      card.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!state.connectMode) return;
        if (!state.connectSource) {
          state.connectSource = node.id;
          setStatus(`Origen "${node.title}" elegido. Haz clic en otro nodo destino.`);
          renderNodes();
        } else if (state.connectSource !== node.id) {
          state.edges.push({ from: state.connectSource, to: node.id });
          state.connectSource = null;
          state.connectMode = false;
          $("canvas-connect-mode").textContent = "Conectar 2 nodos";
          setStatus("Enlace semántico trazado entre nodos.", "ok");
          renderNodes();
        }
      });

      let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
      card.addEventListener("pointerdown", (e) => {
        if (e.target.tagName === "BUTTON") return;
        e.stopPropagation();
        dragging = true;
        sx = e.clientX;
        sy = e.clientY;
        ox = node.x;
        oy = node.y;
        card.setPointerCapture(e.pointerId);
      });
      card.addEventListener("pointermove", (e) => {
        if (!dragging) return;
        node.x = Math.round(ox + (e.clientX - sx) / state.zoom);
        node.y = Math.round(oy + (e.clientY - sy) / state.zoom);
        card.style.left = `${node.x}px`;
        card.style.top = `${node.y}px`;
        renderEdges();
      });
      card.addEventListener("pointerup", () => { dragging = false; });

      world.append(card);
    }
    renderEdges();
  }

  // Panning en etapa infinita
  let panning = false, px0 = 0, py0 = 0, startPanX = 0, startPanY = 0;
  $("canvas-stage").addEventListener("pointerdown", (e) => {
    if (e.target !== $("canvas-stage") && e.target !== $("canvas-world")) return;
    panning = true;
    px0 = e.clientX;
    py0 = e.clientY;
    startPanX = state.panX;
    startPanY = state.panY;
    $("canvas-stage").classList.add("panning");
  });
  window.addEventListener("pointermove", (e) => {
    if (!panning) return;
    state.panX = startPanX + (e.clientX - px0);
    state.panY = startPanY + (e.clientY - py0);
    applyWorldTransform();
  });
  window.addEventListener("pointerup", () => {
    panning = false;
    $("canvas-stage").classList.remove("panning");
  });

  $("canvas-zoom-in")?.addEventListener("click", () => {
    state.zoom = Math.min(2.2, +(state.zoom + 0.15).toFixed(2));
    applyWorldTransform();
  });
  $("canvas-zoom-out")?.addEventListener("click", () => {
    state.zoom = Math.max(0.35, +(state.zoom - 0.15).toFixed(2));
    applyWorldTransform();
  });
  $("canvas-zoom-reset")?.addEventListener("click", () => {
    state.zoom = 1; state.panX = 40; state.panY = 40;
    applyWorldTransform();
  });

  $("canvas-pdfs")?.addEventListener("change", (e) => {
    state.files = Array.from(e.target.files || []);
    const sel = $("canvas-doc-select");
    sel.replaceChildren();
    state.files.forEach((f, i) => {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = `${i + 1}. ${f.name}`;
      sel.append(opt);
    });
    if (state.files.length) setStatus(`${state.files.length} archivo(s) listos en tablero.`);
  });

  $("canvas-pin-page")?.addEventListener("click", async () => {
    const pdfs = state.files.filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    const dIdx = Number($("canvas-doc-select").value || 0);
    const file = state.files[dIdx];
    const pno = Math.max(1, Number($("canvas-page-input").value || 1));
    if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
      return setStatus("Selecciona un PDF válido en el panel izquierdo.", "error");
    }
    const form = new FormData();
    form.append("files", file);
    form.append("options", JSON.stringify({ page: pno, dpi: 90 }));
    try {
      setStatus("Renderizando página para tablero Canvas...");
      const res = await window.folioProcess("inspect", form);
      const data = await res.json();
      const snippet = (data.blocks || []).map((b) => b.text).join(" ").slice(0, 260);
      const docPos = pdfs.indexOf(file);
      state.nodes.push({
        id: `node_${Date.now()}_${state.nodes.length}`,
        kind: "page",
        doc_index: docPos >= 0 ? docPos : 0,
        page: data.page,
        title: `${file.name} · Pág. ${data.page}`,
        text: snippet,
        thumb: data.image,
        x: 60 + (state.nodes.length % 4) * 290,
        y: 60 + Math.floor(state.nodes.length / 4) * 260,
        drifted: false,
      });
      renderNodes();
      setStatus(`Página ${data.page} fijada al Canvas.`, "ok");
    } catch (err) {
      setStatus(err.message || "No se pudo fijar la página.", "error");
    }
  });

  $("canvas-add-note")?.addEventListener("click", () => {
    const txt = window.prompt("Contenido de la nota libre en el Canvas:", "Hallazgo clave...");
    if (!txt) return;
    state.nodes.push({
      id: `note_${Date.now()}`,
      kind: "note",
      title: "Nota Analítica",
      text: txt,
      x: 100 + (state.nodes.length % 3) * 280,
      y: 90 + Math.floor(state.nodes.length / 3) * 180,
    });
    renderNodes();
  });

  $("canvas-connect-mode")?.addEventListener("click", () => {
    state.connectMode = !state.connectMode;
    state.connectSource = null;
    $("canvas-connect-mode").textContent = state.connectMode ? "Cancelar enlace" : "Conectar 2 nodos";
    setStatus(state.connectMode ? "Haz clic en el nodo origen." : "Modo enlace desactivado.");
    renderNodes();
  });

  $("canvas-sync-btn")?.addEventListener("click", async () => {
    const pdfs = state.files.filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    const pageNodes = state.nodes.filter((n) => n.kind === "page");
    if (!pdfs.length || !pageNodes.length) {
      return setStatus("Carga PDFs y fija al menos una página antes de sincronizar.", "error");
    }
    const form = new FormData();
    pdfs.forEach((f) => form.append("files", f));
    form.append("options", JSON.stringify({
      extracts: pageNodes.map((n) => ({
        id: n.id,
        doc_index: n.doc_index || 0,
        page: n.page || 1,
        expected_sha256: n.sha256 || "",
      })),
    }));
    try {
      setStatus("Sincronizando extractos con PDFs actuales...");
      const res = await window.folioProcess("canvas_extract_sync", form);
      const data = await res.json();
      let updatedCount = 0;
      for (const synced of data.extracts || []) {
        const node = state.nodes.find((n) => n.id === synced.id);
        if (!node) continue;
        if (synced.status === "updated") {
          node.drifted = true;
          updatedCount += 1;
        }
        node.sha256 = synced.sha256;
        if (synced.text) node.text = synced.text.slice(0, 260);
      }
      renderNodes();
      setStatus(`Sincronización completa: ${updatedCount} extracto(s) modificados.`, "ok");
    } catch (err) {
      setStatus(err.message || "Error al sincronizar.", "error");
    }
  });

  $("canvas-export-board")?.addEventListener("click", () => {
    const payload = {
      format: "EVA-BOARD-V1",
      nodes: state.nodes.map(({ thumb, ...rest }) => rest),
      edges: state.edges,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    if (downloadUrl) URL.revokeObjectURL(downloadUrl);
    downloadUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = "tablero.evaboard";
    a.click();
    setStatus("Tablero .evaboard exportado en tu equipo.", "ok");
  });

  $("canvas-import-board")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      state.nodes = Array.isArray(data.nodes) ? data.nodes : [];
      state.edges = Array.isArray(data.edges) ? data.edges : [];
      renderNodes();
      setStatus(`Tablero cargado (${state.nodes.length} nodos). Sube los PDFs y pulsa Sincronizar.`, "ok");
    } catch {
      setStatus("Archivo .evaboard inválido.", "error");
    }
  });

  async function runCanvasBundle(op, fileFilter) {
    const list = state.files.filter(fileFilter);
    if (!list.length) return setStatus("Carga primero los archivos requeridos.", "error");
    const form = new FormData();
    list.forEach((f) => form.append("files", f));
    form.append("options", JSON.stringify({}));
    try {
      setStatus("Generando paquete en motor local...");
      const res = await window.folioProcess(op, form);
      const notice = res.headers.get("X-PDF-Notice") || "Listo.";
      const blob = await res.blob();
      if (downloadUrl) URL.revokeObjectURL(downloadUrl);
      downloadUrl = URL.createObjectURL(blob);
      const link = $("canvas-download-link");
      link.href = downloadUrl;
      link.download = "EVA00.zip";
      $("canvas-download").hidden = false;
      setStatus(notice, "ok");
    } catch (err) {
      setStatus(err.message || "Error al ejecutar análisis.", "error");
    }
  }

  $("canvas-research-link")?.addEventListener("click", () => {
    runCanvasBundle("research_link", (f) => /\.(pdf|bib)$/i.test(f.name));
  });
  $("canvas-compare-v1v2")?.addEventListener("click", () => {
    const pdfs = state.files.filter((f) => /\.pdf$/i.test(f.name));
    if (pdfs.length !== 2) return setStatus("Carga exactamente 2 PDFs (V1 y V2) para comparar.", "error");
    runCanvasBundle("compare_semantic", (f) => /\.pdf$/i.test(f.name));
  });

  applyWorldTransform();
})();
