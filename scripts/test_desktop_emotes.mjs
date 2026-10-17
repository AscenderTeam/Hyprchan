import test from 'node:test';
import assert from 'node:assert/strict';
import { EmoteRequests } from './desktop_emotes.mjs';
import { reasoningFor } from './desktop_reasoning.mjs';

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
