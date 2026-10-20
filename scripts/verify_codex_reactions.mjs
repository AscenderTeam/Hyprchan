#!/usr/bin/env node
// Exercise the real GUI bridge with two supplied synthetic screenshots only.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const [beforePath, afterPath, outputPath] = process.argv.slice(2);
if (!beforePath || !afterPath || !outputPath) throw new Error('Usage: verify_codex_reactions.mjs before.png after.png results.json');
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const child = spawn('node', [join(root, 'scripts/desktop_codex_bridge.mjs')], {
  env: { ...process.env, HYPRCHAN_MEMORY_PATH: ':memory:' }, stdio: ['pipe', 'pipe', 'inherit'] });
const input = createInterface({ input: child.stdout });
let ready;
const startup = new Promise(resolve => { ready = resolve; });
const pending = new Map();
const deltas = [];
input.on('line', line => {
  const event = JSON.parse(line);
  if (event.type === 'ready') ready(event);
  if (event.type === 'delta') deltas.push(event.id);
  if (event.type === 'done' || event.type === 'error') {
    const waiter = pending.get(event.id);
    if (waiter) {
      clearTimeout(waiter.timer);
      pending.delete(event.id);
      if (event.type === 'error') waiter.reject(new Error(event.message));
      else waiter.resolve({ ...event, wallMs: performance.now() - waiter.start });
    }
  }
});
function request(command) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(command.id); reject(new Error('Turn timed out')); }, 20000);
    pending.set(command.id, { resolve, reject, timer, start: performance.now() });
    child.stdin.write(JSON.stringify(command) + '\n');
  });
}
function reaction(id, path) {
  return { type: 'react', id, language: 'ru', vision: { enabled: true, snapshot: {
    captured_at: Date.now() / 1000,
    images: [{ kind: 'screen', url: 'data:image/png;base64,' + readFileSync(path).toString('base64') }],
  } } };
}
const deadline = setTimeout(() => child.kill('SIGTERM'), 90000);
const rows = [];
let passed = false;
try {
  const config = await startup;
  rows.push({ case: 'new_screen', ...await request(reaction(1, beforePath)) });
  rows.push({ case: 'unchanged_screen', ...await request(reaction(2, beforePath)) });
  rows.push({ case: 'changed_screen', ...await request(reaction(3, afterPath)) });
  const interrupted = request(reaction(4, beforePath));
  await new Promise(resolve => setTimeout(resolve, 150));
  const chat = request({ type: 'chat', id: 5, text: 'Привет!', vision: { enabled: false } });
  rows.push({ case: 'preempted_observation', ...await interrupted });
  rows.push({ case: 'user_after_preemption', ...await chat });
  assert.ok(rows[0].text.trim() && !rows[0].quiet);
  assert.equal(rows[1].quiet, true);
  assert.equal(rows[1].text, '');
  assert.ok(rows[2].text.trim() && !rows[2].quiet);
  assert.equal(rows[3].status, 'interrupted');
  assert.equal(rows[3].text, '');
  assert.equal(rows[4].status, 'completed');
  assert.ok(rows[4].text.trim());
  assert.ok(deltas.every(id => id === 5), 'Observations must never stream a NO_REPLY token into the GUI');
  passed = true;
  console.log(JSON.stringify({ config, rows, passed }, null, 2));
} finally {
  writeFileSync(outputPath, JSON.stringify({ syntheticScreensOnly: true, passed, rows }, null, 2) + '\n');
  clearTimeout(deadline);
  child.stdin.end('{"type":"quit"}\n');
  const kill = setTimeout(() => child.kill('SIGTERM'), 3000);
  child.on('exit', () => clearTimeout(kill));
}
