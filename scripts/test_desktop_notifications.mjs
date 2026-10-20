import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { CompanionNotifications } from './desktop_notifications.mjs';

const thought = { title: 'A tiny tangent', body: 'My imaginary penguin runs a jazz club.', topic: 'penguin-jazz-club', source_url: '' };
function setup(t, options = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'hyprchan-notifications-test-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return new CompanionNotifications({ statePath: join(directory, 'state.json'), now: () => 1000000,
    run: async () => ({ stdout: '42\n' }), ...options });
}

test('notification cooldown survives restart and repeated ideas stay quiet after it expires', async t => {
  let now = 1000000;
  const n = setup(t, { now: () => now });
  assert.equal((await n.send(thought)).sent, true);
  assert.equal(statSync(n.statePath).mode & 0o777, 0o600);
  const restarted = new CompanionNotifications({ statePath: n.statePath, now: () => now, run: n.run });
  assert.equal((await restarted.send({ ...thought, topic: 'another-thought' })).reason, 'cooldown');
  now += 900000;
  assert.equal((await restarted.send(thought)).reason, 'already_shared');
  assert.equal((await restarted.send({ ...thought, topic: 'another-thought' })).sent, true);
});

test('no shell is involved and notification body markup is escaped', async t => {
  let invocation;
  const n = setup(t, { run: async (...args) => { invocation = args; return { stdout: '7' }; } });
  const body = '$(touch /tmp/nope) <b>only words</b> & `id`';
  await n.send({ ...thought, title: '--help', body, source_url: 'https://example.org/?x=1&y=2' });
  assert.equal(invocation[0], 'notify-send');
  assert.deepEqual(invocation[1].slice(-3), ['--', '--help', '$(touch /tmp/nope) &lt;b&gt;only words&lt;/b&gt; &amp; `id`\nhttps://example.org/?x=1&amp;y=2']);
  assert.equal(invocation[2].shell, undefined);
});

test('failed delivery does not claim success or consume the cooldown', async t => {
  const n = setup(t, { run: async () => { throw new Error('Notification service offline'); } });
  await assert.rejects(n.send(thought), /offline/);
  assert.equal(n.status().retryAfterSec, 0);
  n.run = async () => ({ stdout: '9' });
  assert.equal((await n.send(thought)).sent, true);
});

test('disabled and interrupted turns cannot send notifications', async t => {
  let calls = 0;
  const n = setup(t, { run: async () => { calls++; return { stdout: '1' }; } });
  n.setEnabled(false);
  assert.equal((await n.send(thought)).sent, false);
  n.setEnabled(true);
  const controller = new AbortController(); controller.abort();
  assert.equal((await n.send(thought, controller.signal)).sent, false);
  assert.equal(calls, 0);
});

test('turning notifications off cancels a pending delivery and concurrent sends stay bounded', async t => {
  const n = setup(t, { run: (_, args, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
  }) });
  const sending = n.send(thought);
  assert.equal((await n.send(thought)).reason, 'delivery_in_progress');
  n.setEnabled(false);
  await assert.rejects(sending, /aborted/);
  assert.equal(n.status().retryAfterSec, 0);
});

test('malformed content and executable source links are rejected', async t => {
  const n = setup(t);
  for (const args of [{ ...thought, body: '' }, { ...thought, title: 'x'.repeat(65) },
                     { ...thought, source_url: 'file:///tmp/example' }, { ...thought, source_url: 'https://user:password@example.org' }]) {
    await assert.rejects(n.send(args));
  }
});
