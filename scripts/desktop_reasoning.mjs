// Preserve a cheap greeting path while allowing thought on meaningful turns.
export function reasoningFor(command, configured = process.env.HYPRCHAN_CODEX_EFFORT) {
  if (configured) return configured;
  const text = String(command.text || '').trim();
  return command.type === 'chat' && /^(hi+|hey+|hello+|hiya|привет|приве+т|хай|ку|здравствуй)[\s!.~♡✨]*$/iu.test(text)
    ? 'low' : 'medium';
}
