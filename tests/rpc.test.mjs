import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

test('worker RPC preserves exact raw JSON and handles interleaved results', async () => {
  let source;
  try { source = await readFile(new URL('../rpc.js', import.meta.url), 'utf8'); } catch {}
  assert.ok(source, 'worker RPC is missing');
  const {WorkerRPC} = await import('../rpc.js');
  const messages = [];
  const worker = {postMessage: value => messages.push(value), terminate() {this.stopped = true;}};
  const rpc = new WorkerRPC(() => worker);
  const raw = '{"schema":{"n":9007199254740993},"seed":"18446744073709551615"}';
  const first = rpc.request('POST', '/api/composite/variant', '', raw);
  const second = rpc.request('GET', '/api/catalogue');
  assert.equal(messages[0].body, raw);
  worker.onmessage({data:{id:messages[1].id,status:200,raw:'{"problems":[]}'}});
  assert.deepEqual((await second).data, {problems:[]});
  worker.onmessage({data:{id:messages[0].id,status:200,raw:'{"n":9007199254740993}'}});
  assert.equal((await first).raw, '{"n":9007199254740993}');
  assert.equal(rpc.pending.size, 0);
});

test('fatal worker errors reject all pending work and retry creates a new worker', async () => {
  const {WorkerRPC} = await import('../rpc.js');
  const workers = [];
  const rpc = new WorkerRPC(() => {const w = {postMessage(){},terminate(){this.stopped=true;}}; workers.push(w); return w;});
  const first = assert.rejects(rpc.request('GET','/api/catalogue'), /offline/);
  const second = assert.rejects(rpc.request('GET','/api/catalogue'), /offline/);
  workers[0].onmessage({data:{type:'fatal',message:'offline'}});
  await Promise.all([first, second]);
  assert.equal(workers[0].stopped, true);
  assert.equal(rpc.pending.size, 0);
  const next = rpc.request('GET','/api/catalogue');
  assert.equal(workers.length, 2);
  workers[1].onmessage({data:{id:3,status:400,raw:'{"error":"bad input"}'}});
  await assert.rejects(next, /bad input/);
  assert.equal(rpc.pending.size, 0);
});
