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

  const roles = [];
  let downloadUrl = null;

  function setStatus(msg, kind = "") {
    const bar = $("vault-status");
    bar.textContent = msg;
    bar.className = "v2-status-bar" + (kind ? " " + kind : "");
  }

  function showDownload(blob, filename, notice) {
    if (downloadUrl) URL.revokeObjectURL(downloadUrl);
    downloadUrl = URL.createObjectURL(blob);
    const link = $("vault-download-link");
    link.href = downloadUrl;
    link.download = filename || "EVA00.pdf";
    $("vault-download").hidden = false;
    setStatus(notice || "Operación completada.", "ok");
  }

  function renderRoles() {
    const list = $("role-list");
    list.replaceChildren();
    roles.forEach((r, i) => {
      const li = document.createElement("li");
      li.className = "v2-list-item";
      const txt = document.createElement("span");
      txt.textContent = `${i + 1}. Rol "${r.role}" · Patrones censurados: ${r.redact_patterns.length}`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "secondary";
      btn.textContent = "Quitar";
      btn.addEventListener("click", () => {
        roles.splice(i, 1);
        renderRoles();
      });
      li.append(txt, btn);
      list.append(li);
    });
  }

  $("add-role-btn")?.addEventListener("click", () => {
    const role = $("role-name").value.trim();
    const password = $("role-pw").value;
    const patterns = $("role-patterns").value
      .split(";")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!role) return setStatus("Escribe el nombre del rol.", "error");
    if (password.length < 8) return setStatus("La clave del rol debe tener al menos 8 caracteres.", "error");
    roles.push({ role, password, redact_patterns: patterns });
    $("role-name").value = "";
    $("role-pw").value = "";
    $("role-patterns").value = "";
    renderRoles();
    setStatus(`Rol "${role}" añadido al empaquetado.`);
  });

  $("run-pack-btn")?.addEventListener("click", async () => {
    const pdfFile = $("pack-pdf").files?.[0];
    if (!pdfFile) return setStatus("Selecciona primero el PDF base.", "error");
    if (!roles.length) return setStatus("Añade al menos un rol con su contraseña.", "error");
    const form = new FormData();
    form.append("files", pdfFile);
    form.append("options", JSON.stringify({ mode: $("pack-mode").value, roles }));
    try {
      setStatus("Compilando versiones saneadas por rol y cifrando...");
      const res = await window.folioProcess("crypto_container_pack", form);
      const disp = res.headers.get("Content-Disposition") || "";
      const m = disp.match(/filename="?([^";]+)"?/);
      showDownload(await res.blob(), m ? m[1] : "EVA00.zip", res.headers.get("X-PDF-Notice"));
    } catch (err) {
      setStatus(err.message || "No se pudo crear el cripto-contenedor.", "error");
    }
  });

  function b64ToBytes(b64) {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) arr[i] = bin.charCodeAt(i);
    return arr;
  }

  $("unlock-client-btn")?.addEventListener("click", async () => {
    const file = $("unlock-file").files?.[0];
    const pw = $("unlock-pw").value;
    const roleFilter = $("unlock-role").value.trim().toLowerCase();
    if (!file || !pw) return setStatus("Selecciona el archivo .evacrypt e introduce la clave del rol.", "error");
    if (!window.crypto?.subtle) {
      return setStatus("WebCrypto requiere contexto HTTPS o localhost. Usa Descifrar vía Motor Local.", "error");
    }
    try {
      setStatus("Derivando clave PBKDF2-SHA256 y verificando AES-GCM localmente...");
      const doc = JSON.parse(await file.text());
      if (doc.format !== "EVA-CRYPT-V1") throw new Error("Formato .evacrypt incompatible.");
      const slots = (doc.roles || []).filter((s) => !roleFilter || String(s.role).toLowerCase() === roleFilter);
      const enc = new TextEncoder();
      const baseKey = await crypto.subtle.importKey("raw", enc.encode(pw), "PBKDF2", false, ["deriveKey"]);
      for (const slot of slots) {
        try {
          const aesKey = await crypto.subtle.deriveKey(
            {
              name: "PBKDF2",
              salt: b64ToBytes(slot.salt_b64),
              iterations: slot.iterations || 310000,
              hash: "SHA-256",
            },
            baseKey,
            { name: "AES-GCM", length: 256 },
            false,
            ["decrypt"]
          );
          const plain = await crypto.subtle.decrypt(
            {
              name: "AES-GCM",
              iv: b64ToBytes(slot.iv_b64),
              additionalData: enc.encode(slot.aad),
            },
            aesKey,
            b64ToBytes(slot.ciphertext_b64)
          );
          showDownload(
            new Blob([plain], { type: "application/pdf" }),
            `desbloqueado_${slot.role}.pdf`,
            `Acceso concedido en tu navegador al rol "${slot.role}" (0 bytes enviados al servidor).`
          );
          return;
        } catch {
          // Intentar siguiente ranura de rol
        }
      }
      setStatus("Clave o rol incorrecto para este archivo .evacrypt.", "error");
    } catch (err) {
      setStatus(err.message || "Error descifrando el contenedor en WebCrypto.", "error");
    }
  });

  $("unlock-server-btn")?.addEventListener("click", async () => {
    const file = $("unlock-file").files?.[0];
    const pw = $("unlock-pw").value;
    const role = $("unlock-role").value.trim();
    if (!file || !pw) return setStatus("Selecciona el archivo .evacrypt e introduce la clave.", "error");
    const form = new FormData();
    form.append("files", file);
    form.append("options", JSON.stringify({ role, role_password: pw }));
    try {
      setStatus("Verificando clave de rol en motor local...");
      const res = await window.folioProcess("crypto_container_unlock", form);
      showDownload(await res.blob(), "EVA00.pdf", res.headers.get("X-PDF-Notice"));
    } catch (err) {
      setStatus(err.message || "No se pudo descifrar el contenedor.", "error");
    }
  });

  async function runSimpleOp(op, files, opts, jsonOutPre = null) {
    if (!files || !files.length) return setStatus("Selecciona primero el documento PDF.", "error");
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    form.append("options", JSON.stringify(opts));
    try {
      setStatus("Ejecutando en motor local...");
      const res = await window.folioProcess(op, form);
      const disp = res.headers.get("Content-Disposition") || "";
      const m = disp.match(/filename="?([^";]+)"?/);
      const blob = await res.blob();
      if (jsonOutPre && disp.includes(".json")) {
        jsonOutPre.textContent = (await blob.text()).slice(0, 25000);
        jsonOutPre.hidden = false;
      }
      showDownload(blob, m ? m[1] : "EVA00.pdf", res.headers.get("X-PDF-Notice"));
    } catch (err) {
      setStatus(err.message || "Fallo en la operación.", "error");
    }
  }

  $("run-audit-json")?.addEventListener("click", () => {
    runSimpleOp("forensic_audit", $("audit-files").files, { format: "json" }, $("audit-preview"));
  });
  $("run-audit-zip")?.addEventListener("click", () => {
    runSimpleOp("forensic_audit", $("audit-files").files, { format: "zip" });
  });
  $("run-antitrack-btn")?.addEventListener("click", () => {
    runSimpleOp("anti_track", $("clean-pdf").files, { include_report: true });
  });
  $("run-sanitize-btn")?.addEventListener("click", () => {
    const patterns = $("sanitize-terms").value.split(";").map((s) => s.trim()).filter(Boolean);
    runSimpleOp("forensic_sanitize", $("clean-pdf").files, { redact_patterns: patterns, include_report: true });
  });
})();
