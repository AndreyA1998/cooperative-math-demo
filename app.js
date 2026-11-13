import { request } from "./transport.js";
import { MathPresentation } from "./math-renderer.js";

const byId = (id) => document.getElementById("atomic-" + id);
const catalogueControls = byId("catalogue-controls");
const idSelect = byId("problem-id");
const subjectSelect = byId("subject");
const splitSelect = byId("split");
const seedInput = byId("seed");
const seedMode = byId("seed-mode");
const subjectNames = { algebra: "Алгебра", counting_and_probability: "Комбинаторика и вероятность", geometry: "Геометрия", intermediate_algebra: "Продвинутая алгебра", number_theory: "Теория чисел", prealgebra: "Начальная алгебра", precalculus: "Предварительный курс анализа" };
const taskNumber = (id) => id.slice(id.lastIndexOf("/") + 1);
const groups = new Map();
const tasks = new Map();
let catalogue = [];
let activeGroup;
let activeId;
let initialising = false;
let revision = 0;

async function getJSON(action, fields) {
  return (await request("GET", "/api/" + action, new URLSearchParams(fields).toString())).data;
}
function showStatus(message, error = false) {
  byId("status").textContent = message;
  byId("status").classList.toggle("error", error);
  byId("status").hidden = !message;
}
function setSeedMode(checked) {
  seedMode.checked = checked;
  byId("seed-setting").hidden = !checked;
  seedInput.disabled = !checked;
}
function remember() {
  const state = tasks.get(activeId);
  if (state) Object.assign(state, { seed: seedInput.value, seedMode: seedMode.checked });
  if (activeGroup && activeId) groups.set(activeGroup, activeId);
}
function filterCatalogue(preferredId) {
  activeGroup = subjectSelect.value + "/" + splitSelect.value;
  const matches = catalogue.filter((entry) => entry.subject === subjectSelect.value && entry.split === splitSelect.value)
    .sort((a, b) => Number(taskNumber(a.id)) - Number(taskNumber(b.id)));
  idSelect.replaceChildren(...matches.map(({ id }) => new Option(taskNumber(id), id)));
  const remembered = preferredId ?? groups.get(activeGroup);
  if (matches.some(({ id }) => id === remembered)) idSelect.value = remembered;
  byId("catalogue-count").textContent = matches.length ? `${new Intl.NumberFormat("ru").format(matches.length)} задач в разделе` : "В этом разделе нет задач.";
  byId("generate").disabled = !matches.length;
  byId("generate-random").disabled = !matches.length;
}
function updateURL(state) {
  const url = new URL(window.location.href);
  url.search = new URLSearchParams(state.variant ? { id: activeId, seed: state.variant.seed } : { id: activeId });
  window.history.replaceState(null, "", url);
}
function renderTask(state) {
  const token = ++revision;
  byId("problem-card").hidden = false;
  const variant = state.variant;
  const content = variant ?? state.template;
  const presentation = content.presentation;
  const text = byId("problem-text");
  byId("placeholder").hidden = true;
  text.hidden = false;
  byId("mode").textContent = variant ? "Задача" : "Шаблон";
  byId("problem-title").textContent = "Задача";
  byId("answer-value").textContent = variant?.answer ?? "—";
  byId("reset").disabled = !variant;
  byId("download").hidden = false;
  byId("download").textContent = variant ? "Скачать задачу" : "Скачать шаблон";
  byId("copy-status").textContent = "";
  byId("copy").disabled = false;
  const chips = (presentation?.inputs ?? []).map((input) => {
    const chip = document.createElement("span");
    chip.className = "input-chip";
    const label = document.createElement("span");
    label.className = "input-name";
    label.textContent = input.text === null ? "" : input.name + " = ";
    const value = document.createElement("span");
    value.className = "parameter-slot slot-external" + (input.text !== null ? " slot-filled" : "");
    value.dataset.parameter = input.key;
    value.textContent = input.text ?? input.name;
    chip.append(label, value);
    return chip;
  });
  byId("params").replaceChildren(...chips);
  byId("params").hidden = !chips.length;
  setSeedMode(state.seedMode ?? false);
  seedInput.value = state.seed ?? "";
  byId("renderer-note").hidden = true;
  const segments = presentation?.segments
    ?? [{ kind: "text", text: content.problem ?? content.problem_template ?? content.template ?? "" }];
  void MathPresentation.render(text, segments).then((rendered) => {
    if (token !== revision) return;
    byId("renderer-note").textContent = "Часть формул показана в исходной записи LaTeX.";
    byId("renderer-note").hidden = rendered;
  });
  updateURL(state);
}
async function selectTask() {
  remember();
  activeId = idSelect.value;
  if (!activeId) return;
  idSelect.querySelector('option[value=""]')?.remove();
  byId("problem-card").hidden = false;
  byId("generate").disabled = false;
  groups.set(activeGroup, activeId);
  let state = tasks.get(activeId);
  if (state) { renderTask(state); showStatus(""); return; }
  const id = activeId;
  const token = ++revision;
  byId("problem-text").hidden = true;
  byId("params").hidden = true;
  byId("placeholder").hidden = false;
  byId("placeholder").textContent = "Загружаем шаблон…";
  byId("problem-title").textContent = "Задача";
  byId("mode").textContent = "Шаблон";
  byId("answer-value").textContent = "—";
  byId("reset").disabled = true;
  byId("copy").disabled = true;
  byId("download").hidden = true;
  byId("renderer-note").hidden = true;
  catalogueControls.disabled = true;
  showStatus("Загружаем шаблон…");
  try {
    const template = await getJSON("template", { id });
    state = { template, variant: null, seed: "", seedMode: false };
    tasks.set(id, state);
    if (id === activeId && revision === token) { renderTask(state); showStatus(""); }
  } catch (error) {
    if (id === activeId) {
      byId("placeholder").textContent = "Нажмите «Заполнить числа», чтобы повторить загрузку шаблона.";
      showStatus(error.message || "Не удалось загрузить шаблон.", true);
    }
  } finally { catalogueControls.disabled = false; }
}
async function changeFilter() {
  remember();
  // Clear the old identity before selecting within the next subject/split group.
  activeId = undefined;
  filterCatalogue();
  await selectTask();
}
async function generateVariant(seed) {
  if (!activeId || catalogueControls.disabled) return;
  if (!tasks.has(activeId)) {
    await selectTask();
    if (!tasks.has(activeId)) return;
    const recovered = tasks.get(activeId);
    recovered.seedMode = seed !== undefined;
    if (seed !== undefined) recovered.seed = seed;
    setSeedMode(recovered.seedMode);
    seedInput.value = recovered.seed;
  }
  remember();
  const id = activeId;
  const fields = seed === undefined ? { id } : { id, seed };
  catalogueControls.disabled = true;
  showStatus("Вычисляем…");
  try {
    const variant = await getJSON("generate", fields);
    const state = tasks.get(id);
    state.variant = variant;
    state.seed = variant.seed;
    if (activeId === id) renderTask(state);
    showStatus("");
  } catch (error) { showStatus(error.message || "Не удалось заполнить числа.", true); }
  finally { catalogueControls.disabled = false; }
}
async function init() {
  if (initialising || catalogue.length) return;
  initialising = true;
  try {
    catalogue = (await getJSON("catalogue")).problems;
    const subjects = [...new Set(catalogue.map(({ subject }) => subject))];
    subjectSelect.replaceChildren(...subjects.map((subject) => new Option(subjectNames[subject] ?? subject, subject)));
    const query = new URLSearchParams(window.location.search);
    const requestedId = query.get("id");
    const requested = catalogue.find(({ id }) => id === requestedId);
    subjectSelect.value = requested?.subject ?? (subjects.includes("prealgebra") ? "prealgebra" : subjects[0]);
    splitSelect.value = requested?.split ?? "test";
    filterCatalogue(requested?.id);
    catalogueControls.disabled = false;
    setSeedMode(false);
    if (requested) {
      await selectTask();
    } else {
      const empty = new Option("Выберите задачу", "", true, true);
      empty.disabled = true;
      idSelect.prepend(empty);
      idSelect.value = "";
      byId("generate").disabled = true;
      byId("copy").disabled = true;
      byId("problem-card").hidden = true;
    }
    showStatus("");
    if (requested && query.has("seed")) {
      setSeedMode(true);
      seedInput.value = query.get("seed");
      await generateVariant(seedInput.value);
    } else if (requestedId && !requested) showStatus("Задача из ссылки отсутствует в каталоге.", true);
  } catch { showStatus("Не удалось загрузить каталог. Повторите загрузку выше.", true); }
  finally { initialising = false; }
}
seedMode.addEventListener("change", () => { setSeedMode(seedMode.checked); remember(); });
subjectSelect.addEventListener("change", () => { void changeFilter(); });
splitSelect.addEventListener("change", () => { void changeFilter(); });
idSelect.addEventListener("change", () => { void selectTask(); });
byId("generator").addEventListener("submit", (event) => { event.preventDefault(); void generateVariant(seedMode.checked ? seedInput.value : undefined); });
byId("generate-random").addEventListener("click", async () => {
  remember();
  idSelect.querySelector('option[value=""]')?.remove();
  idSelect.selectedIndex = Math.floor(Math.random() * idSelect.options.length);
  await selectTask();
  const state = tasks.get(activeId);
  if (!state) return;
  state.variant = null;
  state.seedMode = false;
  renderTask(state);
});
byId("reset").addEventListener("click", () => {
  remember();
  const state = tasks.get(activeId);
  if (!state) return;
  state.variant = null;
  renderTask(state);
});
function currentTaskText() {
  const state = tasks.get(activeId);
  if (!state) return null;
  if (state.variant) return state.variant.problem;
  if (state.template.problem_template != null) return state.template.problem_template;
  const presentation = state.template.presentation;
  return [presentation.segments.map((part) => part.symbolic_math ?? part.text).join(""),
    ...(presentation.notes ?? [])].filter(Boolean).join("\n\n");
}
byId("download").addEventListener("click", () => {
  const text = currentTaskText();
  if (text == null) return;
  const variant = tasks.get(activeId).variant;
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = variant ? "math-task-" + variant.seed + ".txt" : "math-template-" + taskNumber(activeId) + ".txt";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
byId("copy").addEventListener("click", async () => {
  const text = currentTaskText();
  if (text == null) return;
  try { await navigator.clipboard.writeText(text); byId("copy-status").textContent = "Скопировано"; }
  catch { byId("copy-status").textContent = "Не удалось скопировать. Выделите условие вручную."; }
});
window.addEventListener("math-runtime-ready", () => { void init(); });
void init();
