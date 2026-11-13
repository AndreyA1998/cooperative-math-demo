"use strict";

// A view-only renderer: copied model text and exported schemas never pass here.
export const MathPresentation = (() => {
  let renderer;
  const colors = { external: "#2463b3", internal: "#945512" };

  function load() {
    if (renderer) return renderer;
    const base = "https://cdn.jsdelivr.net/npm/katex@0.19.1/dist/";
    function append(element) {
      return new Promise((resolve, reject) => {
        element.addEventListener("load", resolve, { once: true });
        element.addEventListener("error", reject, { once: true });
        document.head.append(element);
      });
    }
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = base + "katex.min.css";
    style.integrity = "sha384-WwGtaC6ywCHxA5cstpj/3+xIZvTez8dq2IcBQaXRkenHZ7FVVq1ZROtURwfbtTlG";
    style.crossOrigin = "anonymous";
    const script = document.createElement("script");
    script.src = base + "katex.min.js";
    script.integrity = "sha384-a1WQdjRj162i159OYq041X6I4K8NenkrI09LlPmiHg0YOb7CR+wJOraXwK9abpnE";
    script.crossOrigin = "anonymous";
    let timeout;
    renderer = Promise.race([
      Promise.all([append(style), window.katex ? Promise.resolve() : append(script)]).then(() => window.katex),
      new Promise((resolve) => { timeout = setTimeout(() => resolve(null), 12000); }),
    ]).catch(() => null).then((katex) => {
      clearTimeout(timeout);
      if (!katex) {
        style.remove();
        script.remove();
        renderer = undefined; // A later generation can retry the optional renderer.
      }
      return katex;
    });
    return renderer;
  }

  function escapeText(text) {
    const escapes = {
      "\\": "\\textbackslash{}", "{": "\\{", "}": "\\}",
      "$": "\\$", "&": "\\&", "%": "\\%", "#": "\\#",
      "_": "\\_", "^": "\\textasciicircum{}", "~": "\\textasciitilde{}",
    };
    return text.replace(/[\\{}$&%#_^~]/g, (character) => escapes[character]);
  }

  function escaped(text, at) {
    let count = 0;
    while (at > 0 && text[--at] === "\\") count++;
    return count % 2 === 1;
  }

  const delimiters = [
    ["$$", "$$", true], ["\\[", "\\]", true],
    ["\\(", "\\)", false], ["$", "$", false],
  ];

  function mathRanges(text) {
    const ranges = [];
    for (let at = 0; at < text.length; at++) {
      if (escaped(text, at)) continue;
      const delimiter = delimiters.find(([open]) => text.startsWith(open, at));
      if (!delimiter) continue;
      const [open, close, display] = delimiter;
      let end = at + open.length;
      while (end < text.length && !(text.startsWith(close, end) && !escaped(text, end))) end++;
      if (end === text.length) continue;
      ranges.push({ start: at, contentStart: at + open.length, contentEnd: end, end: end + close.length, display });
      at = end + close.length - 1;
    }
    return ranges;
  }

  function standaloneMath(text) {
    let braces = 0;
    for (let at = 0; at < text.length; at++) {
      if (escaped(text, at)) continue;
      if (text[at] === "{") braces++;
      if (text[at] === "}" && --braces < 0) return false;
    }
    // Structural fragments may cross a fraction, environment or delimiter. Their
    // native formula stays intact; external input chips still identify the value.
    return braces === 0 && !/\\(?:left|right|middle|begin|end)\b|&|\\\\/.test(text);
  }

  function render(target, segments) {
    let text = "";
    let slots = [];
    for (const segment of segments) {
      const start = text.length;
      text += segment.text;
      if (segment.kind === "parameter" && !(segment.filled && segment.text.length === 0)) {
        slots.push({ ...segment, start, end: text.length });
      }
    }
    const ranges = mathRanges(text);
    // An annotation may own a value, but never a mixture of prose and TeX
    // delimiters. Keep such structural fragments exact and unhighlighted.
    slots = slots.filter((slot) => ranges.every((range) =>
      slot.end <= range.start || slot.start >= range.end
      || (slot.start >= range.contentStart && slot.end <= range.contentEnd)));
    const children = [];
    const equations = [];
    function appendText(into, start, end) {
      for (const slot of slots.filter((slot) => slot.end > start && slot.start < end)) {
        const first = Math.max(start, slot.start);
        const last = Math.min(end, slot.end);
        into.push(document.createTextNode(text.slice(start, first)));
        const span = document.createElement("span");
        span.className = "parameter-slot slot-" + slot.role + (slot.filled ? " slot-filled" : "");
        span.dataset.parameter = slot.key;
        span.textContent = text.slice(first, last);
        into.push(span);
        start = last;
      }
      into.push(document.createTextNode(text.slice(start, end)));
    }
    let at = 0;
    for (const range of ranges) {
      appendText(children, at, range.start);
      const equation = document.createElement("span");
      equation.className = "math-fragment" + (range.display ? " math-display" : "");
      const contained = slots.filter((slot) => slot.start >= range.contentStart && slot.end <= range.contentEnd
        && (!slot.filled || standaloneMath(slot.text)));
      let source = "";
      let position = range.contentStart;
      for (const slot of contained) {
        source += text.slice(position, slot.start);
        // Commands and colors come from this renderer. No HTML extensions or trust
        // are enabled; only the certified presentation fragment receives emphasis.
        const value = slot.filled ? slot.text : "\\text{" + escapeText(slot.text) + "}";
        source += "{\\color{" + colors[slot.role] + "}\\boxed{" + value + "}}";
        position = slot.end;
      }
      source += text.slice(position, range.contentEnd);
      if (contained.length) {
        equation.dataset.parameters = [...new Set(contained.map((slot) => slot.key))].join(" ");
      }
      // The readable fallback also preserves slot colors before/without KaTeX.
      const fallback = document.createElement("span");
      const fallbackContent = [];
      appendText(fallbackContent, range.start, range.end);
      fallback.append(...fallbackContent);
      equation.append(fallback);
      equations.push({ equation, source, display: range.display });
      children.push(equation);
      at = range.end;
    }
    appendText(children, at, text.length);
    target.replaceChildren(...children);
    if (!equations.length) return Promise.resolve(true);
    return load().then((katex) => {
      if (!katex) return false;
      let rendered = true;
      for (const { equation, source, display } of equations) {
        if (!target.contains(equation)) continue;
        const fallback = [...equation.childNodes];
        try {
          katex.render(source, equation, {
            displayMode: display, throwOnError: false, trust: false,
            strict: "ignore", maxExpand: 1000, maxSize: 50,
          });
          if (equation.querySelector(".katex-error")) throw new Error("Unsupported formula");
          equation.dataset.rendered = "true";
        } catch {
          rendered = false;
          equation.dataset.rendered = "false";
          equation.replaceChildren(...fallback);
        }
      }
      void document.fonts.ready.then(() => {
        if (!target.isConnected || !equations.some(({ equation }) => target.contains(equation))) return;
        let overflow = false;
        for (const { equation } of equations) {
          const visualWidth = equation.querySelector(".katex-html")?.getBoundingClientRect().width ?? equation.scrollWidth;
          const wide = visualWidth > equation.getBoundingClientRect().width + 2;
          if (wide) equation.tabIndex = 0;
          overflow ||= wide;
        }
        target.classList.toggle("has-wide-math", overflow);
      });
      return rendered;
    });
  }
  return { render };
})();
