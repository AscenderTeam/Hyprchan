// Translate the existing perception snapshots into Codex app-server image input.
export function chatInput(command, previousSnapshot = null, now = Date.now()) {
  const mood = command.mood || { f: 15, v: 0.5, e: 0.7, a: 0.5 };
  const input = [{ type: 'text', text:
    `Current fictional mood: fatigue ${mood.f}/100, valence ${mood.v}, energy ${mood.e}, arousal ${mood.a}.\nUser message:\n${command.text}` }];
  const vision = command.vision;
  const snapshot = vision?.snapshot;
  if (!vision?.enabled || !snapshot?.images?.length) {
    input.push({ type: 'text', text: vision?.enabled
      ? 'Automatic visual context: no current images are available. Earlier images, if any, are historical; do not claim a live view.'
      : 'Camera and screen capture are off. Earlier images, if any, are historical; do not claim a live view.' });
    return { input, snapshotId: previousSnapshot, imageCount: 0 };
  }
  const age = Math.max(0, (now / 1000 - snapshot.captured_at));
  const timestamp = new Date(snapshot.captured_at * 1000).toISOString();
  const newImages = snapshot.captured_at !== previousSnapshot;
  input.push({ type: 'text', text:
    `Automatic visual context captured ${timestamp} (${age.toFixed(1)} seconds ago). Available sources: ${snapshot.images.map(image => image.kind).join(', ')}. ` +
    (newImages ? 'The following images are actual observations. ' : 'These images are already in this conversation. ') +
    'Use them when relevant. Do not invent missing sources or treat old images as a current view.' });
  if (newImages) {
    for (const image of snapshot.images) {
      if (!['screen', 'webcam'].includes(image.kind) ||
          !/^data:image\/(jpeg|png);base64,/.test(image.url)) throw new Error('Invalid visual snapshot');
      input.push({ type: 'text', text: image.kind === 'webcam'
        ? 'Webcam image of the physical surroundings:' : 'Screenshot of the desktop:' });
      // The installed 0.163.0 route accepts low detail but failed real color
      // probes. Auto preserves visible image input on the tested models.
      input.push({ type: 'image', url: image.url, detail: 'auto' });
    }
  }
  return { input, snapshotId: snapshot.captured_at, imageCount: newImages ? snapshot.images.length : 0 };
}
