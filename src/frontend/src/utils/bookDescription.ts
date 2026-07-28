const LINE_BREAK_TAG = /<\s*\/?\s*br\s*\/?\s*>/gi;
const BLOCK_END_TAG = /<\s*\/\s*(?:p|div|li|h[1-6])\s*>/gi;
const HTML_COMMENT_OR_TAG = /<!--[\s\S]*?-->|<[^>]*>/g;
const HTML_ENTITY = /&(#(?:x[0-9a-f]+|\d+)|amp|apos|gt|lt|nbsp|quot);/gi;

const FALLBACK_ENTITIES: Record<string, string> = {
  amp: '&',
  apos: "'",
  gt: '>',
  lt: '<',
  nbsp: '\u00a0',
  quot: '"',
};

const decodeHtmlEntities = (value: string): string => {
  if (typeof document !== 'undefined') {
    const textarea = document.createElement('textarea');
    textarea.innerHTML = value.replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    return textarea.value;
  }

  return value.replace(HTML_ENTITY, (entity, reference: string) => {
    const normalizedReference = reference.toLowerCase();
    if (normalizedReference.startsWith('#')) {
      const hexadecimal = normalizedReference.startsWith('#x');
      const codePoint = Number.parseInt(
        normalizedReference.slice(hexadecimal ? 2 : 1),
        hexadecimal ? 16 : 10,
      );
      return codePoint <= 0x10ffff ? String.fromCodePoint(codePoint) : entity;
    }
    return FALLBACK_ENTITIES[normalizedReference] ?? entity;
  });
};

/**
 * Convert provider-supplied HTML descriptions to safe, readable plain text.
 *
 * React continues to render the result as text, never as injected HTML.
 */
export const normalizeBookDescription = (value: string): string => {
  const plainText = value
    .replace(/\r\n?/g, '\n')
    .replace(LINE_BREAK_TAG, '\n')
    .replace(BLOCK_END_TAG, '\n')
    .replace(HTML_COMMENT_OR_TAG, '');

  return decodeHtmlEntities(plainText)
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
};
