import { request } from "./transport.js";
import { MathPresentation } from "./math-renderer.js";

const byId = (id) => document.getElementById("composite-" + id);
const tree = byId("tree");
const structureControls = byId("structure-controls");
const parameterControls = byId("parameter-controls");
const formatNumber = new Intl.NumberFormat("ru");
let currentSchema;
let currentInstance;
let currentVariantRaw;
let templatePresentation;
let presentationRevision = 0;
function showStatus(message, error = false) {
  byId("status").textContent = message;
  byId("status").classList.toggle("error", error);
  byId("status").hidden = !message;
}
async function postJSON(action, body) { return request("POST", "/api/composite/" + action, "", body); }
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function svgElement(tag, attributes = {}, text = "") {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  node.textContent = text;
  return node;
}
const nodeWidth = 200;
const nodeHeight = 104;
const columnGap = 24;
const rowHeight = 190;
const inset = 28;
const subjectNames = { algebra: "Алгебра", counting_and_probability: "Комбинаторика и вероятность", geometry: "Геометрия", intermediate_algebra: "Продвинутая алгебра", number_theory: "Теория чисел", prealgebra: "Начальная алгебра", precalculus: "Предварительный курс анализа" };
function origin(sourceId) {
  const [subject, split, number] = sourceId.split("/");
  return { subject: subjectNames[subject] ?? subject, detail: "№ " + number + " · " + split };
}
function layoutTree(schema) {
  const nodes = new Map(schema.nodes.map((node) => [node.node_id, node]));
  const positions = new Map();
  let column = 0, lastRow = 0;
  function place(id, row) {
    const children = nodes.get(id).children.map((child) => place(child, row + 1));
    const x = children.length ? (children[0] + children.at(-1)) / 2 : column++;
    positions.set(id, { x: inset + nodeWidth / 2 + x * (nodeWidth + columnGap), y: inset + row * rowHeight });
    lastRow = Math.max(lastRow, row);
    return x;
  }
  place(schema.root_id, 0);
  return { nodes, positions, width: inset * 2 + column * (nodeWidth + columnGap) - columnGap, height: inset * 2 + nodeHeight + lastRow * rowHeight };
}
function renderTree(schema, presentation = null) {
  const { nodes, positions, width, height } = layoutTree(schema);
  const filled = new Map((presentation?.nodes ?? []).map((node) => [node.node_id, node]));
  tree.setAttribute("viewBox", `0 0 ${width} ${height}`);
  tree.setAttribute("width", width);
  tree.setAttribute("height", height);
  const defs = svgElement("defs");
  const marker = svgElement("marker", { id: "composite-tree-arrow", viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 5, markerHeight: 5, orient: "auto" });
  marker.append(svgElement("path", { d: "M0 0 L8 4 L0 8 Z", class: "tree-arrow" }));
  defs.append(marker);
  const edges = svgElement("g");
  const labels = svgElement("g");
  const cards = svgElement("g");
  for (const node of nodes.values()) {
    const at = positions.get(node.node_id);
    const display = filled.get(node.node_id);
    for (const childId of node.children) {
      const child = positions.get(childId);
      const middle = (at.y + nodeHeight + child.y) / 2;
      edges.append(svgElement("path", { class: "tree-edge", d: `M ${child.x} ${child.y} C ${child.x} ${middle} ${at.x} ${middle} ${at.x} ${at.y + nodeHeight + 2}`, "marker-end": "url(#composite-tree-arrow)" }));
      const incoming = display?.incoming?.filter((input) => input.source_node === childId) ?? [];
      if (incoming.some((input) => input.value !== null)) {
        const value = incoming.map((input) => input.value).join(", ");
        const x = child.x * .82 + at.x * .18;
        const labelWidth = Math.min(nodeWidth, Math.max(42, value.length * 7 + 22));
        const label = svgElement("g", { transform: `translate(${x} ${middle + 10})`, class: "tree-flow-value", "data-source": childId, "data-target": node.node_id });
        label.append(svgElement("rect", { x: -labelWidth / 2, y: -13, width: labelWidth, height: 26, rx: 13, class: "tree-edge-label" }));
        const text = svgElement("text", { "text-anchor": "middle", y: 4, class: "tree-input" }, value);
        if (value.length > 20) { text.setAttribute("textLength", labelWidth - 18); text.setAttribute("lengthAdjust", "spacingAndGlyphs"); }
        label.append(text);
        labels.append(label);
      }
    }
    const root = node.node_id === schema.root_id;
    const source = origin(node.source_id);
    const card = svgElement("g", { transform: `translate(${at.x - nodeWidth / 2} ${at.y})`, class: "tree-task", "data-node": node.node_id, tabindex: 0, role: "button", "aria-label": "Задача " + node.number + ", " + source.subject + ", " + source.detail + (display?.answer != null ? ", ответ " + display.answer : "") });
    card.append(svgElement("rect", { width: nodeWidth, height: nodeHeight, rx: 13, class: "tree-node" + (root ? " tree-root" : "") }));
    card.append(svgElement("text", { x: 16, y: 22, class: "tree-label" }, String(node.number)));
    card.append(svgElement("text", { x: 16, y: 41, class: "tree-origin" }, source.subject));
    card.append(svgElement("text", { x: 16, y: 57, class: "tree-origin" }, source.detail));
    card.append(svgElement("text", { x: 16, y: 85, class: display?.answer != null ? "tree-node-answer" : "tree-empty-answer", ...(String(display?.answer ?? "").length > 18 ? { textLength: nodeWidth - 32, lengthAdjust: "spacingAndGlyphs" } : {}) }, display?.answer ?? "—"));
    const activate = () => document.querySelector(`[data-card-node="${node.node_id}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    card.addEventListener("click", activate);
    card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); } });
    cards.append(card);
  }
  tree.replaceChildren(svgElement("title", { id: "composite-svg-title" }, "Дерево задач"), svgElement("desc", { id: "composite-svg-description" }, "Ответы передаются снизу вверх. Номера соответствуют карточкам под деревом."), defs, edges, labels, cards);
}
function renderPresentation(presentation) {
  const token = ++presentationRevision;
  const pending = [];
  const cards = presentation.nodes.map((node) => {
    const card = element("article", "subproblem-card subproblem-" + node.kind);
    card.dataset.node = node.node_id;
    card.dataset.cardNode = node.node_id;
    const header = element("header", "subproblem-heading");
    header.append(element("span", "task-number", String(node.number)));
    header.append(element("h3", "", "Задача " + node.number));
    const source = origin(node.source_id);
    header.append(element("span", "subproblem-origin", source.subject + " · " + source.detail));
    if (node.answer != null) {
      const answer = element("div", "subproblem-answer");
      answer.append(element("span", "", "Ответ"), element("strong", "", node.answer));
      header.append(answer);
    }
    card.append(header);
    const incoming = node.incoming ?? [];
    if (incoming.length) {
      const flow = element("div", "subproblem-flow");
      for (const input of incoming) {
        const line = element("span", "flow-item");
        line.append(element("span", "flow-source", "№ " + input.source_label.replace(/^R/, "")));
        if (input.answer != null) line.append(element("span", "flow-answer", input.answer));
        line.append(element("span", "flow-arrow", "→"));
        if (input.value != null) line.append(element("span", "flow-input-name", "u" + (input.input_index + 1) + " ="));
        line.append(element("span", "parameter-slot slot-internal" + (input.value != null ? " slot-filled" : ""), input.value ?? "u" + (input.input_index + 1)));
        flow.append(line);
      }
      card.append(flow);
    }
    if (node.inputs.length) {
      const inputs = element("div", "subproblem-inputs");
      for (const input of node.inputs) {
        const chip = element("span", "input-chip");
        const value = element("span", "parameter-slot slot-" + input.role + (input.text !== null ? " slot-filled" : ""), input.text ?? input.name);
        value.dataset.parameter = input.key;
        chip.append(element("span", "input-name", input.text === null ? "" : input.name + " = "), value);
        inputs.append(chip);
      }
      card.append(inputs);
    }
    const statement = element("div", "subproblem-statement");
    pending.push(MathPresentation.render(statement, node.segments));
    card.append(statement);
    if (node.adapter_math?.length || node.notes.length || node.adapter) {
      const rules = element("div", "conversion-rules");
      for (const rule of node.adapter_math ?? []) {
        const line = element("div", "conversion-rule");
        pending.push(MathPresentation.render(line, [{ kind: "text", text: "$" + rule + "$" }]));
        rules.append(line);
      }
      if (node.adapter && !node.adapter_math?.length) rules.append(element("p", "conversion-note", node.adapter));
      for (const note of node.notes) {
        const paragraph = element("p", "conversion-note");
        pending.push(MathPresentation.render(paragraph, [{ kind: "text", text: note }]));
        rules.append(paragraph);
      }
      card.append(rules);
    }
    return card;
  });
  byId("public-template").replaceChildren(...cards);
  byId("public-template").classList.add("formatted-presentation");
  byId("presentation-note").hidden = true;
  void Promise.all(pending).then((results) => {
    if (token !== presentationRevision) return;
    byId("presentation-note").textContent = "Часть формул показана в исходной записи LaTeX.";
    byId("presentation-note").hidden = results.every(Boolean);
  });
}
function resetParameters() {
  currentInstance = undefined;
  currentVariantRaw = undefined;
  byId("export-schema").textContent = "Скачать шаблон";
  presentationRevision++;
  byId("mode").textContent = "Шаблон";
  byId("instance-result").hidden = true;
  byId("root-answer").textContent = "";
  byId("reset-parameters").disabled = true;
  byId("current-copy-status").textContent = "";
  if (currentSchema) renderTree(currentSchema.data);
  if (templatePresentation) renderPresentation(templatePresentation);
  else if (currentSchema) {
    const target = byId("public-template");
    target.classList.remove("formatted-presentation");
    target.textContent = currentSchema.data.problem_template;
    byId("presentation-note").textContent = "Показан исходный шаблон.";
    byId("presentation-note").hidden = false;
  }
}
async function showSchema(schema) {
  currentSchema = schema;
  templatePresentation = null;
  resetParameters();
  byId("presentation-note").hidden = true;
  const data = schema.data;
  byId("schema-results").hidden = false;
  byId("parameter-hint").hidden = true;
  byId("schema-meta").textContent = data.nodes.length + " задач · " + data.depth + " уровня";
  const reduced = data.actual_width < data.requested_width;
  byId("width-notice").textContent = reduced ? `Запрошена ширина ${formatNumber.format(data.requested_width)}, доступно ${formatNumber.format(data.actual_width)}. Предел демо — 128 задач в основании.` : "";
  byId("width-notice").hidden = !reduced;
  byId("reuse-notice").hidden = !(data.requested_allow_template_reuse === false && data.allow_template_reuse === true);
  const target = byId("public-template");
  target.classList.remove("formatted-presentation");
  target.textContent = data.problem_template;
  const viewport = byId("tree-viewport");
  const root = tree.querySelector(".tree-root").getBoundingClientRect();
  const frame = viewport.getBoundingClientRect();
  // An asymmetric tree's root need not lie at the center of the full canvas.
  viewport.scrollLeft += root.left + root.width / 2
    - frame.left - viewport.clientLeft - viewport.clientWidth / 2;
  viewport.scrollTop = 0;
  try {
    templatePresentation = (await postJSON("presentation", '{"schema":' + schema.raw + ',"seed":null}')).data;
    renderPresentation(templatePresentation);
  } catch {
    byId("presentation-note").textContent = "Оформление недоступно. Показан исходный текст.";
    byId("presentation-note").hidden = false;
  }
}
function showInstance(instance, presentation, raw) {
  currentInstance = instance;
  currentVariantRaw = raw;
  byId("export-schema").textContent = "Скачать задачу";
  byId("mode").textContent = "Вариант";
  byId("reset-parameters").disabled = false;
  byId("instance-result").hidden = false;
  byId("root-answer").textContent = instance.answer;
  byId("current-copy-status").textContent = "";
  renderTree(currentSchema.data, presentation);
  renderPresentation(presentation);
}
async function submit(action, body, success, message) {
  structureControls.disabled = true;
  parameterControls.disabled = true;
  showStatus(message);
  try { await success(await postJSON(action, body)); showStatus(""); }
  catch (error) { showStatus(error.message || "Не удалось выполнить вычисление.", true); }
  finally { structureControls.disabled = false; parameterControls.disabled = !currentSchema; }
}
function seedControls(prefix) {
  const mode = byId(prefix + "-seed-mode");
  const input = byId(prefix + "-seed");
  mode.addEventListener("change", () => { byId(prefix + "-seed-setting").hidden = !mode.checked; input.disabled = !mode.checked; });
  return { mode, input };
}
const structureSeed = seedControls("structure");
const parameterSeed = seedControls("parameter");
function seedForSubmission({ mode, input }) {
  if (mode.checked) return input.value;
  const random = new BigUint64Array(1);
  let seed;
  do { seed = crypto.getRandomValues(random)[0].toString(); } while (seed === input.value);
  input.value = seed;
  return seed;
}
byId("structure-form").addEventListener("submit", (event) => {
  event.preventDefault();
  void submit("build", JSON.stringify({ depth: byId("depth").valueAsNumber, width: byId("width").valueAsNumber, split: byId("split").value, seed: seedForSubmission(structureSeed), allow_template_reuse: byId("reuse").checked }), showSchema, "Подбираем схему…");
});
byId("parameter-form").addEventListener("submit", (event) => {
  event.preventDefault();
  // Exact JSON bytes, including integers beyond the JavaScript Number range.
  const body = '{"schema":' + currentSchema.raw + ',"seed":' + JSON.stringify(seedForSubmission(parameterSeed)) + '}';
  void submit("variant", body, ({ data, raw }) => showInstance(data.instance, data.presentation, raw), "Вычисляем…");
});
byId("reset-parameters").addEventListener("click", resetParameters);
async function copyText(button, text) {
  let copied = false;
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); copied = true; }
    else {
      const buffer = element("textarea", "copy-buffer");
      buffer.value = text;
      document.body.append(buffer);
      buffer.select();
      copied = document.execCommand("copy");
      buffer.remove();
      button.focus({ preventScroll: true });
    }
  } catch { copied = false; }
  button.parentElement.querySelector("output").textContent = copied ? "Скопировано" : "Выделите текст и скопируйте вручную.";
}
byId("copy-current").addEventListener("click", (event) => { void copyText(event.currentTarget, currentInstance?.problem ?? currentSchema.data.problem_template); });
byId("export-schema").addEventListener("click", () => {
  // Preserve both exact serialized payloads, including integers outside Number.
  const raw = currentVariantRaw
    ? '{"schema":' + currentSchema.raw + ',"variant":' + currentVariantRaw + '}'
    : currentSchema.raw;
  const url = URL.createObjectURL(new Blob([raw], { type: "application/json" }));
  const link = element("a");
  link.href = url;
  link.download = currentInstance
    ? "math-task-" + currentSchema.data.seed + "-" + currentInstance.parameter_seed + ".json"
    : "math-schema-" + currentSchema.data.seed + ".json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
