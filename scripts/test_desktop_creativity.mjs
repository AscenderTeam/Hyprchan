import test from 'node:test';
import assert from 'node:assert/strict';
import { acceptTangent } from './desktop_creativity.mjs';

const story = (words, paragraphs = 2) => Array.from({ length: paragraphs }, (_, index) =>
  Array(Math.floor(words / paragraphs) + (index < words % paragraphs ? 1 : 0)).fill('мяу').join(' ')).join('\n\n');

test('chosen tangents must be developed, while preserving the exact accepted story', () => {
  for (const words of [120, 167, 220]) {
    const text = story(words);
    assert.deepEqual(acceptTangent({ text }), { text, words, paragraphs: 2 });
  }
  for (const words of [0, 30, 119, 221]) {
    assert.throws(() => acceptTangent({ text: story(words) }), /Not shared/);
  }
});

test('paragraphs and source links cannot substitute for the requested prose', () => {
  for (const paragraphs of [1, 5]) assert.throws(() => acceptTangent({ text: story(150, paragraphs) }), /paragraphs/);
  assert.throws(() => acceptTangent({ text: story(119) + ' https://example.org/fact' }), /119 words/);
  assert.equal(acceptTangent({ text: story(120) + ' https://example.org/fact' }).words, 120);
});

test('missing and oversized tool arguments are rejected', () => {
  for (const args of [null, {}, { text: 7 }, { text: 'x'.repeat(4001) }]) assert.throws(() => acceptTangent(args), /complete tangent/);
});
