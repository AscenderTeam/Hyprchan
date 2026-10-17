#!/usr/bin/env node
// Small interactive demonstration of the benchmarked persistent dialogue path.
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CodexHarness } from './bench_codex_rp.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const options = {
  model: process.env.HYPRCHAN_CODEX_MODEL || 'gpt-6-luna',
  effort: process.env.HYPRCHAN_CODEX_EFFORT || 'low',
  tier: process.env.HYPRCHAN_CODEX_TIER || 'fast',
};
const prompt = readFileSync(join(root, 'benchmarks/codex-rp/persona.txt'), 'utf8');
const bench = new CodexHarness();
const input = createInterface({ input: process.stdin });
// Create the iterator before startup so piped input is buffered correctly.
const lines = input[Symbol.asyncIterator]();
try {
  console.error(`Preparing ${options.model}, reasoning=${options.effort}, tier=${options.tier}…`);
  await bench.initialize();
  const thread = await bench.startThread({ ...options, prompt });
  const warmup = await bench.turn(thread,
    'Startup context: you have just settled onto the desktop. Acknowledge quietly in a few words; the user has not spoken yet.', options);
  if (warmup.status !== 'completed') throw new Error(warmup.errors.join('; ') || warmup.status);
  console.error('Ready. Type a message; /quit exits. First-turn setup is complete.');
  for await (const line of lines) {
    if (line.trim() === '/quit') break;
    if (!line.trim()) continue;
    process.stdout.write('Hyprchan: ');
    const stream = message => {
      if (message.method === 'item/agentMessage/delta' && message.params.threadId === thread.id) {
        process.stdout.write(message.params.delta);
      }
    };
    bench.on('notification', stream);
    const result = await bench.turn(thread, line, options);
    bench.off('notification', stream);
    process.stdout.write('\n');
    console.error(`[first text ${result.firstTextMs} ms; full text ${result.lastTextMs} ms; complete ${result.completedMs} ms]`);
    if (result.status !== 'completed') console.error(`Inference ${result.status}: ${result.errors.join('; ')}`);
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  input.close();
  await bench.close();
}
