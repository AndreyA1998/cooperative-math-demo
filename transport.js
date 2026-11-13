import {WorkerRPC} from './rpc.js';

const status = document.getElementById('runtime-status');
const retry = document.getElementById('runtime-retry');
const rpc = new WorkerRPC(
  () => new Worker(new URL('./worker.js', import.meta.url), {type: 'module'}),
  state => {
    if (status) {
      status.textContent = state.message || (state.type === 'ready' ? 'Готово · вычисления выполняются в вашем браузере' : 'Подготовка…');
      status.classList.toggle('error', state.type === 'fatal');
    }
    if (retry) retry.hidden = state.type !== 'fatal';
    if (state.type === 'ready') window.dispatchEvent(new Event('math-runtime-ready'));
  },
);
retry?.addEventListener('click', () => {
  retry.hidden = true;
  if (status) status.textContent = 'Повторная загрузка…';
  try { rpc.start(); } catch (error) { rpc.fail(error); }
});
export const request = (method, path, query = '', body = null) => rpc.request(method, path, query, body);
