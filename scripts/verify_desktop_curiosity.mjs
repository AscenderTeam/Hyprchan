#!/usr/bin/env node
// Real model/web/tool check. Sends at most one real Hyprchan notification.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { writeFileSync } from 'node:fs';
import { CompanionNotifications } from './desktop_notifications.mjs';
const notificationReady = new CompanionNotifications().status().retryAfterSec === 0;

const output = process.argv[2];
if (!output) throw new Error('Usage: verify_desktop_curiosity.mjs results.json');
const child = spawn('node', ['scripts/desktop_codex_bridge.mjs'], {
  env: { ...process.env, HYPRCHAN_MEMORY_PATH: ':memory:' }, stdio: ['pipe', 'pipe', 'inherit'],
});
const pending = new Map();
const notifications = [];
const rows = [];
let ready;
const startup = new Promise(resolve => { ready = resolve; });
const lines = createInterface({ input: child.stdout });
lines.on('line', line => {
  const event = JSON.parse(line);
  if (event.type === 'ready') ready(event);
  if (event.type === 'notification_status') notifications.push(event);
  if (['done', 'error'].includes(event.type) && pending.has(event.id)) {
    const wait = pending.get(event.id); pending.delete(event.id); clearTimeout(wait.timer);
    if (event.type === 'error') wait.reject(new Error(event.message)); else wait.resolve(event);
  }
});
const send = value => child.stdin.write(JSON.stringify(value) + '\n');
function request(value) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(value.id); reject(new Error('Creative turn timed out')); }, 45000);
    pending.set(value.id, { resolve, reject, timer }); send(value);
  });
}
const words = text => text.replace(/https?:\/\/\S+/g, '').trim().split(/\s+/).filter(Boolean).length;
let passed = false;
const deadline = setTimeout(() => child.kill('SIGTERM'), 120000);
try {
  await startup;
  send({ type: 'memory_mode', active: false });
  send({ type: 'vision_mode', active: false });
  const greeting = await request({ type: 'chat', id: 1, text: 'Привет!', vision: { enabled: false } });
  rows.push({ case: 'greeting', ...greeting });
  assert.equal(greeting.status, 'completed');
  assert.equal(greeting.toolCalls, 0); assert.equal(greeting.webSearches, 0);

  const trivia = await request({ type: 'chat', id: 2,
    text: 'Мне любопытны GoGo Penguin. Найди какой-нибудь бесполезный интересный факт про них и поболтай об этом от себя, с маленькой смешной фантазией. Пришли короткий тизер уведомлением, если сейчас можно, а саму историю расскажи в чате.',
    vision: { enabled: false } });
  rows.push({ case: 'artist_rabbit_hole', words: words(trivia.text), ...trivia });
  assert.equal(trivia.status, 'completed');
  assert.ok(trivia.webSearches >= 1, 'No actual web lookup');
  assert.match(trivia.text, /https:\/\//, 'Research needs a source URL');
  assert.ok(trivia.tangentWords >= 120 && trivia.tangentWords <= 220, 'Tangent was not accepted through the longer-output tool');
  assert.equal(words(trivia.text), trivia.tangentWords);
  assert.equal(notifications.filter(n => n.sent).length, notificationReady ? 1 : 0, 'Delivery did not respect the real persisted cooldown');

  const rant = await request({ type: 'chat', id: 3,
    text: 'А теперь мне хочется послушать твой маленький нелепый хейт-спич про systemd. Просто ради твоего настроения, без технических советов.',
    vision: { enabled: false } });
  rows.push({ case: 'systemd_tangent', words: words(rant.text), ...rant });
  assert.equal(rant.status, 'completed');
  assert.ok(rant.tangentWords >= 120 && rant.tangentWords <= 220, 'Rant was only a caption');
  assert.equal(words(rant.text), rant.tangentWords);
  assert.equal(notifications.filter(n => n.sent).length, notificationReady ? 1 : 0, 'Cooldown was bypassed');

  // This event offers an opening, not an order to research or notify. Either a
  // fresh thought or NO_REPLY is valid; capture the actual choice for review.
  const optional = await request({ type: 'react', id: 4, language: 'ru',
    observation: { type: 'audio_event', event: 'new_channel', serial: '123',
      name: 'Music player · Aphex Twin · Windowlicker', application: 'Synthetic public music player',
      observedAt: Date.now() / 1000 }, vision: { enabled: false } });
  rows.push({ case: 'optional_public_music_observation', words: words(optional.text), ...optional });
  assert.equal(optional.status, 'completed');
  assert.equal(notifications.filter(n => n.sent).length, notificationReady ? 1 : 0);
  passed = true;
} finally {
  writeFileSync(output, JSON.stringify({ publicAndSyntheticOnly: true, notificationReady, passed, rows, notifications }, null, 2) + '\n');
  console.log(JSON.stringify({ passed, rows, notifications }, null, 2));
  clearTimeout(deadline);
  send({ type: 'quit' });
  const kill = setTimeout(() => child.kill('SIGTERM'), 3000);
  child.on('exit', () => clearTimeout(kill));
}
