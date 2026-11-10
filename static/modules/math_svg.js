"use strict";

/**
 * Renderizador LaTeX -> SVG vectorial offline seguro (cero innerHTML).
 * Soporta fracciones \frac{}{}, raices \sqrt{}, sub/superindices y simbolos griegos/operadores.
 */
window.evaLatexToSvgNode = function evaLatexToSvgNode(rawExpr) {
  const NS = "http://www.w3.org/2000/svg";
  const symMap = {
    "\\alpha": "α", "\\beta": "β", "\\gamma": "γ", "\\delta": "δ", "\\epsilon": "ε",
    "\\theta": "θ", "\\lambda": "λ", "\\mu": "μ", "\\pi": "π", "\\sigma": "σ",
    "\\phi": "φ", "\\omega": "ω", "\\Omega": "Ω", "\\Delta": "Δ", "\\Sigma": "Σ",
    "\\sum": "∑", "\\int": "∫", "\\prod": "∏", "\\infty": "∞", "\\pm": "±",
    "\\times": "×", "\\cdot": "·", "\\leq": "≤", "\\geq": "≥", "\\neq": "≠", "\\approx": "≈",
  };
  let expr = String(rawExpr || "").trim().replace(/^\$+|\$+$/g, "");
  for (const [k, v] of Object.entries(symMap)) {
    expr = expr.split(k).join(v);
  }
  const svg = document.createElementNS(NS, "svg");
  let cx = 10;
  const baseY = 32;

  const mkText = (x, y, txt, size = 16, italic = false) => {
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", String(x.toFixed(1)));
    t.setAttribute("y", String(y.toFixed(1)));
    t.setAttribute("font-family", "serif");
    t.setAttribute("font-size", String(size));
    if (italic) t.setAttribute("font-style", "italic");
    t.setAttribute("fill", "#111827");
    t.textContent = txt;
    return t;
  };

  const renderInline = (parent, seg, xStart, yBase, fontSize) => {
    let x = xStart;
    let i = 0;
    while (i < seg.length) {
      const ch = seg[i];
      if ((ch === "^" || ch === "_") && i + 1 < seg.length) {
        const isSup = ch === "^";
        let script = "";
        if (seg[i + 1] === "{" && seg.indexOf("}", i + 2) !== -1) {
          const endB = seg.indexOf("}", i + 2);
          script = seg.slice(i + 2, endB);
          i = endB + 1;
        } else {
          script = seg[i + 1];
          i += 2;
        }
        const sy = isSup ? yBase - fontSize * 0.4 : yBase + fontSize * 0.25;
        const sf = Math.round(fontSize * 0.65);
        parent.append(mkText(x, sy, script, sf, true));
        x += Math.max(7, script.length * sf * 0.58);
        continue;
      }
      if (ch === "{" || ch === "}") {
        i += 1;
        continue;
      }
      let j = i + 1;
      while (j < seg.length && !"^{}".includes(seg[j]) && seg[j] !== "_") j += 1;
      const run = seg.slice(i, j);
      parent.append(mkText(x, yBase, run, fontSize, false));
      x += Math.max(6, run.length * fontSize * 0.55);
      i = j;
    }
    return x;
  };

  const fracRx = /\\frac\{([^{}]+)\}\{([^{}]+)\}/g;
  let lastIdx = 0;
  let match;
  while ((match = fracRx.exec(expr)) !== null) {
    if (match.index > lastIdx) {
      cx = renderInline(svg, expr.slice(lastIdx, match.index), cx, baseY, 17);
    }
    const gNum = document.createElementNS(NS, "g");
    const numEnd = renderInline(gNum, match[1], 0, 18, 13);
    const gDen = document.createElementNS(NS, "g");
    const denEnd = renderInline(gDen, match[2], 0, 42, 13);
    const wBar = Math.max(numEnd, denEnd, 16) + 8;
    gNum.setAttribute("transform", `translate(${(cx + (wBar - numEnd) / 2).toFixed(1)}, 0)`);
    gDen.setAttribute("transform", `translate(${(cx + (wBar - denEnd) / 2).toFixed(1)}, 0)`);
    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", String(cx.toFixed(1)));
    line.setAttribute("y1", "24");
    line.setAttribute("x2", String((cx + wBar).toFixed(1)));
    line.setAttribute("y2", "24");
    line.setAttribute("stroke", "#111827");
    line.setAttribute("stroke-width", "1.3");
    svg.append(gNum, line, gDen);
    cx += wBar + 6;
    lastIdx = fracRx.lastIndex;
  }
  if (lastIdx < expr.length) {
    cx = renderInline(svg, expr.slice(lastIdx), cx, baseY, 17);
  }
  const totalW = Math.max(90, cx + 10);
  svg.setAttribute("width", String(totalW));
  svg.setAttribute("height", "52");
  svg.setAttribute("viewBox", `0 0 ${totalW} 52`);
  return svg;
};
