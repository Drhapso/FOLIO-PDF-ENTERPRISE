"use strict";

window.folioProcess = async function(operation, form, {signal} = {}) {
  const build = document.querySelector('meta[name="client-build"]').content;
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const token = Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
  const notice = document.createElement("section");
  notice.className = "processing-notice";
  notice.setAttribute("role", "status");
  notice.setAttribute("aria-live", "polite");
  const animation = document.createElement("video");
  animation.className = "processing-animation";
  animation.muted = true;
  animation.loop = true;
  animation.playsInline = true;
  animation.preload = "metadata";
  animation.setAttribute("aria-hidden", "true");
  animation.setAttribute("tabindex", "-1");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const syncMotion = () => {
    animation.autoplay = !reducedMotion.matches;
    if (reducedMotion.matches) animation.pause();
    else animation.play().catch(() => {
      console.info("EVA PDF Enterprise: el navegador no permitió reproducir la animación; el estado sigue disponible.");
    });
  };
  animation.addEventListener("error", () => {
    animation.hidden = true;
    console.warn("EVA PDF Enterprise: no se pudo cargar la animación de procesamiento.");
  }, {once: true});
  animation.src = `/static/loadinggif.mp4?v=${encodeURIComponent(build)}`;
  const content = document.createElement("div");
  content.className = "processing-notice-content";
  const title = document.createElement("strong");
  title.textContent = "Preparando procesamiento";
  const message = document.createElement("p");
  message.textContent = "Enviando la carga al servidor. No cierres esta pestaña.";
  const guidance = document.createElement("small");
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "secondary";
  cancel.textContent = "Cancelar espera";
  cancel.hidden = true;
  content.append(title, message, guidance, cancel);
  notice.append(animation, content);
  const host = document.querySelector("dialog[open]") || document.body;
  host.append(notice);
  reducedMotion.addEventListener("change", syncMotion);
  syncMotion();
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, {once: true});
  if (signal?.aborted) abort();
  let finished = false;
  let timer;
  let lastState = "";
  let lastMessage = "";
  let settings;
  const update = (heading, text) => {
    title.textContent = heading;
    if (text !== lastMessage) {
      message.textContent = text;
      lastMessage = text;
    }
  };
  cancel.addEventListener("click", async () => {
    cancel.disabled = true;
    try {
      const response = await fetch(`/api/queue/${token}/cancel`, {
        method: "POST", headers: {"X-PDF-Client": build},
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || "No se pudo cancelar la espera.");
      }
      update("Espera cancelada", "El trabajo no se ejecutará.");
    } catch (error) {
      update("No se pudo cancelar", error.message);
    } finally {
      cancel.disabled = false;
    }
  });
  async function poll() {
    try {
      const response = await fetch(`/api/queue/${token}`, {signal: controller.signal});
      if (finished) return;
      if (response.status === 404) {
        if (lastState === "processing") {
          update("Entregando resultado", "Recibiendo el resultado y comprobando la limpieza temporal.");
        }
      } else {
        if (!response.ok) throw new Error("No se pudo consultar la cola.");
        const data = await response.json();
        if (finished) return;
        lastState = data.state;
        cancel.hidden = data.state !== "queued";
        if (data.state === "queued") {
          update("En cola de procesamiento",
            `Posición de llegada: ${data.position}. Motores activos: ${data.active}. ` +
            `Espera máxima: ${data.max_wait_seconds} s. Las tareas ligeras pueden avanzar antes.`);
        } else {
          update(data.heavy ? "Procesando carga pesada" : "Procesando documento",
            "El motor está trabajando. No envíes otra copia; espera el resultado.");
        }
      }
    } catch (error) {
      if (!finished && error.name !== "AbortError") {
        update("Estado de cola no disponible",
          "La solicitud sigue en curso. No vuelvas a enviarla. " + error.message);
      }
    } finally {
      if (!finished) timer = setTimeout(poll, 1000);
    }
  }
  try {
    const response = await fetch("/api/capabilities", {signal: controller.signal});
    if (!response.ok) throw new Error("No se pudieron consultar los límites del servidor.");
    settings = await response.json();
    const uploads = form.getAll("files").filter(item => item instanceof Blob);
    const total = uploads.reduce((sum, file) => sum + file.size, 0);
    const maxFile = settings.max_file_mb * 1024 ** 2;
    if (uploads.some(file => file.size > maxFile) || total > settings.max_upload_mb * 1024 ** 2) {
      throw new Error(`Límite efectivo: ${settings.max_file_mb} MB por archivo y ` +
        `${settings.max_upload_mb} MB por solicitud. Divide el trabajo.`);
    }
    const queue = settings.queue;
    guidance.textContent = `Rango recomendado inicial: hasta ${queue.recommended_upload_mb} MB en conjunto. ` +
      "Los escaneos y el OCR pueden requerir más tiempo incluso con archivos pequeños.";
    if (total >= queue.heavy_upload_mb * 1024 ** 2 || queue.heavy_operations.includes(operation)) {
      update("Carga pesada: procesamiento controlado",
        `Se limitarán las tareas pesadas a ${queue.max_heavy_jobs} simultáneas para proteger el servidor.`);
    } else if (total > queue.recommended_upload_mb * 1024 ** 2) {
      update("Carga superior al rango recomendado",
        "El archivo se admite, pero puede tardar más. Para una respuesta ágil, divide el lote si es posible.");
    }
    timer = setTimeout(poll, 400);
    const result = await fetch("/api/process/" + operation, {
      method: "POST", body: form,
      headers: {"X-PDF-Client": build, "X-PDF-Job": token},
      signal: controller.signal,
    });
    if (!result.ok) {
      const data = await result.json();
      throw new Error(data.error || `El servidor rechazó la solicitud (${result.status}).`);
    }
    // Consumir la respuesta mantiene el aviso durante la descarga, no solo hasta las cabeceras.
    const body = await result.blob();
    return new Response(body, {status: result.status, headers: result.headers});
  } finally {
    finished = true;
    clearTimeout(timer);
    controller.abort();
    signal?.removeEventListener("abort", abort);
    reducedMotion.removeEventListener("change", syncMotion);
    animation.pause();
    animation.removeAttribute("src");
    animation.load();
    notice.remove();
  }
};
