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

  const routes = [];
  let downloadUrl = null;

  function setStatus(msg, kind = "") {
    const bar = $("pipe-status");
    bar.textContent = msg;
    bar.className = "v2-status-bar" + (kind ? " " + kind : "");
  }

  function showDownload(blob, disposition, notice) {
    if (downloadUrl) URL.revokeObjectURL(downloadUrl);
    downloadUrl = URL.createObjectURL(blob);
    const match = (disposition || "").match(/filename="?([^";]+)"?/);
    const link = $("pipe-download-link");
    link.href = downloadUrl;
    link.download = match ? match[1] : "EVA00.zip";
    $("pipe-download").hidden = false;
    setStatus(notice || "Proceso completado correctamente.", "ok");
  }

  function renderRules() {
    const list = $("rule-list");
    list.replaceChildren();
    routes.forEach((rule, idx) => {
      const li = document.createElement("li");
      li.className = "v2-list-item";
      const span = document.createElement("span");
      span.textContent = `${idx + 1}. Si coincide /${rule.when.match_regex}/ -> carpeta "${rule.folder}" (${rule.name_template})`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "secondary";
      btn.textContent = "Quitar";
      btn.addEventListener("click", () => {
        routes.splice(idx, 1);
        renderRules();
      });
      li.append(span, btn);
      list.append(li);
    });
  }

  $("add-rule")?.addEventListener("click", () => {
    const rx = $("rule-regex").value.trim();
    const folder = $("rule-folder").value.trim() || "Clasificados";
    const tpl = $("rule-tpl").value.trim() || "{folder}/{doc_id}_{index}.pdf";
    if (!rx) {
      setStatus("Escribe un patrón Regex o texto disparador para la regla.", "error");
      return;
    }
    routes.push({ name: `regla-${routes.length + 1}`, when: { match_regex: rx }, folder, name_template: tpl });
    $("rule-regex").value = "";
    renderRules();
  });

  async function runOp(op, fileList, opts, expectJsonPreviewPre = null) {
    if (!fileList || !fileList.length) {
      setStatus("Selecciona los archivos requeridos antes de ejecutar.", "error");
      return;
    }
    const form = new FormData();
    Array.from(fileList).forEach((f) => form.append("files", f));
    form.append("options", JSON.stringify(opts));
    try {
      setStatus("Procesando en motor local...");
      const res = await window.folioProcess(op, form);
      const notice = res.headers.get("X-PDF-Notice") || "Listo.";
      const disp = res.headers.get("Content-Disposition") || "";
      const blob = await res.blob();
      if (expectJsonPreviewPre && disp.includes(".json")) {
        const text = await blob.text();
        expectJsonPreviewPre.textContent = text.slice(0, 20000);
        expectJsonPreviewPre.hidden = false;
      }
      showDownload(blob, disp, notice);
    } catch (err) {
      setStatus(err.message || "Error al ejecutar operación.", "error");
    }
  }

  $("run-pipeline")?.addEventListener("click", () => {
    const transforms = [];
    if ($("tr-anti-track").checked) transforms.push({ op: "anti_track" });
    if ($("tr-sanitize").checked) transforms.push({ op: "forensic_sanitize" });
    if ($("tr-compress").checked) transforms.push({ op: "compress" });
    const wm = $("tr-watermark").value.trim();
    if (wm) transforms.push({ op: "watermark", text: wm });

    const files = $("pipe-files").files;
    const labels = Array.from(files || []).map((f) => f.name);
    runOp("pipeline_run", files, {
      contextual_names: $("pipe-contextual-names").checked,
      source_labels: labels,
      pipeline: {
        split_by_regex: $("pipe-split-regex").value.trim(),
        routes,
        transforms,
      },
    });
  });

  $("btn-tpl-detect")?.addEventListener("click", () => {
    runOp("template_detect", $("tpl-pdf").files, {}, $("tpl-preview"));
  });

  $("btn-tpl-compile")?.addEventListener("click", () => {
    const fPdf = $("tpl-pdf").files?.[0];
    const fData = $("tpl-data").files?.[0];
    if (!fPdf || !fData) {
      setStatus("Sube la plantilla PDF y el CSV/JSON de filas.", "error");
      return;
    }
    runOp("template_compile", [fPdf, fData], {});
  });

  function buildSemanticOpts(dryRun) {
    const kind = $("sem-kind").value;
    const pat = $("sem-pattern").value.trim();
    const rep = $("sem-replace").value.trim();
    const rule = { kind, pattern: pat };
    if (kind === "currency") {
      rule.rate = Number(rep || "1");
      rule.target_currency = "USD";
    } else if (kind === "date") {
      rule.target_format = rep || "%Y-%m-%d";
    } else {
      rule.replacement = rep;
    }
    return { dry_run: dryRun, rules: [rule] };
  }

  $("btn-sem-dryrun")?.addEventListener("click", () => {
    const files = $("sem-files").files;
    if (!files?.length) return setStatus("Selecciona al menos un PDF.", "error");
    runOp("semantic_replace", [files[0]], buildSemanticOpts(true), $("sem-preview"));
  });

  $("btn-sem-apply")?.addEventListener("click", () => {
    runOp("semantic_replace", $("sem-files").files, buildSemanticOpts(false));
  });

  $("btn-tbl-extract")?.addEventListener("click", () => {
    runOp("table_bridge_extract", $("tbl-pdf").files, { format: "xlsx", include_borderless: true });
  });

  $("btn-tbl-apply")?.addEventListener("click", () => {
    const fPdf = $("tbl-pdf").files?.[0];
    const fData = $("tbl-edited").files?.[0];
    if (!fPdf || !fData) {
      setStatus("Sube tanto el PDF base como el Excel (.xlsx/.json) editado.", "error");
      return;
    }
    runOp("table_bridge_apply", [fPdf, fData], {});
  });

  $("btn-vec-svg")?.addEventListener("click", () => {
    runOp("extract_vectors_svg", $("vis-files").files, { include_eps: true });
  });

  $("btn-scan-3d")?.addEventListener("click", () => {
    runOp("scan_enhance_3d", $("vis-files").files, { perspective: true, dewarp: true, illumination_clean: true, mrc: true });
  });
})();
