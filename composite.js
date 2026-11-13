import { request } from "./transport.js";
import { MathPresentation } from "./math-renderer.js";

const byId = (id) => document.getElementById("composite-" + id);
const tree = byId("tree");
const status = byId("status");
const widthNotice = byId("width-notice");
const formatNumber = new Intl.NumberFormat("ru");
const maximumWidth = 128;
const structureControls = byId("structure-controls");
const parameterControls = byId("parameter-controls");
let currentSchema;
let currentInstance;
const presentationRequests = new WeakMap();

function showStatus(message, isError = false) {
  status.textContent = message;
  status.classList.toggle("error", isError);
  status.hidden = !message;
}

async function postJSON(action, body) {
  return request("POST", "/api/composite/" + action, "", body);
}

function svgElement(name, attributes = {}, content = "") {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [attribute, value] of Object.entries(attributes)) {
    element.setAttribute(attribute, value);
  }
  element.textContent = content;
  return element;
}

const nodeWidth = 246;
const nodeHeight = 54;
const columnGap = 20;
const rowHeight = 146;
const inset = 22;

function layoutTree(schema) {
  const nodes = new Map(schema.nodes.map((node) => [node.node_id, node]));
  const positions = new Map();
  let nextColumn = 0;
  let maxRow = 0;

  function place(nodeId, row) {
    const children = nodes.get(nodeId).children;
    const columns = children.map((childId) => place(childId, row + 1));
    const column = columns.length
      ? (columns[0] + columns[columns.length - 1]) / 2
      : nextColumn++;
    positions.set(nodeId, {
      x: inset + nodeWidth / 2 + column * (nodeWidth + columnGap),
      y: inset + row * rowHeight,
    });
    maxRow = Math.max(maxRow, row);
    return column;
  }

  place(schema.root_id, 0);
  return {
    nodes, positions,
    width: 2 * inset + nextColumn * (nodeWidth + columnGap) - columnGap,
    height: 2 * inset + nodeHeight + maxRow * rowHeight,
  };
}

const shorten = (text, length) => text.length > length ? text.slice(0, length - 1) + "…" : text;
const nodeLabel = (node) => node.label ?? node.node_id;

function renderTree(schema) {
  const { nodes, positions, width, height } = layoutTree(schema);
  tree.setAttribute("viewBox", [0, 0, width, height].join(" "));
  tree.setAttribute("width", width);
  tree.setAttribute("height", height);

  const defs = svgElement("defs");
  const arrow = svgElement("marker", {
    id: "composite-tree-arrow", viewBox: "0 0 8 8", refX: 7, refY: 4,
    markerWidth: 7, markerHeight: 7, orient: "auto",
  });
  arrow.append(svgElement("path", { d: "M0 0 L8 4 L0 8 Z", class: "tree-arrow" }));
  defs.append(arrow);

  const edges = svgElement("g");
  const labels = svgElement("g");
  const cards = svgElement("g");
  for (const parent of nodes.values()) {
    const at = positions.get(parent.node_id);
    const portCount = parent.bindings.length;
    const incoming = new Map(parent.children.map((child) => [child, []]));
    parent.bindings.forEach((binding, index) => {
      const child = positions.get(binding.source_node);
      const portX = at.x - nodeWidth / 2 + nodeWidth * (index + 1) / (portCount + 1);
      const portY = at.y + nodeHeight + 1;
      const labelY = child.y - 55;
      const controlY = portY + (labelY - portY) * .55;
      edges.append(svgElement("path", {
        class: "tree-edge",
        d: `M ${child.x} ${child.y} V ${labelY} C ${child.x} ${controlY} ${portX} ${controlY} ${portX} ${portY}`,
        "marker-end": "url(#composite-tree-arrow)",
      }));
      incoming.get(binding.source_node).push(binding);
    });
    for (const [childId, bindings] of incoming) {
      const child = positions.get(childId);
      const source = nodeLabel(nodes.get(childId));
      const joint = parent.adapter?.kind === "joint_groups";
      const portName = (binding) => joint ? "u" + (binding.input_index + 1) : binding.input_name;
      const destination = nodeLabel(parent) + "." + bindings.map(portName).join(", ");
      const operation = bindings[0].operator.kind;
      const rules = bindings.map((binding) => portName(binding) + " ← " + binding.operator.kind);
      if (joint) rules.push("Совместный адаптер формирует допустимый набор параметров родителя");
      const label = svgElement("g", { transform: `translate(${child.x} ${child.y - 55})` });
      label.append(
        svgElement("title", {}, source + " → " + nodeLabel(parent) + "\n" + rules.join("\n")),
        svgElement("rect", { x: -112, y: 0, width: 224, height: 38, rx: 8, class: "tree-edge-label" }),
        svgElement("text", { x: 0, y: 15, "text-anchor": "middle", class: "tree-input" },
          shorten("→ " + destination, 28)),
        svgElement("text", { x: 0, y: 30, "text-anchor": "middle", class: "tree-operator" },
          operation),
      );
      labels.append(label);
    }

    const root = parent.node_id === schema.root_id;
    const card = svgElement("g", { transform: `translate(${at.x - nodeWidth / 2} ${at.y})` });
    card.append(
      svgElement("title", {}, nodeLabel(parent) + " · " + parent.source_id),
      svgElement("rect", {
        width: nodeWidth, height: nodeHeight, rx: 9, class: root ? "tree-node tree-root" : "tree-node",
      }),
      svgElement("text", { x: 12, y: 23, class: root ? "tree-label tree-root-label" : "tree-label" },
        nodeLabel(parent)),
      svgElement("text", { x: 12, y: 41, class: root ? "tree-source tree-root-source" : "tree-source" },
        parent.source_id),
    );
    cards.append(card);
  }
  tree.replaceChildren(
    svgElement("title", { id: "composite-svg-title" }, "Дерево подзадач"),
    svgElement("desc", { id: "composite-svg-description" },
      "Корень расположен вверху. Каждый ответ поступает в отдельный вход совместного адаптера родителя."),
    defs, edges, labels, cards,
  );
  const viewport = byId("tree-viewport");
  const rootX = positions.get(schema.root_id).x;
  viewport.scrollLeft = rootX - viewport.clientWidth / 2;
  viewport.scrollTop = 0;
}

async function showSchema(schema) {
  const { data } = schema;
  currentSchema = schema;
  resetParameters();
  byId("schema-results").hidden = false;
  byId("parameter-hint").hidden = true;
  byId("schema-meta").textContent = [
    data.split,
    "глубина " + data.depth,
    "ширина " + formatNumber.format(data.actual_width),
    "узлов " + data.nodes.length,
  ].join(" · ");
  const reducedWidth = data.actual_width < data.requested_width;
  widthNotice.textContent = reducedWidth
    ? "Вы запросили ширину " + formatNumber.format(data.requested_width) +
      ", построена схема шириной " + formatNumber.format(data.actual_width) +
      ". Возможная ширина зависит от глубины и доступных задач. Демо поддерживает до " +
      formatNumber.format(maximumWidth) + " задач в основании."
    : "";
  widthNotice.hidden = !reducedWidth;
  byId("reuse-notice").hidden = !(
    data.requested_allow_template_reuse === false && data.allow_template_reuse === true
  );
  byId("public-template").classList.remove("formatted-presentation");
  byId("public-template").textContent = data.problem_template;
  byId("template-copy-status").textContent = "";
  renderTree(data);
  await showPresentation(byId("public-template"), null);
}

function element(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}

function renderPresentation(target, presentation) {
  const content = [];
  const typesetting = [];
  for (const paragraph of presentation.introduction) {
    const intro = element("p", "presentation-introduction");
    typesetting.push(MathPresentation.render(intro, [{ kind: "text", text: paragraph }]));
    content.push(intro);
  }
  for (const node of presentation.nodes) {
    const card = element("article", "subproblem-card subproblem-" + node.kind);
    card.dataset.node = node.node_id;
    const heading = element("header", "subproblem-heading");
    const title = element("h3", "", node.label);
    const provenance = element("span", "subproblem-source", node.source_id);
    const kind = element("span", "subproblem-kind", node.kind === "bottom" ? "Основание" : "Из ответов подзадач");
    heading.append(title, provenance, kind);
    card.append(heading);
    if (node.inputs.length) {
      const inputs = element("div", "subproblem-inputs");
      for (const input of node.inputs) {
        const chip = element("span", "input-chip");
        const value = element("span", "parameter-slot slot-external" + (input.text !== null ? " slot-filled" : ""), input.text ?? input.key);
        value.dataset.parameter = input.key;
        chip.append(element("span", "input-name", input.name + " = "), value);
        inputs.append(chip);
      }
      card.append(inputs);
    }
    const statement = element("div", "subproblem-statement");
    typesetting.push(MathPresentation.render(statement, node.segments));
    card.append(statement);
    for (const note of node.notes) {
      const paragraph = element("p", "subproblem-note");
      typesetting.push(MathPresentation.render(paragraph, [{ kind: "text", text: note }]));
      card.append(paragraph);
    }
    if (node.adapter) {
      const adapter = element("details", "adapter-details");
      adapter.append(element("summary", "", "Как получаются входы"));
      if (node.adapter_math?.length) {
        for (const rule of node.adapter_math) {
          const line = element("div", "adapter-rule");
          typesetting.push(MathPresentation.render(line, [{ kind: "text", text: "\\[" + rule + "\\]" }]));
          adapter.append(line);
        }
      } else {
        adapter.append(element("div", "adapter-text", node.adapter));
      }
      card.append(adapter);
    }
    content.push(card);
  }
  const conclusion = element("p", "presentation-conclusion");
  typesetting.push(MathPresentation.render(conclusion, [{ kind: "text", text: presentation.conclusion }]));
  content.push(conclusion);
  target.replaceChildren(...content);
  target.classList.add("formatted-presentation");
  return Promise.all(typesetting).then((results) => results.every(Boolean));
}

async function showPresentation(target, seed, suppliedPresentation = null) {
  const schema = currentSchema;
  const request = {};
  presentationRequests.set(target, request);
  const current = () => currentSchema === schema && presentationRequests.get(target) === request;
  const body = '{"schema":' + schema.raw + ',"seed":' + JSON.stringify(seed) + '}';
  const note = byId(target === byId("public-template") ? "presentation-note" : "instance-presentation-note");
  note.hidden = true;
  try {
    const data = suppliedPresentation ?? (await postJSON("presentation", body)).data;
    if (!current()) return;
    note.textContent = "Загружаем оформление формул…";
    note.hidden = false;
    void renderPresentation(target, data).then((rendered) => {
      if (!current()) return;
      note.textContent = "Формулы, которые не удалось оформить, показаны в исходной записи LaTeX.";
      note.hidden = rendered;
    });
  } catch {
    if (!current()) return;
    // Canonical plain text remains usable when optional presentation is unavailable.
    note.textContent = "Оформление условия недоступно. Ниже сохранён исходный текст задачи.";
    note.hidden = false;
  }
}

function resetParameters() {
  currentInstance = undefined;
  presentationRequests.delete(byId("public-instance"));
  byId("instance-presentation-note").hidden = true;
  byId("instance-result").hidden = true;
  byId("instance-link").hidden = true;
  byId("public-instance").replaceChildren();
  byId("instance-copy-status").textContent = "";
  byId("root-answer").textContent = "";
  byId("solution-trace").replaceChildren();
  byId("solution").open = false;
  byId("reset-parameters").disabled = true;
}

byId("reset-parameters").addEventListener("click", resetParameters);

async function showInstance(instance, presentation) {
  currentInstance = instance;
  byId("reset-parameters").disabled = false;
  byId("public-instance").classList.remove("formatted-presentation");
  byId("public-instance").textContent = instance.problem;
  byId("instance-copy-status").textContent = "";
  byId("solution").open = false;
  byId("root-answer").textContent = "Ответ " + instance.answer;
  const nodes = new Map(currentSchema.data.nodes.map((node) => [node.node_id, nodeLabel(node)]));
  const trace = instance.trace.map((node) => {
    const line = document.createElement("li");
    const code = document.createElement("code");
    code.textContent = node.parameters_text + " → " + node.answer;
    line.append(nodes.get(node.node_id) + " · ", code);
    return line;
  });
  byId("solution-trace").replaceChildren(...trace);
  byId("instance-result").hidden = false;
  byId("instance-link").hidden = false;
  await showPresentation(byId("public-instance"), instance.parameter_seed, presentation);
}

async function submit(action, body, onSuccess, message) {
  structureControls.disabled = true;
  parameterControls.disabled = true;
  showStatus(message);
  try {
    await onSuccess(await postJSON(action, body));
    showStatus("");
  } catch (error) {
    showStatus(error.message || "Запрос не удалось выполнить.", true);
  } finally {
    structureControls.disabled = false;
    parameterControls.disabled = !currentSchema;
  }
}

function seedControls(prefix) {
  const mode = byId(prefix + "-seed-mode");
  const setting = byId(prefix + "-seed-setting");
  const input = byId(prefix + "-seed");
  mode.addEventListener("change", () => {
    setting.hidden = !mode.checked;
    input.disabled = !mode.checked;
  });
  return { mode, input };
}

const structureSeed = seedControls("structure");
const parameterSeed = seedControls("parameter");

function seedForSubmission({ mode, input }) {
  if (mode.checked) {
    return input.value;
  }
  const previousSeed = input.value.trim();
  const random = new BigUint64Array(1);
  let seed;
  do {
    seed = crypto.getRandomValues(random)[0].toString();
  } while (seed === previousSeed);
  input.value = seed;
  return seed;
}

byId("structure-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const body = JSON.stringify({
    depth: byId("depth").valueAsNumber,
    width: byId("width").valueAsNumber,
    split: byId("split").value,
    seed: seedForSubmission(structureSeed),
    allow_template_reuse: byId("reuse").checked,
  });
  void submit("build", body, showSchema, "Подбираем схему…");
});

byId("parameter-form").addEventListener("submit", (event) => {
  event.preventDefault();
  // Reuse the original JSON bytes: parsed schema integers may exceed JS precision.
  const seed = JSON.stringify(seedForSubmission(parameterSeed));
  const body = '{"schema":' + currentSchema.raw + ',"seed":' + seed + '}';
  void submit("variant", body, ({ data }) => showInstance(data.instance, data.presentation), "Готовим вариант задачи…");
});

function copyWithSelection(text) {
  const buffer = document.createElement("textarea");
  const active = document.activeElement;
  buffer.className = "copy-buffer";
  buffer.readOnly = true;
  buffer.value = text;
  document.body.append(buffer);
  buffer.select();
  try {
    return document.execCommand("copy");
  } finally {
    buffer.remove();
    active?.focus({ preventScroll: true });
  }
}

async function copyText(button, text) {
  let copied = false;
  try {
    if (!navigator.clipboard?.writeText) {
      copied = copyWithSelection(text);
    } else {
      await navigator.clipboard.writeText(text);
      copied = true;
    }
  } catch {
    copied = false;
  }
  const output = button.parentElement.querySelector("output");
  output.textContent = copied ? "Скопировано." : "Выделите текст и скопируйте вручную.";
}

byId("copy-template").addEventListener("click", (event) => {
  void copyText(event.currentTarget, currentSchema.data.problem_template);
});
byId("copy-instance").addEventListener("click", (event) => {
  void copyText(event.currentTarget, currentInstance.problem);
});
byId("export-schema").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([currentSchema.raw], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "math-schema-" + currentSchema.data.seed + ".json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

// Scrolling within the composite panel must keep the tab hash intact.
byId("instance-link").querySelector("a").addEventListener("click", (event) => {
  event.preventDefault();
  byId("instance-result").scrollIntoView({ behavior: "smooth", block: "start" });
});
