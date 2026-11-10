"use strict";

/**
 * Web Worker aislado para tareas de tiling / opcional PDFium-Wasm en /canvas.
 * Se mantiene 100% libre de red y solo procesa mensajes de renderizado local.
 */
self.addEventListener("message", async (event) => {
  const { id, action } = event.data || {};
  if (action === "ping") {
    self.postMessage({ id, ok: true, mode: "pure-js-canvas-worker" });
    return;
  }
  self.postMessage({ id, ok: false, error: "Accion no reconocida en canvas_worker." });
});
