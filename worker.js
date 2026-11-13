// Pin the Python runtime. This worker has no access to the page DOM.
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';
const progress = message => self.postMessage({type: 'progress', message});
const fail = error => self.postMessage({type: 'fatal', message:
  'Не удалось подготовить генератор. Проверьте подключение и повторите загрузку. ' + error.message});

async function checkedFetch(url) {
  const response = await fetch(url, {signal: AbortSignal.timeout(120000)});
  if (!response.ok) throw new Error(`Загрузка: HTTP ${response.status}`);
  return response;
}

const ready = (async () => {
  progress('Первый запуск: загружаем вычислитель и задачи. Это может занять около минуты…');
  const [{loadPyodide}, manifest] = await Promise.all([
    import(PYODIDE + 'pyodide.mjs'),
    checkedFetch(new URL('./runtime.json', import.meta.url)).then(response => response.json()),
  ]);
  if (manifest.format !== 'math-demo-runtime-1') throw new Error('Неизвестная версия пакета.');
  const [pyodide, archive] = await Promise.all([
    loadPyodide({indexURL: PYODIDE}),
    checkedFetch(new URL('./runtime.zip', import.meta.url)).then(response => response.arrayBuffer()),
  ]);
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', archive))]
    .map(value => value.toString(16).padStart(2, '0')).join('');
  if (digest !== manifest.sha256 || archive.byteLength !== manifest.bytes) throw new Error('Пакет обновился. Повторите загрузку.');
  progress('Подготавливаем каталог задач…');
  pyodide.unpackArchive(archive, 'zip', {extractDir: '/workspace'});
  pyodide.runPython("import sys\nsys.path.insert(0, '/workspace')");
  const api = pyodide.pyimport('math_demo.api');
  // Keep an owned proxy: destroying the module also destroys borrowed attributes.
  const dispatch = api.dispatch_json.copy();
  api.destroy();
  self.postMessage({type: 'ready'});
  return dispatch;
})();
ready.catch(fail);

// Serialize calls explicitly; Python state and caches belong to this one worker.
let queue = Promise.resolve();
self.onmessage = ({data}) => {
  queue = queue.then(async () => {
    const dispatch = await ready;
    const result = dispatch(data.method, data.path, data.query, data.body ?? undefined);
    try {
      const [status, raw] = result.toJs();
      self.postMessage({id: data.id, status, raw});
    } finally { result.destroy(); }
  }).catch(fail);
};
