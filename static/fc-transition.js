/* =============================================================================
   FC26 TACTICAL TRANSITION ENGINE · FALCON CENTER 2026
   Transiciones suaves con logos minimalistas · Batallón de Intendencia N.º 1
   ============================================================================= */

(function () {
  "use strict";

  const EMBLEMAS = {
    falcon_center: `
      <svg viewBox="0 0 100 100" class="fc26-eagle-svg" aria-hidden="true">
        <path d="M50 20 Q30 10 8 26 Q18 34 28 34 Q14 42 4 56 Q16 58 26 54 Q14 64 8 80 Q24 74 36 64 Q42 58 48 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M50 20 Q70 10 92 26 Q82 34 72 34 Q86 42 96 56 Q84 58 74 54 Q86 64 92 80 Q76 74 64 64 Q58 58 52 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M43 14 Q43 6 50 3 Q57 6 57 14 Q57 20 50 23 Q43 20 43 14 Z" fill="#ffffff"/>
        <polygon points="50,1 46,7 54,7" fill="#facc15"/>
        <polygon points="50,13 46,18 54,18" fill="#facc15"/>
        <path d="M33 30 L67 30 L67 58 Q67 74 50 84 Q33 74 33 58 Z" fill="#0f172a" stroke="#ffffff" stroke-width="2.2"/>
        <polygon points="50,26 51.5,29 54.5,29 52,31 53,34 50,32 47,34 48,31 45.5,29 48.5,29" fill="#facc15"/>
      </svg>
    `,
    falcon_web: `
      <svg viewBox="0 0 100 100" class="fc26-eagle-svg" aria-hidden="true">
        <path d="M50 20 Q30 10 8 26 Q18 34 28 34 Q14 42 4 56 Q16 58 26 54 Q14 64 8 80 Q24 74 36 64 Q42 58 48 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M50 20 Q70 10 92 26 Q82 34 72 34 Q86 42 96 56 Q84 58 74 54 Q86 64 92 80 Q76 74 64 64 Q58 58 52 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M33 30 L67 30 L67 58 Q67 74 50 84 Q33 74 33 58 Z" fill="#0f172a" stroke="#ffffff" stroke-width="2.2"/>
        <circle cx="50" cy="54" r="9" fill="none" stroke="#ffffff" stroke-width="2" stroke-dasharray="4 2"/>
        <circle cx="50" cy="54" r="4" fill="#ffffff"/>
        <path d="M43 43 L57 43 L50 66 Z" fill="none" stroke="#facc15" stroke-width="1.8"/>
      </svg>
    `,
    regimen: `
      <svg viewBox="0 0 100 100" class="fc26-eagle-svg" aria-hidden="true">
        <path d="M50 20 Q30 10 8 26 Q18 34 28 34 Q14 42 4 56 Q16 58 26 54 Q14 64 8 80 Q24 74 36 64 Q42 58 48 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M50 20 Q70 10 92 26 Q82 34 72 34 Q86 42 96 56 Q84 58 74 54 Q86 64 92 80 Q76 74 64 64 Q58 58 52 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M33 30 L67 30 L67 58 Q67 74 50 84 Q33 74 33 58 Z" fill="#0f172a" stroke="#ffffff" stroke-width="2.2"/>
        <rect x="42" y="44" width="16" height="19" rx="2" fill="none" stroke="#ffffff" stroke-width="2"/>
        <line x1="50" y1="44" x2="50" y2="63" stroke="#ffffff" stroke-width="1.5"/>
        <polygon points="50,38 48,43 52,43" fill="#facc15"/>
      </svg>
    `,
    eva_pdf: `
      <svg viewBox="0 0 100 100" class="fc26-eagle-svg" aria-hidden="true">
        <path d="M50 20 Q30 10 8 26 Q18 34 28 34 Q14 42 4 56 Q16 58 26 54 Q14 64 8 80 Q24 74 36 64 Q42 58 48 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M50 20 Q70 10 92 26 Q82 34 72 34 Q86 42 96 56 Q84 58 74 54 Q86 64 92 80 Q76 74 64 64 Q58 58 52 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M33 30 L67 30 L67 58 Q67 74 50 84 Q33 74 33 58 Z" fill="#0f172a" stroke="#ffffff" stroke-width="2.2"/>
        <rect x="41" y="42" width="14" height="20" rx="1.5" fill="none" stroke="#ffffff" stroke-width="1.8"/>
        <rect x="45" y="46" width="14" height="20" rx="1.5" fill="#1e293b" stroke="#cbd5e1" stroke-width="1.5"/>
        <line x1="48" y1="52" x2="56" y2="52" stroke="#facc15" stroke-width="1.8"/>
        <line x1="48" y1="58" x2="56" y2="58" stroke="#ffffff" stroke-width="1.4"/>
      </svg>
    `,
    help_desk: `
      <svg viewBox="0 0 100 100" class="fc26-eagle-svg" aria-hidden="true">
        <path d="M50 20 Q30 10 8 26 Q18 34 28 34 Q14 42 4 56 Q16 58 26 54 Q14 64 8 80 Q24 74 36 64 Q42 58 48 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M50 20 Q70 10 92 26 Q82 34 72 34 Q86 42 96 56 Q84 58 74 54 Q86 64 92 80 Q76 74 64 64 Q58 58 52 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M33 30 L67 30 L67 58 Q67 74 50 84 Q33 74 33 58 Z" fill="#0f172a" stroke="#ffffff" stroke-width="2.2"/>
        <path d="M50 38 L50 66 M44 48 L56 48 M42 56 L58 56" stroke="#ffffff" stroke-width="2"/>
        <polygon points="50,36 46,44 54,44" fill="#facc15"/>
        <circle cx="50" cy="62" r="3" fill="#38bdf8"/>
      </svg>
    `,
    falcon_produccion: `
      <svg viewBox="0 0 100 100" class="fc26-eagle-svg" aria-hidden="true">
        <path d="M50 20 Q30 10 8 26 Q18 34 28 34 Q14 42 4 56 Q16 58 26 54 Q14 64 8 80 Q24 74 36 64 Q42 58 48 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M50 20 Q70 10 92 26 Q82 34 72 34 Q86 42 96 56 Q84 58 74 54 Q86 64 92 80 Q76 74 64 64 Q58 58 52 48 Z" fill="#e2e8f0" stroke="#f8fafc" stroke-width="1.2"/>
        <path d="M33 30 L67 30 L67 58 Q67 74 50 84 Q33 74 33 58 Z" fill="#0f172a" stroke="#ffffff" stroke-width="2.2"/>
        <rect x="41" y="42" width="18" height="22" rx="2" fill="none" stroke="#ffffff" stroke-width="2"/>
        <line x1="41" y1="49" x2="59" y2="49" stroke="#cbd5e1" stroke-width="1.2"/>
        <line x1="41" y1="56" x2="59" y2="56" stroke="#cbd5e1" stroke-width="1.2"/>
        <circle cx="54" cy="45" r="1.8" fill="#22c55e"/>
        <circle cx="54" cy="52" r="1.8" fill="#22c55e"/>
      </svg>
    `
  };

  let overlayEl = null;

  function crearOverlay() {
    if (overlayEl) return overlayEl;
    overlayEl = document.createElement("div");
    overlayEl.className = "fc26-overlay";
    overlayEl.setAttribute("aria-hidden", "true");
    overlayEl.innerHTML = `
      <div class="fc26-emblem-wrap" id="fc26Emblem"></div>
      <div class="fc26-brand-text">
        <h3 class="fc26-platform-title" id="fc26Title">FALCON CENTER</h3>
        <p class="fc26-platform-sub" id="fc26Sub">Cargando entorno…</p>
      </div>
      <div class="fc26-loader-track">
        <div class="fc26-loader-bar"></div>
      </div>
    `;
    document.body.appendChild(overlayEl);
    return overlayEl;
  }

  function mostrar(idPlat, titulo, subtitulo) {
    const el = crearOverlay();
    const emblem = document.getElementById("fc26Emblem");
    const tit = document.getElementById("fc26Title");
    const sub = document.getElementById("fc26Sub");
    if (emblem) emblem.innerHTML = EMBLEMAS[idPlat] || EMBLEMAS.falcon_center;
    if (tit) tit.textContent = titulo || "FALCON CENTER";
    if (sub) sub.textContent = subtitulo || "Cargando entorno…";
    el.classList.add("fc26-active");
  }

  function ocultar() {
    if (!overlayEl) return;
    overlayEl.classList.remove("fc26-active");
  }

  function navegar(url, idPlat, titulo, subtitulo) {
    mostrar(idPlat, titulo, subtitulo);
    setTimeout(() => {
      window.location.href = url;
    }, 420);
  }

  function urlFalconCenter() {
    const host = window.location.hostname || "127.0.0.1";
    return `http://${host}:8000/`;
  }

  function irACenter(e) {
    if (e) e.preventDefault();
    navegar(urlFalconCenter(), "falcon_center", "FALCON CENTER - BAINT", "Regresando a Falcon Center…");
  }

  function enlazarBotones() {
    // Configurar enlaces con data-fc-retorno o id="fcCenterLink" o clase "btn-fc-center"
    const selectores = "[data-fc-retorno], #fcCenterLink, .btn-fc-center, .fc-center-btn";
    document.querySelectorAll(selectores).forEach((el) => {
      el.href = urlFalconCenter();
      el.addEventListener("click", irACenter);
    });

    // Enlaces de salida con data-fc-dest
    document.querySelectorAll("[data-fc-dest]").forEach((el) => {
      el.addEventListener("click", (e) => {
        const dest = el.dataset.fcDest;
        const tit = el.dataset.fcTitulo || "CONECTANDO";
        const sub = el.dataset.fcSub || "Iniciando plataforma…";
        const href = el.getAttribute("href");
        if (href && href !== "#") {
          e.preventDefault();
          navegar(href, dest, tit, sub);
        }
      });
    });
  }

  function manejarEntrada() {
    const body = document.body;
    if (!body) return;
    const plat = body.dataset.fcPlataforma;
    const sinEntrada = body.hasAttribute("data-fc-sin-entrada");
    // Si la página define data-fc-plataforma y no tiene data-fc-sin-entrada (ej: EVA)
    if (plat && !sinEntrada) {
      const tit = body.dataset.fcTitulo || "FALCON";
      const sub = body.dataset.fcSub || "Entorno operativo activo";
      mostrar(plat, tit, sub);
      setTimeout(() => {
        ocultar();
      }, 350);
    }
  }

  window.FC26 = {
    mostrar,
    ocultar,
    navegar,
    irACenter,
    urlFalconCenter
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      crearOverlay();
      enlazarBotones();
      manejarEntrada();
    });
  } else {
    crearOverlay();
    enlazarBotones();
    manejarEntrada();
  }
})();
