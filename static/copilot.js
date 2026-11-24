"use strict";

(function () {
  const BUILD = document.querySelector('meta[name="client-build"]')?.content || "";
  let activeFile = null;

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

    if (!input || !sendBtn) return;

    // Chips
    document.querySelectorAll(".copilot-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const prompt = chip.getAttribute("data-prompt") || chip.textContent.trim();
        input.value = prompt;
        submitQuery(prompt);
      });
    });

    // Send button & enter key
    sendBtn.addEventListener("click", () => {
      const q = input.value.trim();
      if (q || activeFile) submitQuery(q);
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const q = input.value.trim();
        if (q || activeFile) submitQuery(q);
      }
    });

    // File input change
    fileInput?.addEventListener("change", (e) => {
      if (e.target.files && e.target.files[0]) {
        loadFile(e.target.files[0]);
      }
    });

    // Drag and Drop
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
            loadFile(file);
          } else {
            alert("Por favor selecciona un archivo PDF.");
          }
        }
      });
    }

    // Summarize button
    btnSummarize?.addEventListener("click", () => {
      submitQuery("Resumir este documento");
    });

    // Remove file button
    btnRemoveFile?.addEventListener("click", () => {
      activeFile = null;
      if (fileInput) fileInput.value = "";
      if (fileLoaded) fileLoaded.hidden = true;
      if (dropContent) dropContent.hidden = false;
    });

    function loadFile(file) {
      activeFile = file;
      if (dropContent) dropContent.hidden = true;
      if (fileLoaded) fileLoaded.hidden = false;
      if (loadedName) loadedName.textContent = file.name;
      if (loadedMeta) {
        const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
        loadedMeta.textContent = `(${sizeMb} MB)`;
      }
      submitQuery("Resumen del documento cargado");
    }

    async function submitQuery(promptText) {
      feed.hidden = false;
      feed.innerHTML = `
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
        renderResponse(data);
      } catch (err) {
        feed.innerHTML = `
          <div class="copilot-card-response">
            <div class="copilot-card-title copilot-card-title-error">⚠️ No se pudo completar la consulta</div>
            <p class="copilot-reply-text">${escapeHtml(err.message)}</p>
          </div>
        `;
      }
    }

    function renderResponse(data) {
      let html = `<div class="copilot-card-response">`;

      if (data.type === "summary") {
        html += `
          <div class="copilot-card-title"><span class="copilot-sparkle">✦</span> Resumen del Documento</div>
          <p class="copilot-reply-text">${escapeHtml(data.reply)}</p>
        `;
        if (data.data && data.data.suggested_tools && data.data.suggested_tools.length) {
          html += `<div class="copilot-tools-row">`;
          data.data.suggested_tools.forEach((t) => {
            html += `<button type="button" class="copilot-tool-cta" data-tool="${t.id}">${t.icon} ${escapeHtml(t.name)}</button>`;
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
                <span class="copilot-match-page">Pág. ${m.page}:</span>
                "${escapeHtml(m.snippet)}"
              </div>
            `;
          });
          html += `</div>`;
        }
        if (data.suggested_tool) {
          html += `<button type="button" class="copilot-tool-cta" data-tool="${data.suggested_tool.id}">${data.suggested_tool.icon} Abrir en ${escapeHtml(data.suggested_tool.name)}</button>`;
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
          <button type="button" id="copilot-apply-plan-btn" class="copilot-btn-send copilot-apply-btn">Aprobar y Ejecutar Plan</button>
        `;
      } else if (data.recommended_tool) {
        const t = data.recommended_tool;
        html += `
          <div class="copilot-card-title"><span class="copilot-sparkle">✦</span> Herramienta recomendada</div>
          <p class="copilot-reply-text">${escapeHtml(data.reply)}</p>
          <button type="button" class="copilot-tool-cta" data-tool="${t.id}">${t.icon} Abrir ${escapeHtml(t.name)}</button>
        `;
      } else {
        html += `
          <div class="copilot-card-title"><span class="copilot-sparkle">✦</span> Asistente EVA</div>
          <p class="copilot-reply-text">${escapeHtml(data.reply)}</p>
        `;
      }

      html += `</div>`;
      feed.innerHTML = html;

      // Attach actions to dynamically created tool buttons
      feed.querySelectorAll(".copilot-tool-cta").forEach((btn) => {
        btn.addEventListener("click", () => {
          const toolId = btn.getAttribute("data-tool");
          if (toolId) triggerOpenTool(toolId);
        });
      });

      // Attach action to apply plan button
      const applyBtn = document.getElementById("copilot-apply-plan-btn");
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
        window.openToolById(toolId, activeFile);
        return;
      }
      // Or find the card in the tools grid and click it
      const toolCards = document.querySelectorAll(".tool-card");
      for (const card of toolCards) {
        if (card.getAttribute("data-tool-id") === toolId) {
          card.click();
          card.scrollIntoView({ behavior: "smooth", block: "center" });
          return;
        }
      }
      // If not in grid, navigate or scroll to tools
      const section = document.getElementById("herramientas");
      if (section) section.scrollIntoView({ behavior: "smooth" });
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
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCopilot);
  } else {
    initCopilot();
  }
})();
