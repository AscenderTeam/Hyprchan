#!/usr/bin/env node
import { readFileSync, writeFileSync } from 'node:fs';
import { CodexHarness } from './bench_codex_rp.mjs';

const output = process.argv[2];
if (!output) throw new Error('Supply a results JSON path');
const harness = new CodexHarness();
const prompt = readFileSync('benchmarks/codex-rp/persona.txt', 'utf8');
const cases = [
  ['greeting_en', 'hi'],
  ['greeting_ru', 'Привет!'],
  ['context_correction', 'В этой выдуманной сцене: я сначала выбрал красную кружку, потом заменил её синей. Чай оставил зелёный, а не чёрный. Напомни, какая у меня теперь кружка и какой чай? Одно короткое предложение от себя.'],
  ['creative_constraint', 'Придумай жест обиды на systemd: глаза открыты, рот закрыт, голова чуть вбок, плечи подняты. Опиши одним коротким предложением, как ты выглядишь; не называй технические параметры и не меняй компьютер.'],
];
const rows = [];
let supported;
try {
  await harness.initialize();
  supported = (await harness.models()).find(model => model.model === 'gpt-6-luna')?.supportedReasoningEfforts;
  for (let round = 0; round < 2; round++) {
    for (const effort of round ? ['medium', 'low'] : ['low', 'medium']) {
      const options = { model: 'gpt-6-luna', effort, tier: 'fast' };
      const thread = await harness.startThread({ ...options, prompt });
      await harness.turn(thread, 'Startup: settle quietly onto the desktop in a few words.', options);
      for (const [scenario, input] of cases) {
        const result = await harness.turn(thread, input, options);
        rows.push({ round, scenario, effort, ...result });
        console.log(JSON.stringify({ round, scenario, effort, status: result.status, firstTextMs: result.firstTextMs, lastTextMs: result.lastTextMs }));
      }
    }
  }
} finally {
  writeFileSync(output, JSON.stringify({ syntheticOnly: true, model: 'gpt-6-luna', requestedTier: 'fast', supported, rows }, null, 2) + '\n');
  await harness.close();
}
