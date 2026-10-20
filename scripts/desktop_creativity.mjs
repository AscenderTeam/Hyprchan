export const tangentTool = {
  type: 'function', name: 'share_tangent',
  description: 'Your optional creative outlet: share a developed artist rabbit hole, useless trivia story, theatrical rant or imaginary mini-scene. Choose it only when you have a whim worth sharing. Once chosen, the text must contain 120–220 words across 2–4 short paragraphs; a one-line caption is rejected. Keep your kawaii personality and ground real trivia in actual sources. This text becomes your chat reply; after acceptance do not repeat it in your final message. You may then optionally send a short notification teaser.',
  inputSchema: { type: 'object', additionalProperties: false,
    properties: { text: { type: 'string', minLength: 1, maxLength: 4000,
      description: 'The complete 120–220-word in-character tangent, with paragraph breaks and direct links for researched facts.' } },
    required: ['text'] },
};

export function acceptTangent(args) {
  if (typeof args?.text !== 'string' || args.text.length > 4000) throw new Error('Supply the complete tangent as text (maximum 4000 characters)');
  const text = args.text.trim();
  const words = text.replace(/https?:\/\/\S+/g, '').split(/\s+/).filter(Boolean).length;
  const paragraphs = text.split(/\n\s*\n/).filter(part => part.trim()).length;
  if (words < 120 || words > 220 || paragraphs < 2 || paragraphs > 4) {
    throw new Error(`Not shared: ${words} words in ${paragraphs} paragraphs. Develop/revise this same thought to 120–220 words and 2–4 paragraphs, then call share_tangent again. Keep real facts accurate; fill the extra room with your own playful commentary, not invented facts.`);
  }
  return { text, words, paragraphs };
}
