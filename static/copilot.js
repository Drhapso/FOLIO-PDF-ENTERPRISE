"use strict";

(function () {
  const BUILD = document.querySelector('meta[name="client-build"]')?.content || "";
  const FLOATING_SCROLL_THRESHOLD_PX = 140;
  const FIXED_OPTION_HIDDEN_EDGE_PX = 8;

  let activeFile = null;

  function normalizeText(str) {
    return String(str || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function initCopilot() {
    const input = document.getElementById("copilot-input");
    const sendBtn = document.getElementById("copilot-send");
    const feed = document.getElementById("copilot-feed");
    const dropzone = document.getElementById("copilot-dropzone");
    const fileInput = document.getElementById("copilot-file-input");
    const fileLoaded = document.getElementById("copilot-file-loaded");
    const dropContent = document.getElementById("copilot-drop-content");
    const loadedName = document.getElementById("copilot-loaded-name");
    const loadedMeta = document.getElementById("copilot-loaded-meta");
    const btnSummarize = document.getElementById("copilot-btn-summarize");
    const btnRemoveFile = document.getElementById("copilot-btn-remove-file");

    // Elementos del botón flotante fijo + panel integrado
    const fabShell = document.getElementById("copilot-fab-shell");
    const fabBtn = document.getElementById("copilot-fab-btn");
    const fabPanel = document.getElementById("copilot-fab-panel");
    const fabClose = document.getElementById("copilot-fab-close");
    const fabFileBadge = document.getElementById("copilot-fab-file-badge");
    const fabTabs = Array.from(document.querySelectorAll(".copilot-fab-tab"));
    const fabViewSearch = document.getElementById("copilot-fab-view-search");
    const fabViewAi = document.getElementById("copilot-fab-view-ai");
    const fabToolInput = document.getElementById("copilot-fab-tool-input");
    const fabToolClear = document.getElementById("copilot-fab-tool-clear");
    const fabCatBtns = Array.from(document.querySelectorAll(".copilot-fab-cat"));
    const fabResultsCount = document.getElementById("copilot-fab-results-count");
    const fabAskAiBtn = document.getElementById("copilot-fab-ask-ai");
    const fabResults = document.getElementById("copilot-fab-results");
    const fabAiInput = document.getElementById("copilot-fab-ai-input");
    const fabAiSend = document.getElementById("copilot-fab-ai-send");
    const fabAiFeed = document.getElementById("copilot-fab-ai-feed");
    const fabFileInput = document.getElementById("copilot-fab-file-input");
    const fabFileLabel = document.getElementById("copilot-fab-file-label");
    const fabFileName = document.getElementById("copilot-fab-file-name");
    const fabFileSummarize = document.getElementById("copilot-fab-file-summarize");
    const fabFileRemove = document.getElementById("copilot-fab-file-remove");
    const fabScrollTop = document.getElementById("copilot-fab-scroll-top");

    if (!input || !sendBtn) return;

    let fabPanelOpen = false;
    let fabActiveTab = "search";
    let fabCategory = "all";
    let fabVisibleTools = [];
    let fabHighlightedIndex = -1;

    function syncFileUi() {
      if (activeFile) {
        const sizeMb = (activeFile.size / (1024 * 1024)).toFixed(2);
        if (dropContent) dropContent.hidden = true;
        if (fileLoaded) fileLoaded.hidden = false;
        if (loadedName) loadedName.textContent = activeFile.name;
        if (loadedMeta) loadedMeta.textContent = `(${sizeMb} MB)`;

        if (fabFileBadge) fabFileBadge.hidden = false;
        if (fabFileLabel) fabFileLabel.hidden = true;
        if (fabFileName) {
          fabFileName.textContent = `📄 ${activeFile.name} (${sizeMb} MB)`;
          fabFileName.hidden = false;
        }
        if (fabFileSummarize) fabFileSummarize.hidden = false;
        if (fabFileRemove) fabFileRemove.hidden = false;
      } else {
        if (fileInput) fileInput.value = "";
        if (fabFileInput) fabFileInput.value = "";
        if (fileLoaded) fileLoaded.hidden = true;
        if (dropContent) dropContent.hidden = false;

        if (fabFileBadge) fabFileBadge.hidden = true;
        if (fabFileLabel) fabFileLabel.hidden = false;
        if (fabFileName) {
          fabFileName.textContent = "";
          fabFileName.hidden = true;
        }
        if (fabFileSummarize) fabFileSummarize.hidden = true;
        if (fabFileRemove) fabFileRemove.hidden = true;
      }
    }

    function loadFile(file, targetFeed) {
      activeFile = file;
      syncFileUi();
      submitQuery("Resumen del documento cargado", targetFeed || feed);
    }

    function clearFile() {
      activeFile = null;
      syncFileUi();
    }

    // Chips principales (sección inline)
    document.querySelectorAll("#eva-copilot .copilot-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const prompt = chip.getAttribute("data-prompt") || chip.textContent.trim();
        input.value = prompt;
        submitQuery(prompt, feed);
      });
    });

    // Send button & enter key (sección inline)
    sendBtn.addEventListener("click", () => {
      const q = input.value.trim();
      if (q || activeFile) submitQuery(q, feed);
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const q = input.value.trim();
        if (q || activeFile) submitQuery(q, feed);
      }
    });

    // File input change (sección inline)
    fileInput?.addEventListener("change", (e) => {
      if (e.target.files && e.target.files[0]) {
        loadFile(e.target.files[0], feed);
      }
    });

    // Drag and Drop (sección inline)
    if (dropzone) {
      ["dragenter", "dragover"].forEach((evt) => {
        dropzone.addEventListener(evt, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropzone.classList.add("dragover");
        });
      });

      ["dragleave", "drop"].forEach((evt) => {
        dropzone.addEventListener(evt, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropzone.classList.remove("dragover");
        });
      });

      dropzone.addEventListener("drop", (e) => {
        const dt = e.dataTransfer;
        if (dt && dt.files && dt.files.length) {
          const file = dt.files[0];
          if (file.name.toLowerCase().endsWith(".pdf")) {
            loadFile(file, feed);
          } else {
            alert("Por favor selecciona un archivo PDF.");
          }
        }
      });
    }

    btnSummarize?.addEventListener("click", () => {
      submitQuery("Resumir este documento", feed);
    });

    btnRemoveFile?.addEventListener("click", clearFile);

    async function submitQuery(promptText, targetFeed) {
      const out = targetFeed || feed;
      if (!out) return;
      out.hidden = false;
      out.innerHTML = `
        <div class="copilot-card-response">
          <div class="copilot-card-title"><span class="copilot-sparkle">✦</span> Analizando solicitud...</div>
          <p class="copilot-reply-text">Procesando localmente en tu equipo sin salir a la red...</p>
        </div>
      `;

      try {
        const formData = new FormData();
        formData.append("prompt", promptText || "");
        if (activeFile) {
          formData.append("file", activeFile);
        }

        const res = await fetch("/api/copilot/chat", {
          method: "POST",
          headers: { "X-PDF-Client": BUILD },
          body: formData,
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          if (res.status === 404) {
            throw new Error(
              "Error en el servicio Copiloto (HTTP 404): la ruta /api/copilot/chat no está cargada en el servidor activo. Reinicie el servicio EVA PDF (puerto 8090) y recargue la página."
            );
          }
          throw new Error(errData.error || `Error en el servicio Copiloto (HTTP ${res.status})`);
        }

        const data = await res.json();
        renderResponse(data, out);
      } catch (err) {
        out.innerHTML = `
          <div class="copilot-card-response">
            <div class="copilot-card-title copilot-card-title-error">⚠️ No se pudo completar la consulta</div>
            <p class="copilot-reply-text">${escapeHtml(err.message)}</p>
          </div>
        `;
      }
    }

    function renderResponse(data, targetFeed) {
      const out = targetFeed || feed;
      let html = `<div class="copilot-card-response">`;

      if (data.type === "summary") {
        html += `
          <div class="copilot-card-title"><span class="copilot-sparkle">✦</span> Resumen del Documento</div>
          <p class="copilot-reply-text">${escapeHtml(data.reply)}</p>
        `;
        if (data.data && data.data.suggested_tools && data.data.suggested_tools.length) {
          html += `<div class="copilot-tools-row">`;
          data.data.suggested_tools.forEach((t) => {
            html += `<button type="button" class="copilot-tool-cta" data-tool="${escapeHtml(t.id)}">${escapeHtml(t.icon)} ${escapeHtml(t.name)}</button>`;
          });
          html += `</div>`;
        }
      } else if (data.type === "qa") {
        html += `
          <div class="copilot-card-title"><span class="copilot-sparkle">✦</span> Respuestas encontradas en el PDF</div>
          <p class="copilot-reply-text">${escapeHtml(data.reply)}</p>
        `;
        if (data.matches && data.matches.length) {
          html += `<div class="copilot-matches-list">`;
          data.matches.forEach((m) => {
            html += `
              <div class="copilot-match-item">
                <span class="copilot-match-page">Pág. ${escapeHtml(m.page)}:</span>
                "${escapeHtml(m.snippet)}"
              </div>
            `;
          });
          html += `</div>`;
        }
        if (data.suggested_tool) {
          html += `<button type="button" class="copilot-tool-cta" data-tool="${escapeHtml(data.suggested_tool.id)}">${escapeHtml(data.suggested_tool.icon)} Abrir en ${escapeHtml(data.suggested_tool.name)}</button>`;
        }
      } else if (data.type === "plan") {
        html += `
          <div class="copilot-card-title"><span class="copilot-sparkle">✦</span> Plan Agéntico Generado</div>
          <p class="copilot-reply-text">${escapeHtml(data.reply)}</p>
          <ol class="copilot-plan-steps">
        `;
        (data.steps || []).forEach((st) => {
          let desc = st.action;
          if (st.action === "redact_pattern") desc = `Censurar patrones (${(st.patterns || []).join(", ")})`;
          if (st.action === "replace_text") desc = `Reemplazar "${st.find}" por "${st.replace}"`;
          if (st.action === "watermark") desc = `Marca de agua "${st.text}"`;
          if (st.action === "anti_track") desc = `Purga de rastreo y scripts`;
          if (st.action === "forensic_sanitize") desc = `Desinfección forense de metadatos`;
          if (st.action === "delete_pages") desc = `Eliminar páginas ${st.pages}`;
          html += `<li>${escapeHtml(desc)}</li>`;
        });
        html += `
          </ol>
          <button type="button" class="copilot-btn-send copilot-apply-btn">Aprobar y Ejecutar Plan</button>
        `;
      } else if (data.recommended_tool) {
        const t = data.recommended_tool;
        html += `
          <div class="copilot-card-title"><span class="copilot-sparkle">✦</span> Herramienta recomendada</div>
          <p class="copilot-reply-text">${escapeHtml(data.reply)}</p>
          <button type="button" class="copilot-tool-cta" data-tool="${escapeHtml(t.id)}">${escapeHtml(t.icon)} Abrir ${escapeHtml(t.name)}</button>
        `;
      } else {
        html += `
          <div class="copilot-card-title"><span class="copilot-sparkle">✦</span> Asistente EVA</div>
          <p class="copilot-reply-text">${escapeHtml(data.reply)}</p>
        `;
      }

      html += `</div>`;
      out.innerHTML = html;

      out.querySelectorAll(".copilot-tool-cta").forEach((btn) => {
        btn.addEventListener("click", () => {
          const toolId = btn.getAttribute("data-tool");
          if (toolId) {
            closeFabPanel(false);
            triggerOpenTool(toolId);
          }
        });
      });

      const applyBtn = out.querySelector(".copilot-apply-btn");
      if (applyBtn && data.steps && activeFile) {
        applyBtn.addEventListener("click", async () => {
          applyBtn.disabled = true;
          applyBtn.textContent = "Aplicando plan...";
          try {
            const formData = new FormData();
            formData.append("files", activeFile);
            formData.append("options", JSON.stringify({ approved: true, steps: data.steps }));
            const r = await fetch("/api/process/copilot_apply", {
              method: "POST",
              headers: { "X-PDF-Client": BUILD },
              body: formData,
            });
            if (r.ok) {
              const blob = await r.blob();
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `copiloto_${activeFile.name}`;
              a.click();
              URL.revokeObjectURL(url);
              applyBtn.textContent = "✓ Plan ejecutado y descargado";
            } else {
              const err = await r.json().catch(() => ({}));
              alert("Error al aplicar plan: " + (err.error || r.statusText));
              applyBtn.disabled = false;
              applyBtn.textContent = "Reintentar";
            }
          } catch (e) {
            alert("Error al conectar: " + e.message);
            applyBtn.disabled = false;
          }
        });
      }
    }

    function triggerOpenTool(toolId) {
      if (typeof window.openToolById === "function") {
        const opened = window.openToolById(toolId, activeFile);
        if (opened !== false) return;
      }
      const toolCards = document.querySelectorAll(".tool-card");
      for (const card of toolCards) {
        if (card.getAttribute("data-tool-id") === toolId) {
          card.click();
          card.scrollIntoView({ behavior: "smooth", block: "center" });
          return;
        }
      }
      const section = document.getElementById("herramientas");
      if (section) section.scrollIntoView({ behavior: "smooth" });
    }

    // =========================================================================
    // BOTÓN FLOTANTE FIJO DEL COPILOTO + BÚSQUEDA INTEGRADA DE FUNCIONES
    // =========================================================================
    function getToolsCatalog() {
      if (typeof window.getEvaToolsCatalog === "function") {
        return window.getEvaToolsCatalog();
      }
      return Array.from(document.querySelectorAll(".tool-card")).map((card) => ({
        id: card.dataset.toolId || "",
        name: card.querySelector("h3")?.textContent?.trim() || "",
        icon: card.querySelector(".tool-icon")?.textContent?.trim() || "✦",
        category: card.dataset.category || "organize",
        level: card.dataset.level || "basic",
        levelLabel: card.querySelector(".tool-level")?.textContent?.trim() || "Local",
        desc: card.querySelector("p")?.textContent?.trim() || "",
        detail: "",
        keywords: "",
        io: "",
        unavailable: false,
        pendingMotor: false,
      }));
    }

    function renderFabTools() {
      if (!fabResults) return;
      const catalog = getToolsCatalog();
      const rawQuery = fabToolInput ? fabToolInput.value.trim() : "";
      const query = normalizeText(rawQuery);

      if (fabToolClear) fabToolClear.hidden = rawQuery.length === 0;
      if (fabAskAiBtn) fabAskAiBtn.hidden = rawQuery.length < 2;

      const filtered = catalog.filter((tool) => {
        if (fabCategory !== "all" && tool.level !== fabCategory) return false;
        if (!query) return true;
        const haystack = normalizeText(
          `${tool.name} ${tool.desc} ${tool.detail || ""} ${tool.keywords || ""} ${tool.levelLabel || ""} ${tool.io || ""}`
        );
        return haystack.includes(query);
      });

      fabVisibleTools = filtered;
      if (fabHighlightedIndex >= filtered.length) {
        fabHighlightedIndex = filtered.length > 0 ? 0 : -1;
      }

      if (fabResultsCount) {
        fabResultsCount.textContent = rawQuery
          ? `${filtered.length} función(es) para "${rawQuery}"`
          : `${filtered.length} función(es) disponibles`;
      }

      if (!filtered.length) {
        fabResults.innerHTML = `
          <div class="copilot-fab-empty">
            <p>No se encontraron funciones directas para "<strong>${escapeHtml(rawQuery)}</strong>".</p>
            <button type="button" class="copilot-tool-cta copilot-fab-empty-ai">✦ Preguntar al Copiloto IA</button>
          </div>
        `;
        const askEmpty = fabResults.querySelector(".copilot-fab-empty-ai");
        askEmpty?.addEventListener("click", () => escalateSearchToAi(rawQuery));
        return;
      }

      fabResults.innerHTML = filtered
        .map((tool, idx) => {
          const activeCls = idx === fabHighlightedIndex ? " is-highlighted" : "";
          const badgeHtml = tool.unavailable
            ? `<span class="copilot-fab-item-warn">Reiniciar servidor</span>`
            : tool.pendingMotor
              ? `<span class="copilot-fab-item-warn">Motor pendiente</span>`
              : "";
          return `
            <button
              type="button"
              role="option"
              aria-selected="${idx === fabHighlightedIndex ? "true" : "false"}"
              class="copilot-fab-item${activeCls}"
              data-fab-tool-id="${escapeHtml(tool.id)}"
              data-fab-index="${idx}"
            >
              <span class="copilot-fab-item-icon" data-category="${escapeHtml(tool.category)}" aria-hidden="true">${escapeHtml(tool.icon)}</span>
              <span class="copilot-fab-item-main">
                <span class="copilot-fab-item-top">
                  <strong>${escapeHtml(tool.name)}</strong>
                  <span class="copilot-fab-item-level" data-level="${escapeHtml(tool.level)}">${escapeHtml(tool.levelLabel)}</span>
                </span>
                <span class="copilot-fab-item-desc">${escapeHtml(tool.desc)}</span>
                ${badgeHtml}
              </span>
              <span class="copilot-fab-item-arrow" aria-hidden="true">↗</span>
            </button>
          `;
        })
        .join("");

      fabResults.querySelectorAll(".copilot-fab-item").forEach((itemBtn) => {
        itemBtn.addEventListener("click", () => {
          const toolId = itemBtn.getAttribute("data-fab-tool-id");
          if (toolId) {
            closeFabPanel(false);
            triggerOpenTool(toolId);
          }
        });
      });
    }

    function highlightFabResult(nextIndex) {
      if (!fabVisibleTools.length) return;
      const total = fabVisibleTools.length;
      fabHighlightedIndex = ((nextIndex % total) + total) % total;
      const items = fabResults ? fabResults.querySelectorAll(".copilot-fab-item") : [];
      items.forEach((el, idx) => {
        const isSel = idx === fabHighlightedIndex;
        el.classList.toggle("is-highlighted", isSel);
        el.setAttribute("aria-selected", String(isSel));
        if (isSel) el.scrollIntoView({ block: "nearest" });
      });
    }

    function setFabTab(tabName) {
      fabActiveTab = tabName === "ai" ? "ai" : "search";
      fabTabs.forEach((btn) => {
        const active = btn.getAttribute("data-fab-tab") === fabActiveTab;
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-selected", String(active));
      });
      if (fabViewSearch) fabViewSearch.hidden = fabActiveTab !== "search";
      if (fabViewAi) fabViewAi.hidden = fabActiveTab !== "ai";

      if (fabPanelOpen) {
        if (fabActiveTab === "search") {
          renderFabTools();
          fabToolInput?.focus();
        } else {
          fabAiInput?.focus();
        }
      }
    }

    function escalateSearchToAi(queryText) {
      const q = String(queryText || "").trim();
      setFabTab("ai");
      if (fabAiInput) fabAiInput.value = q;
      if (q || activeFile) {
        submitQuery(q, fabAiFeed);
      }
    }

    // Regla interna de activación del botón flotante:
    // Se activa al desplazar la UI principal hacia abajo cuando las opciones fijas
    // superiores (#eva-copilot y la barra fija de filtros/búsqueda #herramientas .toolbar)
    // salen de la vista superior. Se oculta automáticamente al regresar arriba o al abrir un diálogo modal.
    const copilotSectionEl = document.getElementById("eva-copilot");
    const toolsToolbarEl = document.querySelector("#herramientas .toolbar");

    function shouldActivateFloatingButton() {
      const anyDialogOpen = Boolean(document.querySelector("dialog[open]"));
      if (anyDialogOpen) return false;
      if (fabPanelOpen) return true;

      const copilotHidden = !copilotSectionEl || copilotSectionEl.getBoundingClientRect().bottom <= FIXED_OPTION_HIDDEN_EDGE_PX;
      const toolbarHidden = !toolsToolbarEl || toolsToolbarEl.getBoundingClientRect().bottom <= FIXED_OPTION_HIDDEN_EDGE_PX;
      const scrolledDown = window.scrollY >= FLOATING_SCROLL_THRESHOLD_PX;

      return scrolledDown && copilotHidden && toolbarHidden;
    }

    function evaluateFloatingVisibility() {
      if (!fabBtn) return;
      const anyDialogOpen = Boolean(document.querySelector("dialog[open]"));
      if (anyDialogOpen && fabPanelOpen) {
        closeFabPanel(false);
      }
      const visible = shouldActivateFloatingButton();
      fabBtn.classList.toggle("is-visible", visible);
      fabBtn.setAttribute("aria-hidden", String(!visible));
      fabBtn.tabIndex = visible ? 0 : -1;
    }

    function openFabPanel(initialTab) {
      if (!fabPanel || !fabBtn) return;
      fabPanelOpen = true;
      fabPanel.hidden = false;
      fabBtn.setAttribute("aria-expanded", "true");
      fabBtn.classList.add("is-open");
      evaluateFloatingVisibility();
      setFabTab(initialTab || fabActiveTab);
    }

    function closeFabPanel(restoreFocus = true) {
      if (!fabPanel || !fabBtn) return;
      fabPanelOpen = false;
      fabPanel.hidden = true;
      fabBtn.setAttribute("aria-expanded", "false");
      fabBtn.classList.remove("is-open");
      evaluateFloatingVisibility();
      if (restoreFocus && fabBtn.classList.contains("is-visible")) {
        fabBtn.focus();
      }
    }

    if (fabBtn && fabPanel) {
      fabBtn.addEventListener("click", () => {
        if (fabPanelOpen) closeFabPanel(false);
        else openFabPanel("search");
      });

      fabClose?.addEventListener("click", () => closeFabPanel(true));

      fabTabs.forEach((btn) => {
        btn.addEventListener("click", () => {
          setFabTab(btn.getAttribute("data-fab-tab"));
        });
      });

      fabCatBtns.forEach((btn) => {
        btn.addEventListener("click", () => {
          fabCategory = btn.getAttribute("data-fab-cat") || "all";
          fabCatBtns.forEach((item) => {
            const active = item === btn;
            item.classList.toggle("active", active);
            item.setAttribute("aria-pressed", String(active));
          });
          fabHighlightedIndex = -1;
          renderFabTools();
        });
      });

      fabToolInput?.addEventListener("input", () => {
        fabHighlightedIndex = 0;
        renderFabTools();
      });

      fabToolInput?.addEventListener("keydown", (e) => {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          highlightFabResult(fabHighlightedIndex + 1);
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          highlightFabResult(fabHighlightedIndex - 1);
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (fabVisibleTools.length > 0) {
            const idx = fabHighlightedIndex >= 0 ? fabHighlightedIndex : 0;
            const picked = fabVisibleTools[idx];
            if (picked) {
              closeFabPanel(false);
              triggerOpenTool(picked.id);
            }
          } else if (fabToolInput.value.trim()) {
            escalateSearchToAi(fabToolInput.value.trim());
          }
        }
      });

      fabToolClear?.addEventListener("click", () => {
        if (!fabToolInput) return;
        fabToolInput.value = "";
        fabHighlightedIndex = -1;
        renderFabTools();
        fabToolInput.focus();
      });

      fabAskAiBtn?.addEventListener("click", () => {
        escalateSearchToAi(fabToolInput ? fabToolInput.value : "");
      });

      // Copiloto IA dentro del panel flotante
      fabAiSend?.addEventListener("click", () => {
        const q = fabAiInput ? fabAiInput.value.trim() : "";
        if (q || activeFile) submitQuery(q, fabAiFeed);
      });

      fabAiInput?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          const q = fabAiInput.value.trim();
          if (q || activeFile) submitQuery(q, fabAiFeed);
        }
      });

      document.querySelectorAll(".copilot-fab-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
          const prompt = chip.getAttribute("data-prompt") || chip.textContent.trim();
          if (fabAiInput) fabAiInput.value = prompt;
          submitQuery(prompt, fabAiFeed);
        });
      });

      fabFileInput?.addEventListener("change", (e) => {
        if (e.target.files && e.target.files[0]) {
          loadFile(e.target.files[0], fabAiFeed);
        }
      });

      fabFileSummarize?.addEventListener("click", () => {
        submitQuery("Resumir este documento", fabAiFeed);
      });

      fabFileRemove?.addEventListener("click", clearFile);

      fabScrollTop?.addEventListener("click", () => {
        closeFabPanel(false);
        window.scrollTo({ top: 0, behavior: "smooth" });
      });

      // Cerrar al hacer clic fuera del panel flotante
      document.addEventListener("click", (e) => {
        if (!fabPanelOpen || !fabShell) return;
        if (!fabShell.contains(e.target)) {
          closeFabPanel(false);
        }
      });

      // Atajos globales: Ctrl+K / Cmd+K para abrir búsqueda/copiloto, Esc para cerrar
      document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
          if (document.querySelector("dialog[open]")) return;
          e.preventDefault();
          if (fabPanelOpen) closeFabPanel(false);
          else openFabPanel("search");
          return;
        }
        if (e.key === "Escape" && fabPanelOpen) {
          e.preventDefault();
          closeFabPanel(true);
        }
      });

      // Observadores de desplazamiento, intersección y modales nativos (<dialog>)
      let rafPending = false;
      const scheduleEvaluate = () => {
        if (rafPending) return;
        rafPending = true;
        window.requestAnimationFrame(() => {
          rafPending = false;
          evaluateFloatingVisibility();
        });
      };

      window.addEventListener("scroll", scheduleEvaluate, { passive: true });
      window.addEventListener("resize", scheduleEvaluate, { passive: true });

      if (typeof window.IntersectionObserver === "function") {
        const observer = new IntersectionObserver(scheduleEvaluate, { threshold: [0, 0.05] });
        if (copilotSectionEl) observer.observe(copilotSectionEl);
        if (toolsToolbarEl) observer.observe(toolsToolbarEl);
      }

      if (typeof window.MutationObserver === "function") {
        const dialogObserver = new MutationObserver(scheduleEvaluate);
        document.querySelectorAll("dialog").forEach((dlg) => {
          dialogObserver.observe(dlg, { attributes: true, attributeFilter: ["open"] });
        });
      }

      evaluateFloatingVisibility();

      window.evaCopilotFab = {
        open: openFabPanel,
        close: closeFabPanel,
        evaluateVisibility: evaluateFloatingVisibility,
        shouldActivate: shouldActivateFloatingButton,
      };
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCopilot);
  } else {
    initCopilot();
  }
})();
