"use strict";
(() => {
  const opening = document.getElementById("folio-opening");
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  if (motion.matches) return;
  const previousFocus = document.activeElement;
  let timer;
  function close() {
    if (!opening.open) return;
    clearTimeout(timer);
    motion.removeEventListener("change", motionChanged);
    opening.close();
    if (previousFocus instanceof HTMLElement && previousFocus !== document.body) previousFocus.focus();
    else document.querySelector(".brand").focus({preventScroll:true});
  }
  function motionChanged(event) {
    if (event.matches) close();
  }
  opening.addEventListener("cancel", event => {
    event.preventDefault();
    close();
  });
  opening.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  });
  motion.addEventListener("change", motionChanged);
  opening.showModal();
  timer = setTimeout(close, 4500);
})();
