// Translate the existing perception snapshots into Codex app-server image input.
import { audioPrompt } from './desktop_audio_context.mjs';
export function chatInput(command, previousSnapshot = null, now = Date.now()) {
  const mood = command.mood || { f: 15, v: 0.5, e: 0.7, a: 0.5 };
  const deliveredImages = { ...(previousSnapshot || {}) };
  const request = command.type === 'react' && command.observation
    ? audioPrompt(command.observation) + `\nUse ${command.language === 'ru' ? 'Russian' : command.language === 'en' ? 'English' : 'the language of the latest user message'}.`
    : command.type === 'react'
    ? `Automatic screen observation, about once per minute; the user has not sent a message. Decide whether you have something NEW worth saying about the supplied screen image, using the conversation and previous observations. If not, reply with exactly NO_REPLY and nothing else. An unchanged/similar screen or only changes to Hyprchan's own chat/sprite normally needs NO_REPLY. Otherwise volunteer one short reaction in your expressive kawaii voice (at most 20 words, including any tiny gesture or playful sound) to a concrete visible detail. Share your little emotional reaction; avoid a detached description of the user's work. Use ${command.language === 'ru' ? 'Russian' : command.language === 'en' ? 'English' : 'the language of the most recent user message'}. Do not greet, offer generic help, quote private screen text, invent activity, or repeat your previous observations. You may silently remember a useful new detail from supplied screen/camera images as a tentative observation, with concrete evidence. Do not speak any tool preamble: after any memory work, the only text is the reaction or exactly NO_REPLY.`
    : `Answer this user message in its own language, including every *action*.\nUser message:\n${command.text}`;
  const input = [{ type: 'text', text:
    `Current fictional mood: fatigue ${mood.f}/100, valence ${mood.v}, energy ${mood.e}, arousal ${mood.a}.\n${request}` }];
  const vision = command.vision;
  const suppliedSnapshot = vision?.snapshot;
  // Playback transcripts get desktop context; a webcam is not needed to hear media.
  const snapshot = command.observation && suppliedSnapshot
    ? { ...suppliedSnapshot, images: suppliedSnapshot.images?.filter(image => image.kind === 'screen') }
    : suppliedSnapshot;
  if (!vision?.enabled || !snapshot?.images?.length) {
    input.push({ type: 'text', text: vision?.enabled
      ? 'Automatic visual context: no current images are available. Earlier images, if any, are historical; do not claim a live view.'
      : 'Camera and screen capture are off. Earlier images, if any, are historical; do not claim a live view.' });
    return { input, deliveredImages, imageCount: 0 };
  }
  const age = Math.max(0, (now / 1000 - snapshot.captured_at));
  const timestamp = new Date(snapshot.captured_at * 1000).toISOString();
  const newImages = snapshot.images.filter(image => deliveredImages[image.kind] !== snapshot.captured_at);
  input.push({ type: 'text', text:
    `Automatic visual context captured ${timestamp} (${age.toFixed(1)} seconds ago). Available sources: ${snapshot.images.map(image => image.kind).join(', ')}. ` +
    (newImages.length ? 'The following images are actual observations. ' : 'These images are already in this conversation. ') +
    'Use them when relevant. Do not invent missing sources or treat old images as a current view.' });
  if (newImages.length) {
    for (const image of newImages) {
      if (!['screen', 'webcam'].includes(image.kind) ||
          !/^data:image\/(jpeg|png);base64,/.test(image.url)) throw new Error('Invalid visual snapshot');
      input.push({ type: 'text', text: image.kind === 'webcam'
        ? 'Webcam image of the physical surroundings:' : 'Screenshot of the desktop:' });
      // The installed 0.163.0 route accepts low detail but failed real color
      // probes. Auto preserves visible image input on the tested models.
      input.push({ type: 'image', url: image.url, detail: 'auto' });
      deliveredImages[image.kind] = snapshot.captured_at;
    }
  }
  return { input, snapshotId: snapshot.captured_at, deliveredImages, imageCount: newImages.length };
}
