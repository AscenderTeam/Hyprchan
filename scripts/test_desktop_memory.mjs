import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { CompanionMemory } from './desktop_memory.mjs';
import { CodexHarness } from './bench_codex_rp.mjs';

test('facts persist, corrections replace them, and forgetting survives a restart', () => {
  const directory = mkdtempSync(join(tmpdir(), 'hyprchan-memory-test-'));
  const path = join(directory, 'memory.sqlite3');
  let memory = new CompanionMemory(path);
  try {
    const save = (fact, evidence) => memory.execute('memory_remember', { key: 'favorite_drink', fact, evidence },
      { userText: evidence, writable: true });
    save('Любимый напиток пользователя — чай.', 'Я люблю чай');
    save('Любимый напиток пользователя — кофе.', 'Теперь я предпочитаю кофе');
    assert.equal(memory.count(), 1);
    memory.close(); memory = new CompanionMemory(path);
    assert.match(memory.recall('кофе')[0].fact, /кофе/);
    assert.equal(memory.recall('чай').length, 0);
    assert.equal(statSync(path).mode & 0o777, 0o600);
    memory.execute('memory_forget', { key: 'favorite_drink', evidence: 'Забудь мой любимый напиток' },
      { userText: 'Забудь мой любимый напиток', writable: true });
    memory.close(); memory = new CompanionMemory(path);
    assert.equal(memory.count(), 0);
  } finally { memory.close(); rmSync(directory, { recursive: true, force: true }); }
});

test('writes require current user evidence and cannot run from screen observations or cancelled turns', () => {
  const memory = new CompanionMemory(':memory:');
  const args = { key: 'pet', fact: 'The user has a cat.', evidence: 'I have a cat' };
  try {
    assert.throws(() => memory.execute('memory_remember', args, { userText: 'hello', writable: true }), /exact quote/);
    assert.throws(() => memory.execute('memory_remember', args, { userText: 'I have a cat', writable: false }), /current user/);
    assert.throws(() => memory.execute('memory_remember', args,
      { userText: 'I have a cat', writable: true, signal: AbortSignal.abort() }), /interrupted/);
    assert.equal(memory.count(), 0);
    assert.throws(() => memory.execute('shell', {}), /Unknown/);
  } finally { memory.close(); }
});

test('duplicate facts do not accumulate and recent/relevant context is bounded', () => {
  const memory = new CompanionMemory(':memory:');
  try {
    for (const key of ['pet', 'pets']) memory.execute('memory_remember',
      { key, fact: 'The user has a cat.', evidence: 'I have a cat' }, { userText: 'I have a cat', writable: true });
    assert.equal(memory.count(), 1);
    assert.match(memory.context('cat'), /The user has a cat/);
    assert.equal(memory.execute('memory_recall', { query: '' }).facts.length, 1);
  } finally { memory.close(); }
});

test('Codex serves only explicitly enabled dynamic tools and returns real success/failure', async () => {
  const sent = [];
  const harness = { send: message => sent.push(message), toolHandler: params => ({ saved: params.tool === 'memory_remember' }) };
  await CodexHarness.prototype.handleServerRequest.call(harness,
    { id: 1, method: 'item/tool/call', params: { tool: 'memory_remember' } });
  assert.equal(sent[0].result.success, true);
  assert.deepEqual(JSON.parse(sent[0].result.contentItems[0].text), { saved: true });
  await CodexHarness.prototype.handleServerRequest.call(harness, { id: 2, method: 'item/commandExecution/requestApproval' });
  assert.equal(sent[1].error.code, -32601);
  harness.toolHandler = () => { throw new Error('Memory is off'); };
  await CodexHarness.prototype.handleServerRequest.call(harness, { id: 3, method: 'item/tool/call', params: {} });
  assert.equal(sent[2].result.success, false);
});

test('visual memories stay tentative, require the actual source, and cannot overwrite confirmed facts', () => {
  const memory = new CompanionMemory(':memory:');
  const args = { key: 'keyboard', fact: 'A green keyboard was visible near the user.',
    evidence: 'Green keys visible on the desk', basis: 'camera_observation' };
  const context = { visualSources: ['webcam'], capturedAt: Date.now() / 1000 };
  try {
    assert.throws(() => memory.execute('memory_remember', args, { visualSources: ['screen'], capturedAt: context.capturedAt }), /supplied recent image/);
    memory.execute('memory_remember', args, context);
    assert.equal(memory.recall()[0].confidence, 'tentative');
    memory.execute('memory_remember', { key: 'keyboard', fact: 'The user uses a red keyboard.',
      evidence: 'My keyboard is red', basis: 'user_statement' }, { userText: 'My keyboard is red', writable: true });
    assert.equal(memory.recall()[0].confidence, 'confirmed');
    assert.throws(() => memory.execute('memory_remember', args, context), /cannot overwrite/);
    assert.match(memory.recall()[0].fact, /red/);
  } finally { memory.close(); }
});
