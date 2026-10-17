#!/usr/bin/env node
// Real image inference through the same bridge as the GUI. Synthetic frames only.
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { createInterface } from 'node:readline';
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const child = spawn('node', [join(root, 'scripts/desktop_codex_bridge.mjs')], { stdio: ['pipe', 'pipe', 'inherit'] });
const lines = createInterface({ input: child.stdout });
const rows = [];
const cases = [
  { color: 'red', text: 'What color is the image from my camera? Keep it short.' },
  { color: 'blue', text: 'А теперь какого цвета изображение с камеры? Ответь коротко.' },
  { color: 'green', text: 'hi' },
  { color: 'yellow', text: 'hi' },
  { color: 'purple', text: 'hi' },
  { color: null, text: 'Can you see my live camera right now?' },
];
let index = 0;
function next() {
  const scenario = cases[index];
  let snapshot = null;
  if (scenario.color) {
    const png = execFileSync('ffmpeg', ['-loglevel', 'error', '-f', 'lavfi', '-i',
      `color=c=${scenario.color}:s=512x512`, '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1']);
    snapshot = { captured_at: Date.now() / 1000, images: [
      { kind: 'webcam', url: 'data:image/png;base64,' + png.toString('base64') },
    ] };
  }
  child.stdin.write(JSON.stringify({ type: 'chat', id: index, text: scenario.text,
    vision: { enabled: !!snapshot, snapshot } }) + '\n');
}
const timeout = setTimeout(() => child.kill('SIGTERM'), 90000);
try {
  for await (const line of lines) {
    const event = JSON.parse(line);
    if (event.type === 'error') throw new Error(event.message);
    if (event.type === 'ready') next();
    if (event.type === 'done') {
      rows.push({ ...cases[index], ...event });
      assert.equal(event.status, 'completed');
      assert.equal(event.imageCount, cases[index].color ? 1 : 0);
      if (index === 0) assert.match(event.text, /red/i);
      if (index === 1) assert.match(event.text, /син|голуб/i);
      index++;
      if (index === cases.length) break;
      next();
    }
  }
  assert.equal(rows.length, cases.length);
  writeFileSync(process.argv[2] || join(root, 'benchmarks/codex-rp/results/vision-model-20261017.json'),
    JSON.stringify({ syntheticImagesOnly: true, rows }, null, 2) + '\n');
  console.log(JSON.stringify(rows.map(({ color, text, lastTextMs, imageCount }) => ({ color, text, lastTextMs, imageCount })), null, 2));
} finally {
  clearTimeout(timeout);
  child.stdin.end('{"type":"quit"}\n');
  const kill = setTimeout(() => child.kill('SIGTERM'), 3000);
  child.on('exit', () => clearTimeout(kill));
}
