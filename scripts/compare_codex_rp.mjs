#!/usr/bin/env node
// Interleaved serial comparisons: one live thread per configuration, no overlap.
import { readFileSync, writeFileSync, mkdirSync, appendFileSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { CodexHarness, scenarios } from './bench_codex_rp.mjs';

const options = Object.fromEntries(process.argv.slice(2).map(a => {
  const i = a.indexOf('='); return i < 0 ? [a.slice(2), true] : [a.slice(2, i), a.slice(i + 1)];
}));
const variants = JSON.parse(readFileSync(resolve(options.variants), 'utf8'));
const output = resolve(options.out);
if (existsSync(join(output, 'trials.jsonl'))) throw new Error(`Results already exist: ${output}; choose a new --out.`);
mkdirSync(output, { recursive: true });
const rounds = Number(options.rounds || 10);
const prompt = readFileSync(resolve(options.prompt || 'benchmarks/codex-rp/persona.txt'), 'utf8');
const bench = new CodexHarness({ timeoutMs: 20000 });
try {
  await bench.initialize();
  await bench.models();
  writeFileSync(join(output, 'metadata.json'), JSON.stringify({
    timestamp: new Date().toISOString(), variants, rounds, warmupRounds: 1,
    startupMs: bench.startupMs, prompt, serial: true,
    ordering: 'rotating variant order; first greeting is measured but labelled warmup',
    actualBackendTier: 'not exposed; configured tier only',
  }, null, 2) + '\n');
  const record = row => {
    appendFileSync(join(output, 'trials.jsonl'), JSON.stringify(row) + '\n');
    console.log(JSON.stringify(row));
  };
  const active = [];
  for (const variant of variants) {
    try {
      const thread = await bench.startThread({ ...variant, prompt });
      active.push({ ...variant, thread });
    } catch (error) {
      record({ ...variant, status: 'error', error: String(error.message).slice(0, 1000) });
    }
  }
  for (let round = 0; round <= rounds; round++) {
    for (let j = 0; j < active.length; j++) {
      const variant = active[(j + round) % active.length];
      if (variant.failed) continue;
      const result = await bench.turn(variant.thread, 'hi', variant);
      record({ variant: variant.id, model: variant.model, effort: variant.effort, tier: variant.tier,
        configuredTier: variant.thread.tier, configuredEffort: variant.thread.effort,
        scenario: 'hi', round, warmup: round === 0, ...result });
      if (result.status !== 'completed') variant.failed = true;
    }
  }
  if (options.quality) {
    for (const variant of active.filter(v => !v.failed)) {
      const thread = await bench.startThread({ ...variant, prompt });
      for (const scenario of scenarios) {
        const result = await bench.turn(thread, scenario.input, variant);
        record({ variant: variant.id, model: variant.model, effort: variant.effort, tier: variant.tier,
          scenario: scenario.id, input: scenario.input, ...result });
        if (result.status !== 'completed') break;
      }
    }
  }
} finally {
  await bench.close();
}
