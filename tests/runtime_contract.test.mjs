import test from 'node:test';
import assert from 'node:assert/strict';
import {WorkerRPC} from '../rpc.js';

function runtime() {
  const workers = [];
  const states = [];
  const rpc = new WorkerRPC(() => {
    const worker = {
      messages: [],
      postMessage(message) { this.messages.push(message); },
      terminate() { this.stopped = true; },
    };
    workers.push(worker);
    return worker;
  }, state => states.push(state));
  return {rpc, workers, states};
}

test('a queued messageerror from an old worker cannot destroy a successful retry', async () => {
  const {rpc, workers} = runtime();
  const first = assert.rejects(rpc.request('GET', '/api/catalogue'), /offline/);
  workers[0].onmessage({data: {type: 'fatal', message: 'offline'}});
  await first;
  const next = rpc.request('GET', '/api/catalogue').then(
    value => ({ok: true, value}), error => ({ok: false, error}),
  );
  workers[0].onmessageerror();
  workers[1].onmessage({data: {id: 2, status: 200, raw: '{"problems":[]}'}});
  const result = await next;
  assert.equal(result.ok, true, 'an obsolete worker rejected the replacement request');
  assert.equal(result.value.raw, '{"problems":[]}');
  assert.equal(workers[1].stopped, undefined);
  assert.equal(rpc.pending.size, 0);
});

test('old fatal messages and error events cannot overwrite the active worker', async () => {
  const {rpc, workers, states} = runtime();
  const first = assert.rejects(rpc.request('GET', '/api/catalogue'), /first failure/);
  workers[0].onmessage({data: {type: 'fatal', message: 'first failure'}});
  await first;
  const next = rpc.request('GET', '/api/catalogue');
  workers[0].onmessage({data: {type: 'fatal', message: 'obsolete failure'}});
  workers[0].onerror({preventDefault() {}});
  workers[1].onmessage({data: {id: 2, status: 200, raw: '{"ready":true}'}});
  assert.equal((await next).data.ready, true);
  assert.equal(states.filter(state => state.type === 'fatal').length, 1);
});

test('an unreadable response rejects only that request and subsequent work succeeds', async () => {
  const {rpc, workers} = runtime();
  const invalid = assert.rejects(rpc.request('GET', '/api/catalogue'), SyntaxError);
  const valid = rpc.request('GET', '/api/catalogue');
  workers[0].onmessage({data: {id: 1, status: 200, raw: '{'}});
  await invalid;
  workers[0].onmessage({data: {id: 2, status: 200, raw: '{"ready":true}'}});
  assert.equal((await valid).data.ready, true);
  assert.equal(workers[0].stopped, undefined);
  assert.equal(rpc.pending.size, 0);
});

test('worker construction failure releases the request and permits retry', async () => {
  let attempts = 0;
  const worker = {postMessage() {}, terminate() {}};
  const rpc = new WorkerRPC(() => {
    if (++attempts === 1) throw new Error('worker unavailable');
    return worker;
  });
  await assert.rejects(rpc.request('GET', '/api/catalogue'), /worker unavailable/);
  assert.equal(rpc.pending.size, 0);
  const next = rpc.request('GET', '/api/catalogue');
  worker.onmessage({data: {id: 1, status: 200, raw: '{"ready":true}'}});
  assert.equal((await next).data.ready, true);
});

test('stalled boot terminates the worker, rejects pending work and permits retry', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const {rpc, workers, states} = runtime();
  const result = rpc.request('GET', '/api/catalogue').then(
    value => ({ok: true, value}), error => ({ok: false, error}),
  );
  t.mock.timers.tick(179999);
  assert.equal(workers[0].stopped, undefined);
  t.mock.timers.tick(1);
  assert.equal(workers[0].stopped, true);
  assert.equal((await result).ok, false);
  assert.equal(rpc.pending.size, 0);
  assert.equal(states.at(-1).type, 'fatal');
  const next = rpc.request('GET', '/api/catalogue');
  workers[1].onmessage({data: {type: 'ready'}});
  workers[1].onmessage({data: {id: 2, status: 200, raw: '{"ready":true}'}});
  assert.equal((await next).data.ready, true);
});

test('boot watchdog stops on ready and never imposes a calculation deadline', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const {rpc, workers} = runtime();
  const result = rpc.request('POST', '/api/composite/build', '', '{}');
  t.mock.timers.tick(100000);
  workers[0].onmessage({data: {type: 'ready'}});
  t.mock.timers.tick(1000000);
  assert.equal(workers[0].stopped, undefined);
  assert.equal(rpc.pending.size, 1);
  workers[0].onmessage({data: {id: 1, status: 200, raw: '{"answer":"42"}'}});
  assert.equal((await result).data.answer, '42');
});

test('an obsolete ready message cannot cancel the replacement boot watchdog', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const {rpc, workers} = runtime();
  const first = assert.rejects(rpc.request('GET', '/api/catalogue'), /offline/);
  t.mock.timers.tick(1000);
  workers[0].onmessage({data: {type: 'fatal', message: 'offline'}});
  await first;
  const next = rpc.request('GET', '/api/catalogue').then(
    () => ({ok: true}), error => ({ok: false, error}),
  );
  workers[0].onmessage({data: {type: 'ready'}});
  t.mock.timers.tick(179999);
  assert.equal(workers[1].stopped, undefined);
  t.mock.timers.tick(1);
  assert.equal(workers[1].stopped, true);
  assert.equal((await next).ok, false);
});
