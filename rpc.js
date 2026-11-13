/** A string-only boundary: parsed display data must never be sent back as a schema. */
export class WorkerRPC {
  constructor(factory, onState = () => {}) {
    this.factory = factory;
    this.onState = onState;
    this.pending = new Map();
    this.sequence = 0;
    this.worker = null;
    this.bootTimer = null;
  }
  start() {
    if (this.worker) return;
    const worker = this.factory();
    this.worker = worker;
    const timer = setTimeout(() => {
      if (this.worker === worker && this.bootTimer === timer) {
        this.fail(new Error('Подготовка заняла слишком много времени. Проверьте подключение и повторите загрузку.'));
      }
    }, 180000);
    this.bootTimer = timer;
    worker.onmessage = ({data}) => {
      if (this.worker !== worker) return;
      if (data.type === 'fatal') { this.fail(new Error(data.message)); return; }
      if (data.type) {
        if (data.type === 'ready') {
          clearTimeout(this.bootTimer);
          this.bootTimer = null;
        }
        this.onState(data);
        return;
      }
      const pending = this.pending.get(data.id);
      if (!pending) return;
      // An API response also proves that boot completed, even if a ready
      // notification was omitted. Calculations have no transport deadline.
      clearTimeout(this.bootTimer);
      this.bootTimer = null;
      this.pending.delete(data.id);
      try {
        const parsed = JSON.parse(data.raw);
        if (data.status !== 200) throw new Error(parsed.error || 'Не удалось выполнить запрос.');
        pending.resolve({data: parsed, raw: data.raw});
      } catch (error) { pending.reject(error); }
    };
    worker.onerror = event => {
      event.preventDefault?.();
      if (this.worker === worker) this.fail(new Error('Не удалось запустить вычисления. Проверьте подключение и повторите загрузку.'));
    };
    worker.onmessageerror = () => {
      if (this.worker === worker) this.fail(new Error('Не удалось прочитать ответ вычислителя.'));
    };
  }
  fail(error) {
    clearTimeout(this.bootTimer);
    this.bootTimer = null;
    this.worker?.terminate();
    this.worker = null;
    for (const {reject} of this.pending.values()) reject(error);
    this.pending.clear();
    this.onState({type: 'fatal', message: error.message});
  }
  request(method, path, query = '', body = null) {
    return new Promise((resolve, reject) => {
      try { this.start(); } catch (error) { reject(error); this.fail(error); return; }
      const id = ++this.sequence;
      this.pending.set(id, {resolve, reject});
      try { this.worker.postMessage({id, method, path, query, body}); }
      catch (error) { this.fail(error); }
    });
  }
}
