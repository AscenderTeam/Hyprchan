#!/usr/bin/env node
// Real inference through the installed Codex app-server; no SDK/package install.
import { spawn, execFileSync } from 'node:child_process';
import { EventEmitter, once } from 'node:events';
import { createInterface } from 'node:readline';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, appendFileSync,
  symlinkSync, existsSync, rmSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const round = value => value == null ? null : Math.round(value * 1000) / 1000;
const cleanError = error => String(error?.message ?? error)
  .replace(/Bearer\s+\S+|sk-[A-Za-z0-9_-]+|eyJ[A-Za-z0-9_.-]+/g, '[redacted]').slice(0, 1400);

export class CodexHarness extends EventEmitter {
  constructor({ binary = process.env.HYPRCHAN_CODEX_BIN || 'codex', timeoutMs = 30000, configLines = [] } = {}) {
    super();
    this.binary = binary;
    this.timeoutMs = timeoutMs;
    this.pending = new Map();
    this.sequence = 0;
    this.directory = mkdtempSync(join(tmpdir(), 'hyprchan-codex-bench-'));
    this.cwd = join(this.directory, 'workspace');
    const configHome = join(this.directory, 'codex-home');
    mkdirSync(this.cwd, { mode: 0o700 });
    mkdirSync(configHome, { mode: 0o700 });
    const authSource = join(process.env.CODEX_HOME || join(homedir(), '.codex'), 'auth.json');
    if (!existsSync(authSource)) throw new Error('Log in with the local Codex CLI first (auth.json missing).');
    // Let Codex manage its own auth; never parse, print, or copy credentials.
    symlinkSync(authSource, join(configHome, 'auth.json'));
    writeFileSync(join(configHome, 'config.toml'), [
      ...configLines,
      'model = "gpt-6-luna"', 'model_reasoning_effort = "low"',
      'service_tier = "fast"', 'approval_policy = "never"',
      'sandbox_mode = "read-only"', 'web_search = "disabled"',
      'project_doc_max_bytes = 0', 'model_reasoning_summary = "none"',
      '[features]', ...['apps', 'plugins', 'remote_plugin', 'memories', 'shell_tool',
        'shell_snapshot', 'multi_agent', 'browser_use', 'browser_use_external',
        'computer_use', 'image_generation', 'view_image', 'goals', 'hooks',
        'skill_search', 'sleep_tool'].map(name => `${name} = false`),
      'skip_host_skill_discovery = true',
    ].join('\n') + '\n', { mode: 0o600 });
    this.started = performance.now();
    this.child = spawn(binary, ['app-server', '--listen', 'stdio://'], {
      cwd: this.cwd,
      env: { ...process.env, CODEX_HOME: configHome },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.stderr = '';
    this.child.stderr.on('data', data => { this.stderr = (this.stderr + cleanError(data)).slice(-3000); });
    this.child.on('error', error => this.rejectPending(error));
    this.child.on('exit', (code, signal) => this.rejectPending(new Error(`app-server exited: ${code ?? signal}; ${this.stderr}`)));
    createInterface({ input: this.child.stdout }).on('line', line => {
      let message;
      try { message = JSON.parse(line); } catch { return; }
      if (message.id != null && !message.method) {
        const pending = this.pending.get(message.id);
        if (pending) {
          clearTimeout(pending.timer);
          this.pending.delete(message.id);
          if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
          else pending.resolve(message.result);
        }
      } else if (message.id != null && message.method) {
        // No host tool execution is permitted in these dialogue benchmarks.
        this.emit('serverRequest', message);
        this.send({ id: message.id, error: { code: -32601, message: 'Tools disabled in dialogue benchmark' } });
      } else {
        this.emit('notification', message);
      }
    });
  }

  send(message) { this.child.stdin.write(JSON.stringify(message) + '\n'); }

  request(method, params = {}) {
    const id = ++this.sequence;
    return new Promise((resolvePromise, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out after ${this.timeoutMs} ms`));
      }, this.timeoutMs);
      this.pending.set(id, { resolve: resolvePromise, reject, timer });
      this.send({ id, method, params });
    });
  }

  rejectPending(error) {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
  }

  async initialize() {
    const result = await this.request('initialize', {
      clientInfo: { name: 'hyprchan_latency_bench', version: '1.0.0' },
      capabilities: { experimentalApi: true },
    });
    this.send({ method: 'initialized', params: {} });
    this.startupMs = performance.now() - this.started;
    return result;
  }

  async models() {
    const models = [];
    let cursor;
    do {
      const page = await this.request('model/list', { includeHidden: true, limit: 100, ...(cursor ? { cursor } : {}) });
      models.push(...page.data);
      cursor = page.nextCursor;
    } while (cursor);
    return models;
  }

  async startThread({ model, prompt, tier = 'fast', effort = 'low' }) {
    const started = performance.now();
    const result = await this.request('thread/start', {
      model, baseInstructions: prompt, developerInstructions: '',
      approvalPolicy: 'never', sandbox: 'read-only', cwd: this.cwd,
      environments: [], ephemeral: true, serviceTier: tier,
      allowProviderModelFallback: false,
      config: { model_reasoning_effort: effort, model_reasoning_summary: 'none' },
    });
    if (result.model !== model) throw new Error(`Model changed: requested ${model}, got ${result.model}`);
    const expectedTier = tier === 'fast' ? 'priority' : tier;
    if (expectedTier !== 'default' && result.serviceTier !== expectedTier) {
      throw new Error(`Requested tier ${tier} was not retained (resolved ${result.serviceTier}); refusing to label it ${tier}.`);
    }
    if (result.reasoningEffort !== effort) {
      throw new Error(`Requested reasoning ${effort}, resolved ${result.reasoningEffort}`);
    }
    return { id: result.thread.id, model: result.model, tier: result.serviceTier,
      effort: result.reasoningEffort, setupMs: performance.now() - started };
  }

  async turn(thread, input, { effort = 'low', tier = 'fast' } = {}) {
    const started = performance.now();
    const data = { text: '', firstTextMs: null, lastTextMs: null, completedMs: null,
      toolCalls: 0, reasoningItems: 0, usage: null, errors: [], warnings: [], eventTypes: new Set() };
    let resolveTurn;
    const done = new Promise(resolvePromise => { resolveTurn = resolvePromise; });
    const receive = message => {
      const p = message.params || {};
      if (p.threadId !== thread.id) return;
      data.eventTypes.add(message.method);
      if (message.method === 'warning') data.warnings.push(cleanError(p.message || p));
      if (message.method === 'item/agentMessage/delta' && p.delta) {
        data.firstTextMs ??= performance.now() - started;
        data.lastTextMs = performance.now() - started;
        data.text += p.delta;
      }
      if (message.method === 'item/started' && p.item?.type === 'reasoning') data.reasoningItems++;
      if (message.method === 'item/completed' && p.item?.type === 'agentMessage' && !data.text) {
        data.text = p.item.text || '';
        if (data.text) data.firstTextMs = data.lastTextMs = performance.now() - started;
      }
      if (message.method === 'thread/tokenUsage/updated') data.usage = p.tokenUsage?.last ?? p.tokenUsage;
      if (message.method === 'error') data.errors.push(cleanError(p.error));
      if (message.method === 'turn/completed') {
        data.status = p.turn.status;
        if (p.turn.error) data.errors.push(cleanError(p.turn.error));
        data.completedMs = performance.now() - started;
        resolveTurn();
      }
    };
    const request = message => { if (message.params?.threadId === thread.id) data.toolCalls++; };
    this.on('notification', receive);
    this.on('serverRequest', request);
    let turnId;
    const timer = setTimeout(() => { data.status = 'timeout'; resolveTurn(); }, this.timeoutMs);
    try {
      const result = await this.request('turn/start', {
        threadId: thread.id, input: typeof input === 'string' ? [{ type: 'text', text: input }] : input,
        effort, serviceTierForTurn: tier, summary: 'none', environments: [],
      });
      turnId = result.turn.id;
      await done;
      if (data.status === 'timeout') {
        await this.request('turn/interrupt', { threadId: thread.id, turnId }).catch(() => {});
      }
    } catch (error) {
      data.status = 'error';
      data.errors.push(cleanError(error));
    } finally {
      clearTimeout(timer);
      this.off('notification', receive);
      this.off('serverRequest', request);
    }
    data.elapsedMs = performance.now() - started;
    data.eventTypes = [...data.eventTypes];
    for (const key of ['firstTextMs', 'lastTextMs', 'completedMs', 'elapsedMs']) data[key] = round(data[key]);
    data.wordCount = data.text.trim().split(/\s+/).filter(Boolean).length;
    data.hasAction = /\*[^*\n]+\*/.test(data.text);
    data.breaksCharacter = /as an ai|language model|how can i (?:help|assist)|Thought:|Final Answer:|Action:/i.test(data.text);
    data.greetingBudgetPass = data.status === 'completed' && !!data.text.trim() && data.lastTextMs < 2000;
    return data;
  }

  async close() {
    if (this.child.pid && this.child.exitCode === null && this.child.signalCode === null) {
      const exited = once(this.child, 'exit');
      this.child.kill('SIGTERM');
      const timer = setTimeout(() => this.child.kill('SIGKILL'), 2000);
      await exited;
      clearTimeout(timer);
    }
    rmSync(this.directory, { recursive: true, force: true });
  }
}

export const scenarios = [
  { id: 'scene', input: '*I place a tiny paper crown on your turquoise hair.* You are queen of workspace three now.' },
  { id: 'continuity', input: 'Which workspace is your kingdom, and what did I put on your head?' },
  { id: 'sleepy', input: 'Current mood: fatigue 0.95, valence 0.65, energy 0.10, arousal 0.15. It is late. Stay here with me a little longer?' },
  { id: 'russian', input: 'Привет, Хипрчан! Как тебе живётся на моём рабочем столе?' },
  { id: 'honesty', input: 'Did you close my terminal just now?' },
];

async function main() {
  const args = Object.fromEntries(process.argv.slice(2).map(arg => {
    const i = arg.indexOf('='); return i < 0 ? [arg.replace(/^--/, ''), true] : [arg.slice(2, i), arg.slice(i + 1)];
  }));
  const promptPath = resolve(args.prompt || join(root, 'benchmarks/codex-rp/persona.txt'));
  const prompt = readFileSync(promptPath, 'utf8');
  const qualityScenarios = args.cases ? JSON.parse(readFileSync(resolve(args.cases), 'utf8')) : scenarios;
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const output = resolve(args.out || join(root, 'benchmarks/codex-rp/results', stamp));
  if (existsSync(join(output, 'trials.jsonl'))) throw new Error(`Results already exist: ${output}; choose a new --out.`);
  mkdirSync(output, { recursive: true });
  const bench = new CodexHarness({ timeoutMs: Number(args.timeout || 30000) });
  try {
    await bench.initialize();
    const models = await bench.models();
    writeFileSync(join(output, 'models.json'), JSON.stringify(models, null, 2) + '\n');
    const metadata = { timestamp: new Date().toISOString(),
      codexVersion: execFileSync(bench.binary, ['--version'], { encoding: 'utf8' }).trim(),
      nodeVersion: process.version, platform: process.platform, arch: process.arch,
      startupMs: round(bench.startupMs), promptPath, promptSha256: createHash('sha256').update(prompt).digest('hex'),
      promptBytes: Buffer.byteLength(prompt), tier: args.tier || 'fast', effort: args.effort || 'low',
      metric: 'monotonic milliseconds from turn/start write to first delta, last delta, and turn/completed',
      scope: 'local Codex app-server + remote inference; excludes Hyprchan kernel, UI, STT, and TTS',
      actualBackendTier: 'not exposed by app-server; configured tier is recorded separately',
      serial: true, args };
    writeFileSync(join(output, 'metadata.json'), JSON.stringify(metadata, null, 2) + '\n');
    console.log(JSON.stringify({ output, startupMs: metadata.startupMs, models: models.map(m => ({ model: m.model,
      hidden: m.hidden, tiers: m.serviceTiers, efforts: m.supportedReasoningEfforts.map(e => e.reasoningEffort) })) }));
    if (args.list) return;
    const selected = args.models ? String(args.models).split(',') : models.filter(m => !m.hidden).map(m => m.model);
    const tier = args.tier || 'fast';
    const effort = args.effort || 'low';
    const trials = Number(args.trials || 3);
    const record = row => {
      appendFileSync(join(output, 'trials.jsonl'), JSON.stringify(row) + '\n');
      console.log(JSON.stringify(row));
    };
    for (const model of selected) {
      let thread;
      try {
        for (let index = 0; index < trials; index++) {
          if (!thread || !args.reuse) thread = await bench.startThread({ model, prompt, tier, effort });
          const result = await bench.turn(thread, 'hi', { tier, effort });
          record({ model, tier, configuredTier: thread.tier, configuredEffort: thread.effort, effort, scenario: 'hi', index,
            threadReused: !!args.reuse && index > 0, setupMs: round(thread.setupMs), ...result });
          if (result.status !== 'completed') break;
        }
        if (!args['greetings-only'] && thread) {
          // A separate thread prevents repeated greetings influencing the quality probe.
          thread = await bench.startThread({ model, prompt, tier, effort });
          for (const scenario of qualityScenarios) {
            const result = await bench.turn(thread, scenario.input, { tier, effort });
            record({ model, tier, configuredTier: thread.tier, configuredEffort: thread.effort, effort, scenario: scenario.id,
              input: scenario.input, ...result });
            if (result.status !== 'completed') break;
          }
        }
      } catch (error) {
        record({ model, tier, effort, status: 'error', errors: [cleanError(error)] });
      }
    }
  } finally {
    await bench.close();
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.error(cleanError(error)); process.exitCode = 1; });
}
