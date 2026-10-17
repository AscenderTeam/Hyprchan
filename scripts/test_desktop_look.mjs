import test from 'node:test';
import assert from 'node:assert/strict';
import { LookRequests } from './desktop_look.mjs';

const image = kind => ({ kind, url: 'data:image/png;base64,YQ==' });
const snapshot = (time = 100) => ({ captured_at: time, images: [image('screen'), image('webcam')] });

test('look returns actual image items for only the requested source', async () => {
  const events = [];
  const looks = new LookRequests(event => events.push(event), { now: () => 100_000 });
  const result = looks.request('camera');
  looks.receive({ requestId: events[0].requestId, snapshot: snapshot() });
  const value = await result;
  assert.deepEqual(value.snapshot.images.map(item => item.kind), ['webcam']);
  assert.equal(value.input.filter(item => item.type === 'image').length, 1);
  assert.equal(value.input.at(-1).detail, 'auto');
  assert.match(value.input[1].text, /camera/);
  assert.equal(looks.pending.size, 0);
});

test('capture off cancels pending requests and rejects late images', async () => {
  const events = [];
  const looks = new LookRequests(event => events.push(event));
  const rejected = assert.rejects(looks.request('both'), /capture are off/);
  looks.setEnabled(false);
  await rejected;
  assert.equal(looks.receive({ requestId: events[0].requestId, snapshot: snapshot() }), false);
  await assert.rejects(looks.request('screen'), /capture are off/);
});

test('interruption and a missing capture resolve without hanging a model turn', async () => {
  const events = [];
  const looks = new LookRequests(event => events.push(event), { timeoutMs: 10 });
  const abort = new AbortController();
  const rejected = assert.rejects(looks.request('screen', abort.signal), /interrupted/);
  abort.abort();
  await rejected;
  await assert.rejects(looks.request('camera'), /timed out/);
  assert.equal(looks.pending.size, 0);
});

test('old captures and unavailable sources never masquerade as a fresh view', async () => {
  const events = [];
  const looks = new LookRequests(event => events.push(event), { now: () => 100_000 });
  const old = assert.rejects(looks.request('screen'), /old image/);
  looks.receive({ requestId: events[0].requestId, snapshot: snapshot(90) });
  await old;
  const missing = assert.rejects(looks.request('camera'), /unavailable/);
  looks.receive({ requestId: events.at(-1).requestId, snapshot: { captured_at: 100, images: [image('screen')] } });
  await missing;
});
