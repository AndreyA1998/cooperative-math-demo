import { request } from "./transport.js";
import { MathPresentation } from "./math-renderer.js";

const byId = (id) => document.getElementById("atomic-" + id);
const catalogueControls = byId("catalogue-controls");
const idSelect = byId("problem-id");
const randomButton = byId("generate-random");
const subjectSelect = byId("subject");
const splitSelect = byId("split");
const seedInput = byId("seed");
const seedMode = byId("seed-mode");
const problemText = byId("problem-text");
const parameters = byId("params");
const status = byId("status");

const subjectNames = {
  algebra: "Алгебра",
  counting_and_probability: "Комбинаторика и вероятность",
  geometry: "Геометрия",
  intermediate_algebra: "Продвинутая алгебра",
  number_theory: "Теория чисел",
  prealgebra: "Начальная алгебра",
  precalculus: "Предварительный курс анализа",
};
const formatSubject = (subject) => subjectNames[subject] ?? subject;
const formatNumber = new Intl.NumberFormat("ru");
const taskNumber = (id) => id.slice(id.lastIndexOf("/") + 1);

let catalogue = [];
let currentVariant;
let initialising = false;

async function getJSON(action, fields) {
  const query = new URLSearchParams(fields).toString();
  const { data } = await request("GET", "/api/" + action, query);
  return data;
}

function showStatus(message, error = false) {
  status.textContent = message;
  status.classList.toggle("error", error);
  status.hidden = !message;
}

function filterCatalogue(preferredId = idSelect.value) {
  const subject = subjectSelect.value;
  const split = splitSelect.value;
  const matches = catalogue
    .filter((problem) => problem.subject === subject && problem.split === split)
    .sort((a, b) => Number(taskNumber(a.id)) - Number(taskNumber(b.id)));
  const options = matches.map(({ id }) => new Option(taskNumber(id), id));
  const empty = options.length === 0;
  if (empty) {
    options.push(new Option("Нет подходящих задач", ""));
  }
  idSelect.replaceChildren(...options);
  if (matches.some(({ id }) => id === preferredId)) {
    idSelect.value = preferredId;
  }
  byId("catalogue-count").textContent = empty
    ? "В этом разделе и выборке нет задач. Выберите другой раздел или выборку."
    : "Задач в разделе: " + formatNumber.format(matches.length);
  byId("generate").disabled = empty;
  randomButton.disabled = empty;
}

function setSeedMode(checked) {
  seedMode.checked = checked;
  byId("seed-setting").hidden = !checked;
  seedInput.disabled = !checked;
}

function showVariant(variant) {
  currentVariant = variant;
  byId("placeholder").hidden = true;
  const metadata = byId("problem-meta");
  metadata.textContent = formatSubject(variant.subject) + " · №" + taskNumber(variant.id) + " · " + variant.split;
  metadata.hidden = false;
  problemText.textContent = variant.problem;
  problemText.hidden = false;

  const answer = byId("answer");
  byId("answer-value").textContent = variant.answer;
  answer.hidden = false;

  const rows = Object.entries(variant.parameters).map(([name, value]) => {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = name;
    detail.textContent = variant.parameter_display?.[name] ?? JSON.stringify(value);
    row.append(term, detail);
    return row;
  });
  parameters.replaceChildren(...rows);
  parameters.hidden = false;
  byId("params-placeholder").hidden = true;
  const version = byId("version");
  version.textContent = "Версия генератора " + variant.generator_version;
  version.hidden = false;
  seedInput.value = variant.seed;

  const url = new URL(window.location.href);
  url.search = new URLSearchParams({ id: variant.id, seed: variant.seed });
  window.history.replaceState(null, "", url);

  const note = byId("renderer-note");
  note.hidden = true;
  void MathPresentation.render(problemText, [{ kind: "text", text: variant.problem }]).then((rendered) => {
    if (currentVariant !== variant) return;
    note.textContent = "Формулы, которые не удалось оформить, показаны в исходной записи LaTeX.";
    note.hidden = rendered;
  });
}

async function generateVariant(seed) {
  if (!idSelect.value || catalogueControls.disabled) {
    return;
  }
  const fields = { id: idSelect.value };
  if (seed !== undefined) {
    fields.seed = seed;
  }
  catalogueControls.disabled = true;
  showStatus("Генерируем вариант…");
  try {
    const variant = await getJSON("generate", fields);
    showVariant(variant);
    showStatus("");
  } catch (error) {
    showStatus(error.message || "Не удалось сгенерировать вариант.", true);
  } finally {
    catalogueControls.disabled = false;
  }
}

async function init() {
  if (initialising || catalogue.length) return;
  initialising = true;
  try {
    const data = await getJSON("catalogue");
    catalogue = data.problems;
  } catch {
    initialising = false;
    byId("catalogue-count").textContent = "Каталог недоступен.";
    showStatus("Не удалось загрузить каталог. Повторите загрузку в строке состояния выше.", true);
    return;
  }

  initialising = false;
  showStatus("");
  const subjects = new Set(catalogue.map(({ subject }) => subject));
  for (const subject of subjects) {
    subjectSelect.add(new Option(formatSubject(subject), subject));
  }
  const query = new URLSearchParams(window.location.search);
  const requestedId = query.get("id");
  const requestedTask = catalogue.find(({ id }) => id === requestedId);
  subjectSelect.value = requestedTask?.subject ?? (subjects.has("prealgebra") ? "prealgebra" : subjectSelect.value);
  splitSelect.value = requestedTask?.split ?? "test";
  filterCatalogue(requestedTask?.id ?? "prealgebra/test/11");
  catalogueControls.disabled = false;

  if (requestedId && !requestedTask) {
    showStatus("Задача из ссылки отсутствует в каталоге.", true);
  } else if (requestedId && query.has("seed")) {
    setSeedMode(true);
    seedInput.value = query.get("seed");
    await generateVariant(seedInput.value);
  }
}

seedMode.addEventListener("change", () => setSeedMode(seedMode.checked));
subjectSelect.addEventListener("change", () => filterCatalogue());
splitSelect.addEventListener("change", () => filterCatalogue());

byId("generator").addEventListener("submit", (event) => {
  event.preventDefault();
  void generateVariant(seedMode.checked ? seedInput.value : undefined);
});
randomButton.addEventListener("click", () => {
  setSeedMode(false);
  idSelect.selectedIndex = Math.floor(Math.random() * idSelect.options.length);
  void generateVariant();
});
window.addEventListener("math-runtime-ready", () => { void init(); });
void init();
