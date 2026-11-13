import {WorkerRPC} from './rpc.js';

const status = document.getElementById('runtime-status');
const retry = document.getElementById('runtime-retry');
const banner = status?.closest('.runtime-banner');
const rpc = new WorkerRPC(
  () => new Worker(new URL('./worker.js', import.meta.url), {type: 'module'}),
  state => {
    if (status) {
      status.textContent = state.type === 'ready' ? '' : state.message || 'Подготовка…';
      status.classList.toggle('error', state.type === 'fatal');
    }
    if (banner) banner.hidden = state.type === 'ready';
    if (retry) retry.hidden = state.type !== 'fatal';
    if (state.type === 'ready') window.dispatchEvent(new Event('math-runtime-ready'));
  },
);
retry?.addEventListener('click', () => {
  retry.hidden = true;
  if (banner) banner.hidden = false;
  if (status) {
    status.textContent = 'Повторная загрузка…';
    status.classList.remove('error');
  }
  try { rpc.start(); } catch (error) { rpc.fail(error); }
});
export const request = (method, path, query = '', body = null) => rpc.request(method, path, query, body);

export function hideIdleRuntime() { if (!rpc.worker && banner) banner.hidden = true; }
