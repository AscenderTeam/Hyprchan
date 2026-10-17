import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { promisify } from 'node:util';

export const notificationTool = {
  type: 'function', name: 'notify_user',
  description: 'Optionally share a small discovery, useless fact, silly tangent or callback as a desktop notification. This is a creative outlet, never a task or quota. Respect the supplied cooldown. Keep the notification a short teaser and put your developed tangent in chat, without repeating the teaser verbatim. A returned sent=false means nothing was delivered.',
  inputSchema: { type: 'object', additionalProperties: false, properties: {
    title: { type: 'string', minLength: 1, maxLength: 64 },
    body: { type: 'string', minLength: 1, maxLength: 350, description: 'Short in-character message, with real facts grounded in sources and imaginary antics clearly playful.' },
    topic: { type: 'string', minLength: 1, maxLength: 100, description: 'Stable key for this particular fact or joke; reuse it for the same idea so duplicates stay quiet.' },
    source_url: { type: 'string', maxLength: 500, description: 'Exact public source URL for researched facts, or empty for a fictional joke/tangent.' },
  }, required: ['title', 'body', 'topic', 'source_url'] },
};

const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const hash = text => createHash('sha256').update(text.trim().toLowerCase()).digest('hex');

export class CompanionNotifications {
  constructor({ statePath = process.env.HYPRCHAN_NOTIFICATION_STATE || join(
    process.env.XDG_STATE_HOME || join(homedir(), '.local/state'), 'hyprchan-codex/notifications.json'),
    cooldownMs = Number(process.env.HYPRCHAN_NOTIFICATION_INTERVAL_SEC || 900) * 1000,
    run = promisify(execFile), now = Date.now } = {}) {
    if (!Number.isFinite(cooldownMs) || cooldownMs < 0) throw new Error('Invalid notification interval');
    this.statePath = statePath;
    this.cooldownMs = cooldownMs;
    this.run = run;
    this.now = now;
    this.enabled = process.env.HYPRCHAN_NOTIFICATIONS !== 'off';
    this.state = { lastSent: 0, topics: {} };
    try {
      const value = JSON.parse(readFileSync(statePath, 'utf8'));
      if (Number.isFinite(value.lastSent) && value.topics && typeof value.topics === 'object') this.state = value;
    } catch (error) { if (error.code !== 'ENOENT') this.stateError = 'Could not read notification cooldown state'; }
  }

  setEnabled(active) {
    this.enabled = !!active;
    if (!this.enabled) this.delivery?.abort();
  }

  status() {
    return { enabled: this.enabled, cooldownSec: this.cooldownMs / 1000,
      retryAfterSec: this.state.lastSent ? Math.max(0, Math.ceil((this.state.lastSent + this.cooldownMs - this.now()) / 1000)) : 0,
      stateError: this.stateError || null };
  }

  context() {
    return `Optional desktop notifications: ${JSON.stringify(this.status())}. This is a maximum frequency, never a schedule or obligation. Only use notify_user when you feel like sharing something new. Use a notification as a short teaser, with the developed tangent in your normal chat reply. Do not repeat the teaser verbatim. If suppressed, never retry or claim delivery; do not invent another tangent to work around the limit.`;
  }

  async send(args, signal) {
    if (!this.enabled || signal?.aborted) return { sent: false, reason: 'disabled_or_interrupted' };
    if (this.delivery) return { sent: false, reason: 'delivery_in_progress' };
    const status = this.status();
    if (status.retryAfterSec) return { sent: false, reason: 'cooldown', retryAfterSec: status.retryAfterSec };
    for (const [key, max] of Object.entries({ title: 64, body: 350, topic: 100, source_url: 500 })) {
      if (typeof args?.[key] !== 'string' || args[key].length > max ||
          (key !== 'source_url' && !args[key].trim()) || /[\x00-\x08\x0b-\x1f]/.test(args[key])) {
        throw new Error(`Invalid notification ${key}`);
      }
    }
    if (args.source_url) {
      const url = new URL(args.source_url);
      if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error('Use a public http(s) source URL');
    }
    const key = hash(args.topic);
    if (this.state.topics[key] && this.now() - this.state.topics[key] < 86400000) return { sent: false, reason: 'already_shared' };
    this.delivery = new AbortController();
    try {
      const body = args.body.trim() + (args.source_url ? '\n' + args.source_url : '');
      const { stdout } = await this.run('notify-send', ['--app-name=Hyprchan', '--icon=face-smile',
        '--hint=string:desktop-entry:org.hyprland.hyprchan.codex', '--urgency=normal', '--expire-time=12000',
        '--print-id', '--', args.title.trim(), escape(body)], {
        timeout: 3000, maxBuffer: 2048,
        signal: signal ? AbortSignal.any([signal, this.delivery.signal]) : this.delivery.signal,
      });
      const id = String(stdout).trim();
      if (!/^\d+$/.test(id)) throw new Error('Notification server returned no delivery ID');
      this.state.lastSent = this.now();
      this.state.topics = Object.fromEntries(Object.entries(this.state.topics)
        .filter(([, time]) => Number.isFinite(time) && this.now() - time < 86400000).slice(-99));
      this.state.topics[key] = this.state.lastSent;
      try {
        mkdirSync(dirname(this.statePath), { recursive: true, mode: 0o700 });
        const temporary = this.statePath + `.${process.pid}.tmp`;
        writeFileSync(temporary, JSON.stringify(this.state) + '\n', { mode: 0o600 });
        renameSync(temporary, this.statePath);
        this.stateError = null;
      } catch { this.stateError = 'Notification sent, but cooldown could not be saved across restarts'; }
      return { sent: true, notificationId: id, ...this.status() };
    } finally { this.delivery = null; }
  }
}
