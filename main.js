import { resetViewState } from "./view-state.js";
import "./app.js";
import "./composite.js";

const tabs = [...document.querySelectorAll('[role="tab"][data-view]')];

function selectView(view, { updateURL = false, focus = false } = {}) {
  for (const tab of tabs) {
    const selected = tab.dataset.view === view;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !selected;
    if (selected && focus) tab.focus({ preventScroll: true });
  }
  document.title = (view === "composite" ? "Дерево задач" : "Задача") + " — Cooperative Math";
  window.dispatchEvent(new CustomEvent("math-view-change", { detail: view }));
  if (updateURL) {
    const url = new URL(window.location.href);
    url.hash = view;
    if (url.href !== window.location.href) window.history.pushState(null, "", url);
  }
}

function viewFromURL() {
  // Existing task query parameters belong to the atomic panel and survive tabs.
  return window.location.hash.startsWith("#composite") ? "composite" : "atomic";
}

for (const [index, tab] of tabs.entries()) {
  tab.addEventListener("click", () => selectView(tab.dataset.view, { updateURL: true }));
  tab.addEventListener("keydown", (event) => {
    let next;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    selectView(tabs[next].dataset.view, { updateURL: true, focus: true });
  });
}
window.addEventListener("hashchange", () => selectView(viewFromURL()));
window.addEventListener("popstate", () => selectView(viewFromURL()));
selectView(viewFromURL());

const brand = document.querySelector(".brand");
brand.addEventListener("click", async (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  brand.setAttribute("aria-busy", "true");
  try { await resetViewState(); }
  finally { window.location.replace(new URL("./", window.location.href)); }
});
