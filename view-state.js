// Keep exact task state for reloads, without selecting a task on a fresh visit.
const navigation = performance.getEntriesByType("navigation")[0]?.type;
const resuming = navigation === "reload" || navigation === "back_forward";
let tab;
try {
  tab = resuming && sessionStorage.getItem("math-demo-tab");
  if (!tab) { tab = crypto.randomUUID(); sessionStorage.setItem("math-demo-tab", tab); }
} catch { tab = null; }
const database = tab ? new Promise((resolve) => {
  let request;
  try { request = indexedDB.open("math-demo-view-state", 1); } catch { resolve(null); return; }
  request.onupgradeneeded = () => request.result.createObjectStore("views", { keyPath: "key" });
  request.onerror = () => resolve(null);
  request.onblocked = () => resolve(null);
  request.onsuccess = () => resolve(request.result);
}) : Promise.resolve(null);
let writing = Promise.resolve();
let resetting = false;
export async function readViewState(view) {
  if (!resuming || !tab) return null;
  const db = await database;
  if (!db) return null;
  return new Promise(resolve => {
    const transaction = db.transaction("views", "readonly");
    const request = transaction.objectStore("views").get(tab + ":" + view);
    request.onsuccess = () => resolve(request.result?.state ?? null);
    request.onerror = () => resolve(null);
  });
}
export function saveViewState(view, state) {
  if (resetting) return writing;
  // Queue captured snapshots so a slow old write cannot replace a newer task.
  writing = writing.then(async () => {
    const db = await database;
    if (!db) return;
    await new Promise(resolve => {
      const transaction = db.transaction("views", "readwrite");
      const store = transaction.objectStore("views");
      store.put({ key: tab + ":" + view, updated: Date.now(), state });
      transaction.oncomplete = transaction.onerror = transaction.onabort = resolve;
      // Only our expired snapshots are removed; no browser-wide storage reset.
      const cursor = store.openCursor();
      cursor.onsuccess = () => {
        const entry = cursor.result;
        if (!entry) return;
        if (entry.value.updated < Date.now() - 86400000) entry.delete();
        entry.continue();
      };
    });
  }).catch(() => {});
  return writing;
}

async function storedRecord(key) {
  const db = await database;
  if (!db) return null;
  return new Promise(resolve => {
    const request = db.transaction("views", "readonly").objectStore("views").get(key);
    request.onsuccess = () => resolve(request.result ?? null);
    request.onerror = () => resolve(null);
  });
}
export async function readCatalogueCache() {
  try {
    const response = await fetch(new URL("./runtime.json", import.meta.url), { cache: "no-cache" });
    if (!response.ok) return {};
    const { sha256 } = await response.json();
    const saved = await storedRecord("catalogue");
    return { version: sha256, problems: saved?.version === sha256 ? saved.problems : null };
  } catch { return {}; }
}
export async function saveCatalogueCache(version, problems) {
  const db = await database;
  if (!db || !version) return;
  await new Promise(resolve => {
    const transaction = db.transaction("views", "readwrite");
    transaction.objectStore("views").put({ key: "catalogue", version, problems, updated: Date.now() });
    transaction.oncomplete = transaction.onerror = transaction.onabort = resolve;
  });
}
export function flushViewState() { return writing; }

export async function resetViewState() {
  // Finish already queued writes and refuse late results from in-flight requests.
  resetting = true;
  await writing;
  try {
    const db = await database;
    if (db && tab) await new Promise(resolve => {
      const transaction = db.transaction("views", "readwrite");
      const store = transaction.objectStore("views");
      store.delete(tab + ":atomic");
      store.delete(tab + ":composite");
      transaction.oncomplete = transaction.onerror = transaction.onabort = resolve;
    });
  } finally {
    try { sessionStorage.removeItem("math-demo-tab"); } catch {}
  }
}
