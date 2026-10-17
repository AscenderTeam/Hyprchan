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
  const result = chatInput(command, { screen: 100, webcam: 100 }, 110000);
  assert.equal(result.imageCount, 0);
  assert.match(result.input[1].text, /already in this conversation/);
  assert.match(result.input[1].text, /10\.0 seconds ago/);
});

test('capture off never forwards a cached image and marks old images historical', () => {
  const result = chatInput({ ...command, vision: { enabled: false, snapshot } }, { screen: 100, webcam: 100 });
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

test('a screen reaction never prevents a later chat from receiving its webcam', () => {
  const screen = chatInput({ type: 'react', language: 'ru', vision: { enabled: true,
    snapshot: { ...snapshot, images: [snapshot.images[1]] } } });
  const chat = chatInput(command, screen.deliveredImages);
  assert.equal(screen.imageCount, 1);
  assert.equal(chat.imageCount, 1);
  assert.equal(chat.input.find(i => i.type === 'image').url, snapshot.images[0].url);
});

test('autonomous observations use a NO_REPLY gate without inventing a user message', () => {
  const result = chatInput({ ...command, type: 'react', language: 'ru' });
  assert.match(result.input[0].text, /exactly NO_REPLY/);
  assert.match(result.input[0].text, /Use Russian/);
  assert.doesNotMatch(result.input[0].text, /User message:/);
});

test('heard transcripts include their paired screenshot without a webcam or invented user message', () => {
  const result = chatInput({ type: 'react', language: 'ru',
    observation: { type: 'listen_chunk', jobId: 1, index: 2, total: 5, text: 'A public test phrase.' },
    vision: { enabled: true, snapshot } }, null, 102000);
  assert.equal(result.imageCount, 1);
  assert.equal(result.input.find(item => item.type === 'image').url, snapshot.images[1].url);
  assert.match(result.input[0].text, /A public test phrase/);
  assert.match(result.input[0].text, /screenshot accompanies/);
  assert.match(result.input[0].text, /exactly NO_REPLY/);
  assert.doesNotMatch(result.input[0].text, /User message:/);
  assert.match(result.input[1].text, /2\.0 seconds ago.*Available sources: screen\./);
});

test('capture off keeps a heard transcript text-only even with a previously paired screenshot', () => {
  const result = chatInput({ type: 'react', observation: { type: 'listen_chunk', text: 'A public test phrase.' },
    vision: { enabled: false, snapshot } }, null, 102000);
  assert.equal(result.imageCount, 0);
  assert.equal(result.input.filter(item => item.type === 'image').length, 0);
  assert.match(result.input[0].text, /A public test phrase/);
  assert.match(result.input[1].text, /capture are off/);
});
