import test from 'node:test';
import assert from 'node:assert/strict';
import { EmoteRequests, emoteExamples, emoteInstructions, automaticGestures } from './desktop_emotes.mjs';
import { reasoningFor } from './desktop_reasoning.mjs';

test('runnable cookbook is in the initial instructions, not repeated in each turn', () => {
  assert.ok(emoteExamples.length >= 18);
  assert.equal(new Set(emoteExamples.map(example => example.id)).size, emoteExamples.length);
  const perTurn = new EmoteRequests(() => {}).context();
  for (const example of emoteExamples) {
    assert.equal(emoteInstructions.split(example.code).length - 1, 1, example.id);
    assert.ok(!perTurn.includes(example.code), example.id);
  }
});

test('model gets the renderer catalogue and a tool requirement for other movements', () => {
  assert.ok(automaticGestures.some(item => item.id === 'heart_hug'));
  for (const item of automaticGestures) {
    for (const action of item.examples) assert.ok(emoteInstructions.includes(`*${action}*`));
  }
  assert.match(emoteInstructions, /outside this list, call emote_play/);
  assert.match(emoteInstructions, /Wait for started:true/);
  assert.match(emoteInstructions, /unmapped_action.*did not animate/);
});

test('the per-turn appearance describes the currently visible costume', () => {
  const requests = new EmoteRequests(() => {});
  requests.mode = '3d'; requests.outfit = 'cyan_yellow';
  assert.match(requests.context(), /Current 3D costume: white layered collar/);
  requests.outfit = 'hoodie';
  assert.match(requests.context(), /Current 3D costume: white hoodie/);
  requests.mode = 'pixel'; requests.outfit = 'cyan_yellow';
  assert.match(requests.context(), /white hoodie/);
});

test('emote tool waits for GUI persistence acknowledgement', async () => {
  const sent = [];
  const requests = new EmoteRequests(event => sent.push(event));
  const result = requests.request('emote_create', { id: 'puff' });
  assert.equal(sent[0].type, 'emote_request');
  requests.receive({requestId: sent[0].requestId, result: {saved:true,started:true}});
  assert.deepEqual(await result, {saved:true,started:true});
  assert.equal(requests.pending.size, 0);
});

test('aborted emotes reject and late acknowledgements cannot revive them', async () => {
  const sent = []; const control = new AbortController();
  const requests = new EmoteRequests(event => sent.push(event));
  const result = requests.request('emote_play', {id:'pout'}, control.signal);
  control.abort();
  await assert.rejects(result, /interrupted/);
  assert.equal(sent[1].type, 'emote_cancelled');
  assert.equal(requests.receive({requestId:sent[0].requestId,result:{started:true}}), false);
});

test('GUI errors and timeouts remain errors', async () => {
  const sent = []; const requests = new EmoteRequests(event => sent.push(event), 15);
  const result = requests.request('emote_create', {});
  requests.receive({requestId:sent[0].requestId,error:'SyntaxError'});
  await assert.rejects(result, /SyntaxError/);
  await assert.rejects(requests.request('emote_play', {}), /did not respond/);
});

test('greetings stay low; meaningful turns can think; explicit override is honored', () => {
  for (const text of ['hi','hi!','Привет!','hello~']) assert.equal(reasoningFor({type:'chat',text}, ''), 'low');
  for (const text of ['hi, create a new emote', 'Почему камера не работает?', 'write an animation'])
    assert.equal(reasoningFor({type:'chat',text}, ''), 'medium');
  assert.equal(reasoningFor({type:'react'}, ''), 'medium');
  assert.equal(reasoningFor({type:'chat',text:'hi'}, 'high'), 'high');
});
