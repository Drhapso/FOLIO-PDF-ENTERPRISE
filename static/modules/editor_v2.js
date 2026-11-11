"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  let activePdf = null;
  let lastPlan = null;
  let downloadUrl = null;
  let narrationSegments = [];

  function setStatus(msg, kind = "") {
    const el = $("v2-editor-status");
    if (!el) return;
    el.textContent = msg;
    el.className = "v2-status-bar" + (kind ? " " + kind : "");
  }

  function showResult(blob, disposition, notice) {
    if (downloadUrl) URL.revokeObjectURL(downloadUrl);
    downloadUrl = URL.createObjectURL(blob);
    const link = $("v2-download-link");
    const m = (disposition || "").match(/filename="?([^";]+)"?/);
    link.href = downloadUrl;
    link.download = m ? m[1] : "EVA00.pdf";
    $("v2-download-box").hidden = false;
    setStatus(notice || "Proceso completado.", "ok");
  }

  function syncActivePdf(file) {
    if (file && file.name.toLowerCase().endsWith(".pdf")) {
      activePdf = file;
      setStatus(`PDF activo en Suite V2: ${file.name}`);
    }
  }

  $("acro-standalone-file")?.addEventListener("change", (e) => syncActivePdf(e.target.files?.[0]));
  $("acro-prompt-file")?.addEventListener("change", (e) => syncActivePdf(e.target.files?.[0]));
  $("v2-editor-pdf")?.addEventListener("change", (e) => syncActivePdf(e.target.files?.[0]));

  $("acro-btn-v2")?.addEventListener("click", () => {
    const drawer = $("acro-v2-drawer");
    const open = drawer.hidden;
    drawer.hidden = !open;
    $("acro-btn-v2").classList.toggle("active", open);
    $("acro-btn-v2").setAttribute("aria-expanded", String(open));
  });

  function renderMathPreview() {
    const box = $("v2-math-preview");
    const expr = $("v2-latex-input")?.value || "";
    if (!box || !window.evaLatexToSvgNode) return;
    box.replaceChildren(window.evaLatexToSvgNode(expr));
  }
  $("v2-latex-input")?.addEventListener("input", renderMathPreview);
  renderMathPreview();

  async function runV2(op, opts) {
    if (!activePdf) {
      setStatus("Carga un archivo PDF en el panel V2 o en Abrir PDF.", "error");
      return null;
    }
    const form = new FormData();
    form.append("files", activePdf);
    form.append("options", JSON.stringify(opts));
    try {
      setStatus(`Ejecutando ${op}...`);
      const res = await window.folioProcess(op, form);
      const disp = res.headers.get("Content-Disposition") || "";
      const notice = res.headers.get("X-PDF-Notice") || "Listo.";
      const blob = await res.blob();
      return { res, disp, notice, blob };
    } catch (err) {
      setStatus(err.message || "Error procesando en Suite V2.", "error");
      return null;
    }
  }

  $("v2-copilot-plan-btn")?.addEventListener("click", async () => {
    const prompt = $("v2-copilot-prompt").value.trim();
    if (!prompt) return setStatus("Escribe una instrucción para el Co-Piloto.", "error");
    const result = await runV2("copilot_plan", { prompt });
    if (!result) return;
    try {
      const plan = JSON.parse(await result.blob.text());
      lastPlan = plan;
      $("v2-copilot-apply-btn").disabled = false;
      const thumbs = $("v2-copilot-thumbs");
      thumbs.replaceChildren();
      for (const b64 of plan.preview_thumbnails_png_b64 || []) {
        const img = document.createElement("img");
        img.src = "data:image/png;base64," + b64;
        img.alt = "Vista previa Co-Piloto sin modificar original";
        thumbs.append(img);
      }
      const pre = $("v2-copilot-json");
      pre.textContent = JSON.stringify({ steps: plan.steps, targets: (plan.target_highlights || []).length }, null, 2);
      pre.hidden = false;
      setStatus(result.notice, "ok");
    } catch {
      setStatus("No se pudo interpretar el plan JSON.", "error");
    }
  });

  $("v2-copilot-apply-btn")?.addEventListener("click", async () => {
    if (!lastPlan) return;
    const result = await runV2("copilot_apply", { approved: true, plan: lastPlan });
    if (!result) return;
    showResult(result.blob, result.disp, result.notice);
    $("v2-copilot-apply-btn").disabled = true;
    lastPlan = null;
  });

  $("v2-reflow-btn")?.addEventListener("click", async () => {
    const result = await runV2("edit_reflow", { preserve_images: true });
    if (result) showResult(result.blob, result.disp, result.notice);
  });

  $("v2-liquid-btn")?.addEventListener("click", async () => {
    const preset = $("v2-liquid-preset").value;
    const result = await runV2("liquid_compile", { preset, format: "zip" });
    if (result) showResult(result.blob, result.disp, result.notice);
  });

  $("v2-latex-btn")?.addEventListener("click", async () => {
    const latex = $("v2-latex-input").value.trim();
    const result = await runV2("latex_ocr", { latex, insert_into_pdf: true, format: "zip" });
    if (result) showResult(result.blob, result.disp, result.notice);
  });

  $("v2-fonts-btn")?.addEventListener("click", async () => {
    const result = await runV2("font_reconstruct", { audit_only: true });
    if (!result) return;
    const pre = $("v2-tools-out");
    pre.textContent = (await result.blob.text()).slice(0, 18000);
    pre.hidden = false;
    setStatus(result.notice, "ok");
  });

  $("v2-translate-btn")?.addEventListener("click", async () => {
    const pair = ($("v2-translate-pair")?.value || "es_en").split("_");
    const source_lang = pair[0] || "es";
    const target_lang = pair[1] || "en";
    const result = await runV2("translate_layout", { source_lang, target_lang });
    if (result) showResult(result.blob, result.disp, result.notice);
  });

  $("v2-wcag-btn")?.addEventListener("click", async () => {
    const result = await runV2("accessibility_tagger", { lang: "es-ES", format: "zip" });
    if (result) showResult(result.blob, result.disp, result.notice);
  });

  $("v2-speak-btn")?.addEventListener("click", async () => {
    if (!("speechSynthesis" in window)) {
      return setStatus("Este navegador no soporta Web Speech API.", "error");
    }
    if (!activePdf) return setStatus("Carga un PDF para reproducir Audio-Tags.", "error");
    const form = new FormData();
    form.append("files", activePdf);
    form.append("options", JSON.stringify({ page: Number($("acro-page-num")?.value || 1), dpi: 72 }));
    try {
      const res = await window.folioProcess("inspect", form);
      const data = await res.json();
      narrationSegments = (data.blocks || []).map((b) => b.text).filter(Boolean);
      if (!narrationSegments.length) return setStatus("Sin texto extraible para lectura de voz en esta página.");
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(narrationSegments.join(". "));
      utter.lang = "es-ES";
      window.speechSynthesis.speak(utter);
      setStatus(`Reproduciendo Audio-Tags (${narrationSegments.length} bloques)...`, "ok");
    } catch (err) {
      setStatus(err.message || "Error en Audio-Tags.", "error");
    }
  });

  $("v2-speak-stop")?.addEventListener("click", () => {
    window.speechSynthesis?.cancel();
    setStatus("Lectura Audio-Tags detenida.");
  });
})();
