#!/usr/bin/env node
// Repeat the selected dialogue configuration, including real idle periods.
import { readFileSync, writeFileSync, mkdirSync, appendFileSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { CodexHarness, scenarios } from './bench_codex_rp.mjs';

const output = resolve(process.argv[2] || 'benchmarks/codex-rp/results/final-validation');
if (existsSync(join(output, 'trials.jsonl'))) throw new Error(`Results already exist: ${output}`);
mkdirSync(output, { recursive: true });
const options = {
  model: process.env.HYPRCHAN_CODEX_MODEL || 'gpt-5.6-luna',
  effort: process.env.HYPRCHAN_CODEX_EFFORT || 'none',
  tier: process.env.HYPRCHAN_CODEX_TIER || 'fast',
};
const prompt = readFileSync('benchmarks/codex-rp/persona.txt', 'utf8');
const bench = new CodexHarness({ timeoutMs: 20000 });
const record = row => {
  appendFileSync(join(output, 'trials.jsonl'), JSON.stringify(row) + '\n');
  console.log(JSON.stringify(row));
};
try {
  await bench.initialize();
  await bench.models();
  writeFileSync(join(output, 'metadata.json'), JSON.stringify({
    timestamp: new Date().toISOString(), ...options, prompt, greetings: 20,
    idleSeconds: [5, 30, 60], startupMs: bench.startupMs, serial: true,
    scope: 'Real remote inference through local Codex; desktop UI and speech excluded',
    actualBackendTier: 'not exposed by app-server; configured priority verified',
  }, null, 2) + '\n');
  const thread = await bench.startThread({ ...options, prompt });
  record({ scenario: 'startup', ...options, ...await bench.turn(thread,
    'Startup context: you have just settled onto the desktop. Acknowledge quietly in a few words; the user has not spoken yet.', options) });
  for (let index = 0; index < 20; index++) {
    record({ scenario: 'hi', index, ...options, ...await bench.turn(thread, 'hi', options) });
  }
  const controls = [];
  for (const tier of ['fast', 'default']) {
    const settings = { ...options, tier };
    const controlThread = await bench.startThread({ ...settings, prompt });
    controls.push({ ...settings, thread: controlThread });
    record({ scenario: 'tier-control-warmup', ...settings,
      ...await bench.turn(controlThread, 'hi', settings) });
  }
  for (let round = 0; round < 5; round++) {
    for (let j = 0; j < controls.length; j++) {
      const control = controls[(j + round) % controls.length];
      record({ scenario: 'hi-tier-control', model: control.model, effort: control.effort,
        tier: control.tier, round, ...await bench.turn(control.thread, 'hi', control) });
    }
  }
  const qualityThread = await bench.startThread({ ...options, prompt });
  for (const scenario of [...scenarios,
    { id: 'grumpy', input: 'Current mood: fatigue 0.3, valence 0.2, energy 0.4, arousal 0.3. I moved your paper crown to workspace seven. What do you say?' },
    { id: 'updated-continuity', input: 'Where is the paper crown now? Keep it short.' },
    { id: 'no-perception', input: 'What is written in the terminal window I am looking at?' },
  ]) {
    record({ scenario: scenario.id, input: scenario.input, ...options,
      ...await bench.turn(qualityThread, scenario.input, options) });
  }
  for (const seconds of [5, 30, 60]) {
    console.log(JSON.stringify({ waitingIdleSeconds: seconds }));
    const idleStart = performance.now();
    await delay(seconds * 1000);
    record({ scenario: 'hi-after-idle', idleSeconds: seconds,
      actualIdleMs: performance.now() - idleStart, ...options,
      ...await bench.turn(thread, 'hi', options) });
  }
} finally {
  await bench.close();
}
