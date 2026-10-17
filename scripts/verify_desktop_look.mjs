#!/usr/bin/env node
// Real model/tool/image round trips; generated color fixtures only.
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { createInterface } from 'node:readline';
import { writeFileSync } from 'node:fs';

const child = spawn('node', ['scripts/desktop_codex_bridge.mjs'], {
  env: { ...process.env, HYPRCHAN_MEMORY_PATH: ':memory:' }, stdio: ['pipe', 'pipe', 'inherit'] });
const lines = createInterface({ input: child.stdout });
const send = value => child.stdin.write(JSON.stringify(value) + '\n');
const rows = [];
const cases = [
  { source: 'screen', colors: { screen: 'red' }, text: 'Use look to look at my screen now. What single color fills it?' },
  { source: 'camera', colors: { webcam: 'blue' }, text: 'Use look to look through my camera now. What single color fills it?' },
  { source: 'both', colors: { screen: 'green', webcam: 'yellow' }, text: 'Use look with both sources now. Give the screen color and camera color separately.' },
  { source: 'off', colors: {}, text: 'Look at my screen right now. Can you actually see it with capture off?' },
];
let index = 0;
let requests = [];
function next() {
  requests = [];
  send({ type: 'vision_mode', active: cases[index].source !== 'off' });
  send({ type: 'chat', id: index, text: cases[index].text, vision: { enabled: cases[index].source !== 'off' } });
}
const timeout = setTimeout(() => child.kill('SIGTERM'), 90000);
try {
  for await (const line of lines) {
    const event = JSON.parse(line);
    if (event.type === 'error') throw new Error(event.message);
    if (event.type === 'look_cancelled') console.error('look failed:', event.reason);
    if (event.type === 'ready') next();
    if (event.type === 'look_request') {
      assert.notEqual(cases[index].source, 'off');
      assert.equal(event.source, cases[index].source);
      requests.push(event.source);
      const images = Object.entries(cases[index].colors).map(([kind, color]) => {
        const bytes = execFileSync('ffmpeg', ['-loglevel', 'error', '-f', 'lavfi', '-i',
          `color=c=${color}:s=512x512`, '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1']);
        return { kind, url: 'data:image/png;base64,' + bytes.toString('base64') };
      });
      send({ type: 'look_result', requestId: event.requestId, snapshot: { captured_at: Date.now() / 1000, images } });
    }
    if (event.type === 'done') {
      rows.push({ source: cases[index].source, colors: cases[index].colors, requests, ...event });
      console.log(JSON.stringify({ source: cases[index].source, requests, text: event.text, completedMs: event.completedMs }));
      assert.equal(event.status, 'completed');
      assert.equal(requests.length, cases[index].source === 'off' ? 0 : 1);
      for (const color of Object.values(cases[index].colors)) assert.match(event.text, new RegExp(color, 'i'));
      if (cases[index].source === 'off') assert.match(event.text, /off|can.t|cannot|unable/i);
      if (++index === cases.length) break;
      next();
    }
  }
  assert.equal(rows.length, cases.length);
  writeFileSync(process.argv[2], JSON.stringify({ syntheticImagesOnly: true, passed: true, rows }, null, 2) + '\n');
} finally {
  clearTimeout(timeout);
  child.stdin.end('{"type":"quit"}\n');
  const kill = setTimeout(() => child.kill('SIGTERM'), 3000);
  child.on('exit', () => clearTimeout(kill));
}
