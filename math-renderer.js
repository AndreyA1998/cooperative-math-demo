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

  function labelMath(text) {
    // Unicode relations have math-mode expansions in KaTeX, even inside \text.
    // Only this fixed symbol map leaves text mode; ordinary label code stays escaped.
    const symbols = { "≠": "\\ne", "≤": "\\le", "≥": "\\ge", "∈": "\\in", "∉": "\\notin",
      "≈": "\\approx", "∞": "\\infty", "×": "\\times", "÷": "\\div", "±": "\\pm", "∓": "\\mp" };
    return text.split(/([≠≤≥∈∉≈∞×÷±∓])/).map(part => symbols[part]
      ? "{}" + symbols[part] + "{}" : "\\text{" + escapeText(part) + "}").join("");
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

  // KaTeX's native display environments also delimit math without $ or \[.
  const displayEnvironments = new Set([
    "equation", "equation*", "align", "align*", "alignat", "alignat*",
    "gather", "gather*", "CD",
  ]);

  function environmentRange(text, start) {
    if (!text.startsWith("\\begin{", start)) return null;
    const token = /\\(begin|end)\{([A-Za-z]+\*?)\}/y;
    token.lastIndex = start;
    const opening = token.exec(text);
    if (!opening || !displayEnvironments.has(opening[2])) return null;
    const stack = [opening[2]];
    for (let at = token.lastIndex; at < text.length; at++) {
      if (escaped(text, at)) continue;
      if (text[at] === "%") {
        const newline = text.indexOf("\n", at);
        if (newline < 0) return null;
        at = newline;
        continue;
      }
      if (text[at] !== "\\") continue;
      token.lastIndex = at;
      const match = token.exec(text);
      if (!match) continue;
      if (match[1] === "begin") stack.push(match[2]);
      else {
        if (stack.pop() !== match[2]) return null;
        if (!stack.length) {
          // Keep the native environment itself in the KaTeX source. Removing
          // begin/end or adding another wrapper would change alignment semantics.
          return { start, contentStart: start, contentEnd: token.lastIndex,
            end: token.lastIndex, display: true };
        }
      }
      at = token.lastIndex - 1;
    }
    return null;
  }

  // Tabular is text with math cells, not a math environment. Parse its small
  // native grammar into DOM cells; retain source offsets for every parameter.
  function groupAt(text, start) {
    while (/\s/.test(text[start] ?? "") && start < text.length) start++;
    if (text[start] !== "{") return null;
    let depth = 1;
    for (let at = start + 1; at < text.length; at++) {
      if (escaped(text, at)) continue;
      if (text[at] === "{") depth++;
      else if (text[at] === "}" && --depth === 0) {
        return { start, contentStart: start + 1, contentEnd: at, end: at + 1 };
      }
    }
    return null;
  }

  function tabularRange(text, start) {
    const opening = "\\begin{tabular}";
    if (!text.startsWith(opening, start)) return null;
    const columns = groupAt(text, start + opening.length);
    if (!columns || !/^[\s|lcr]+$/.test(text.slice(columns.contentStart, columns.contentEnd))) return null;
    const alignment = text.slice(columns.contentStart, columns.contentEnd).match(/[lcr]/g);
    if (!alignment?.length) return null;
    const close = "\\end{tabular}";
    const end = text.indexOf(close, columns.end);
    if (end < 0 || text.slice(columns.end, end).includes("\\begin{tabular}")) return null;
    const rows = [];
    let cells = [], first = columns.end, depth = 0, mathClose = null;
    function cell(last) {
      let begin = first;
      while (begin < last && /\s/.test(text[begin])) begin++;
      while (last > begin && /\s/.test(text[last - 1])) last--;
      let span = 1, align = alignment[cells.reduce((sum, item) => sum + item.span, 0)];
      if (text.startsWith("\\multicolumn", begin)) {
        const count = groupAt(text, begin + 12);
        const format = count && groupAt(text, count.end);
        const content = format && groupAt(text, format.end);
        if (!content || content.end !== last) return false;
        const number = text.slice(count.contentStart, count.contentEnd);
        const style = text.slice(format.contentStart, format.contentEnd);
        if (!/^[1-9]\d*$/.test(number) || !/^[|\s]*[lcr][|\s]*$/.test(style)) return false;
        span = Number(number);
        align = style.match(/[lcr]/)[0];
        begin = content.contentStart;
        last = content.contentEnd;
      }
      cells.push({ start: begin, end: last, span, align });
      return true;
    }
    function row(last) {
      if (!cell(last) || cells.reduce((sum, item) => sum + item.span, 0) !== alignment.length) return false;
      rows.push(cells);
      cells = [];
      return true;
    }
    for (let at = columns.end; at < end; at++) {
      if (escaped(text, at)) continue;
      if (mathClose) {
        if (text.startsWith(mathClose, at)) { at += mathClose.length - 1; mathClose = null; }
        continue;
      }
      const delimiter = delimiters.find(([open]) => text.startsWith(open, at));
      if (delimiter) { mathClose = delimiter[1]; at += delimiter[0].length - 1; continue; }
      if (text[at] === "{") depth++;
      else if (text[at] === "}" && --depth < 0) return null;
      if (depth) continue;
      if (text.startsWith("\\hline", at)) {
        if (text.slice(first, at).trim()) return null;
        at += 5;
        first = at + 1;
      } else if (text.startsWith("\\\\", at)) {
        if (!row(at)) return null;
        at++;
        first = at + 1;
      } else if (text[at] === "&") {
        if (!cell(at)) return null;
        first = at + 1;
      }
    }
    if (depth || mathClose) return null;
    if (text.slice(first, end).trim() || cells.length) { if (!row(end)) return null; }
    if (!rows.length) return null;
    return { start, end: end + close.length, contentStart: columns.end, contentEnd: end,
      kind: "table", rows };
  }

  // A box is a TeX group. It must never turn two native macro arguments into one.
  function argumentSafe(text, slot, range) {
    const commands = /\\(?:[dt]?frac|[dt]?binom)(?![A-Za-z])/g;
    commands.lastIndex = range.contentStart;
    function argument(start) {
      while (start < range.contentEnd && /\s/.test(text[start])) start++;
      if (text[start] === "{") return groupAt(text, start);
      if (start >= range.contentEnd) return null;
      const command = /^\\(?:[A-Za-z]+|.)/.exec(text.slice(start));
      return { start, end: start + (command ? command[0].length : 1) };
    }
    for (let match; (match = commands.exec(text)) && match.index < range.contentEnd;) {
      if (escaped(text, match.index)) continue;
      const first = argument(commands.lastIndex);
      const second = first && argument(first.end);
      if (!second) continue;
      if (slot.start <= match.index && slot.end >= second.end) continue;
      for (const arg of [first, second]) {
        if (slot.start < arg.end && slot.end > arg.start && !(slot.start >= arg.start && slot.end <= arg.end)) return false;
      }
    }
    return true;
  }

  function mathRanges(text, cell = false) {
    const ranges = [];
    for (let at = 0; at < text.length; at++) {
      if (escaped(text, at)) continue;
      const table = tabularRange(text, at);
      const bold = cell && text.startsWith("\\textbf", at) && groupAt(text, at + 7);
      if (table || bold) {
        const range = table || { ...bold, start: at, kind: "bold" };
        ranges.push(range);
        at = range.end - 1;
        continue;
      }
      const environment = environmentRange(text, at);
      if (environment) {
        ranges.push(environment);
        at = environment.end - 1;
        continue;
      }
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

  function symbolicMath(text) {
    if (typeof text !== "string" || !text) return false;
    let braces = 0, fences = 0;
    for (const token of text.match(/\\(?:[A-Za-z]+|.)|[{}$]/g) ?? []) {
      if (["$", "\\(", "\\)", "\\[", "\\]", "\\begin", "\\end", "\\\\"].includes(token)) return false;
      if (token === "{") braces++;
      else if (token === "}") braces--;
      else if (token === "\\left") fences++;
      else if (token === "\\right") fences--;
      if (braces < 0 || fences < 0) return false;
    }
    return braces === 0 && fences === 0;
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

  function render(target, segments, cell = false) {
    let text = "";
    let slots = [];
    for (const segment of segments) {
      const start = text.length;
      const symbolic = segment.kind === "parameter" && !segment.filled && symbolicMath(segment.symbolic_math);
      const content = symbolic ? segment.symbolic_math : segment.text;
      text += content;
      if (segment.kind === "parameter" && !(segment.filled && content.length === 0)) {
        slots.push({ ...segment, text: content, symbolic, start, end: text.length });
      }
    }
    const ranges = mathRanges(text, cell);
    for (const slot of slots) {
      if (slot.symbolic && !ranges.some((range) => slot.start < range.end && slot.end > range.start)) {
        ranges.push({ start: slot.start, contentStart: slot.start, contentEnd: slot.end,
          end: slot.end, display: false });
      }
    }
    ranges.sort((left, right) => left.start - right.start);
    // An annotation may own a value, but never a mixture of prose and TeX
    // delimiters. Keep such structural fragments exact and unhighlighted.
    slots = slots.filter((slot) => ranges.every((range) =>
      slot.end <= range.start || slot.start >= range.end
      || (slot.start >= range.contentStart && slot.end <= range.contentEnd)));
    const children = [];
    const equations = [];
    const nested = [];
    function literal(value) {
      return document.createTextNode(cell ? value.replace(/\\([%$&#_{}])/g, "$1") : value);
    }
    function sliceSegments(start, end) {
      const parts = [];
      for (const slot of slots.filter(item => item.start >= start && item.end <= end)) {
        parts.push({ kind: "text", text: text.slice(start, slot.start) });
        parts.push({ ...slot, symbolic_math: slot.symbolic ? slot.text : undefined });
        start = slot.end;
      }
      parts.push({ kind: "text", text: text.slice(start, end) });
      return parts;
    }
    function appendText(into, start, end) {
      for (const slot of slots.filter((slot) => slot.end > start && slot.start < end)) {
        const first = Math.max(start, slot.start);
        const last = Math.min(end, slot.end);
        into.push(literal(text.slice(start, first)));
        const span = document.createElement("span");
        span.className = "parameter-slot slot-" + slot.role + (slot.filled ? " slot-filled" : "");
        span.dataset.parameter = slot.key;
        span.textContent = text.slice(first, last);
        into.push(span);
        start = last;
      }
      into.push(literal(text.slice(start, end)));
    }
    let at = 0;
    for (const range of ranges) {
      appendText(children, at, range.start);
      if (range.kind === "table") {
        const wrapper = document.createElement("div");
        wrapper.className = "native-table";
        wrapper.style.cssText = "overflow-x:auto;max-width:100%;margin:1em 0";
        const table = document.createElement("table");
        table.style.cssText = "border-collapse:collapse;font:inherit";
        const body = table.createTBody();
        for (const row of range.rows) {
          const tr = body.insertRow();
          for (const item of row) {
            const td = tr.insertCell();
            td.colSpan = item.span;
            td.style.cssText = "border:1px solid #cbd3df;padding:.4em .75em";
            td.style.textAlign = { l: "left", c: "center", r: "right" }[item.align];
            nested.push(render(td, sliceSegments(item.start, item.end), true));
          }
        }
        wrapper.append(table);
        children.push(wrapper);
        at = range.end;
        continue;
      }
      if (range.kind === "bold") {
        const strong = document.createElement("strong");
        nested.push(render(strong, sliceSegments(range.contentStart, range.contentEnd), true));
        children.push(strong);
        at = range.end;
        continue;
      }
      const equation = document.createElement("span");
      equation.className = "math-fragment" + (range.display ? " math-display" : "");
      const contained = slots.filter((slot) => slot.start >= range.contentStart && slot.end <= range.contentEnd
        && (!slot.filled || (standaloneMath(slot.text) && argumentSafe(text, slot, range))));
      let source = "";
      let position = range.contentStart;
      for (const slot of contained) {
        source += text.slice(position, slot.start);
        // Commands and colors come from this renderer. No HTML extensions or trust
        // are enabled; only the certified presentation fragment receives emphasis.
        const value = slot.filled || slot.symbolic ? slot.text : labelMath(slot.text);
        source += "{\\color{" + colors[slot.role] + "}\\boxed{" + value + "}}";
        // A small visual gap keeps a boxed whole term distinct from an adjacent fraction.
        if (/^\\(?:dfrac|tfrac|frac)\b/.test(text.slice(slot.end, range.contentEnd))) source += "\\,";
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
    if (!equations.length) return Promise.all(nested).then(results => results.every(Boolean));
    const renderedMath = load().then((katex) => {
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
    return Promise.all([renderedMath, ...nested]).then(results => results.every(Boolean));
  }
  return { render };
})();
