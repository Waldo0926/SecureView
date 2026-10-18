/**
 * Split text into sentences, for `SentenceLines` and the Chinese layer behind it.
 *
 * English breaks after `.`, `!` or `?` followed by a space and a capital letter, a digit or an
 * opening quote, so "500 MB.", ".ciphertext", "e.g. this" and "1.5" stay inside their sentence.
 * Chinese breaks after `。`, `！` or `？`. A text with no break comes back as one sentence.
 */
export function splitSentences(text: string): string[] {
  const trimmed = text.replace(/\s+/g, ' ').trim()
  if (!trimmed) return []
  const parts = trimmed
    .split(/(?<=[.!?]["”’)]?)\s+(?=[A-Z0-9"“(])|(?<=[。！？][”’）]?)/u)
    .map((part) => part.trim())
    .filter(Boolean)
  return parts.length ? parts : [trimmed]
}
