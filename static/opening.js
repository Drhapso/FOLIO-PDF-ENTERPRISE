"use strict";
(() => {
  const opening = document.getElementById("folio-opening");
  const previousFocus = document.activeElement;
  let timer;
  function close() {
    if (!opening.open) return;
    clearTimeout(timer);
    opening.close();
    if (previousFocus instanceof HTMLElement && previousFocus !== document.body) previousFocus.focus();
    else document.querySelector(".brand").focus({preventScroll:true});
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
  opening.showModal();
  timer = setTimeout(close, 4500);
})();
