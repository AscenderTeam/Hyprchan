import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { TurnQueue } from './desktop_turn_queue.mjs';
import { CodexHarness } from './bench_codex_rp.mjs';

const tick = () => new Promise(resolve => setImmediate(resolve));
function runner() {
  const starts = [], cancelled = [], release = new Map();
  const queue = new TurnQueue((command, signal) => new Promise(resolve => {
    starts.push(command.id);
    release.set(command.id, resolve);
    const abort = () => { cancelled.push(command.id); resolve(); };
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort, { once: true });
  }), error => { throw error; });
  return { queue, starts, cancelled, release };
}

test('a user message interrupts a reaction before starting in the same conversation', async () => {
  const r = runner();
  r.queue.submit({ type: 'react', id: 1 });
  await tick();
  r.queue.submit({ type: 'chat', id: 2 });
  await tick();
  assert.deepEqual(r.cancelled, [1]);
  assert.deepEqual(r.starts, [1, 2]);
  await r.queue.close();
});

test('only the newest waiting observation survives', async () => {
  const r = runner();
  r.queue.submit({ type: 'react', id: 1 });
  await tick();
  r.queue.submit({ type: 'react', id: 2 });
  r.queue.submit({ type: 'react', id: 3 });
  r.release.get(1)();
  await tick();
  assert.deepEqual(r.starts, [1, 3]);
  await r.queue.close();
});

test('switching reactions off discards observations without interrupting user replies', async () => {
  const r = runner();
  r.queue.submit({ type: 'chat', id: 1 });
  await tick();
  r.queue.submit({ type: 'react', id: 2 });
  r.queue.cancelReactions();
  assert.deepEqual(r.cancelled, []);
  r.release.get(1)();
  await tick();
  assert.deepEqual(r.starts, [1]);
  await r.queue.close();
});

test('cancellation before turn creation makes no inference request', async () => {
  const signal = AbortSignal.abort();
  const result = await CodexHarness.prototype.turn.call({}, { id: 'thread' }, 'unused', { signal });
  assert.equal(result.status, 'interrupted');
});

test('cancellation during turn/start interrupts as soon as the turn id arrives', async () => {
  const harness = new EventEmitter();
  harness.timeoutMs = 1000;
  const calls = [];
  let started;
  harness.request = async (method, params) => {
    calls.push(method);
    if (method === 'turn/start') return new Promise(resolve => { started = resolve; });
    assert.equal(params.turnId, 'turn');
    queueMicrotask(() => harness.emit('notification', { method: 'turn/completed',
      params: { threadId: 'thread', turn: { status: 'interrupted' } } }));
    return {};
  };
  const controller = new AbortController();
  const turn = CodexHarness.prototype.turn.call(harness, { id: 'thread' }, 'observe', { signal: controller.signal });
  controller.abort();
  started({ turn: { id: 'turn' } });
  const result = await turn;
  assert.equal(result.status, 'interrupted');
  assert.deepEqual(calls, ['turn/start', 'turn/interrupt']);
});

test('a final NO_REPLY remains separate from earlier tool commentary', async () => {
  const harness = new EventEmitter();
  harness.timeoutMs = 1000;
  harness.request = async () => {
    queueMicrotask(() => {
      const notify = (method, params) => harness.emit('notification', { method, params: { threadId: 'thread', ...params } });
      notify('item/agentMessage/delta', { delta: 'Listening now.' });
      notify('item/completed', { item: { type: 'agentMessage', phase: 'commentary', text: 'Listening now.' } });
      notify('item/agentMessage/delta', { delta: 'NO_REPLY' });
      notify('item/completed', { item: { type: 'agentMessage', phase: 'final_answer', text: 'NO_REPLY' } });
      notify('turn/completed', { turn: { status: 'completed' } });
    });
    return { turn: { id: 'turn' } };
  };
  const result = await CodexHarness.prototype.turn.call(harness, { id: 'thread' }, 'observe');
  assert.equal(result.finalText, 'NO_REPLY');
});
