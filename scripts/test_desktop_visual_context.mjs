import test from 'node:test';
import assert from 'node:assert/strict';
import { chatInput } from './desktop_visual_context.mjs';

const snapshot = { captured_at: 100, images: [
  { kind: 'webcam', url: 'data:image/jpeg;base64,camera' },
  { kind: 'screen', url: 'data:image/jpeg;base64,screen' },
] };
const command = { text: 'зацени лицо', vision: { enabled: true, snapshot } };

test('visual requests include actual image bytes with source labels and age', () => {
  const result = chatInput(command, null, 102000);
  assert.equal(result.imageCount, 2);
  assert.deepEqual(result.input.filter(i => i.type === 'image').map(i => i.url), snapshot.images.map(i => i.url));
  assert.ok(result.input.filter(i => i.type === 'image').every(i => i.detail === 'auto'));
  assert.match(result.input[0].text, /зацени лицо/);
  assert.match(result.input[1].text, /2\.0 seconds ago/);
  assert.equal(result.snapshotId, 100);
});

test('previously delivered images are not repeatedly added to the conversation', () => {
  const result = chatInput(command, 100, 110000);
  assert.equal(result.imageCount, 0);
  assert.match(result.input[1].text, /already in this conversation/);
  assert.match(result.input[1].text, /10\.0 seconds ago/);
});

test('capture off never forwards a cached image and marks old images historical', () => {
  const result = chatInput({ ...command, vision: { enabled: false, snapshot } }, 100);
  assert.equal(result.imageCount, 0);
  assert.equal(result.input.filter(i => i.type === 'image').length, 0);
  assert.match(result.input[1].text, /capture are off/);
});

test('unavailable capture does not claim to see a live camera', () => {
  const result = chatInput({ text: 'Can you see me?', vision: { enabled: true } });
  assert.match(result.input[1].text, /no current images are available/);
});

test('screenshots alone never claim to include a webcam', () => {
  const result = chatInput({ ...command, vision: { enabled: true,
    snapshot: { ...snapshot, images: [snapshot.images[1]] } } });
  assert.equal(result.imageCount, 1);
  assert.match(result.input[1].text, /Available sources: screen\./);
});

test('image transport rejects external image URLs', () => {
  assert.throws(() => chatInput({ ...command, vision: { enabled: true,
    snapshot: { ...snapshot, images: [{ kind: 'webcam', url: 'https://example.com/image.jpg' }] } } }), /Invalid/);
});
