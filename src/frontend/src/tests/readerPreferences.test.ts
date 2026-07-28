import { describe, expect, it } from 'vitest';

import { sanitizeReaderPreferences } from '../reader/readerPreferences';

describe('reader preference validation', () => {
  it('clamps user-controlled numeric settings and rejects unknown enums', () => {
    expect(
      sanitizeReaderPreferences({
        theme: 'neon',
        fontFamily: 'serif',
        fontSize: 999,
        lineHeight: 0.2,
        flow: 'scrolled',
        spread: 'unknown',
      }),
    ).toMatchObject({
      theme: 'light',
      fontFamily: 'serif',
      fontSize: 200,
      lineHeight: 1.1,
      flow: 'scrolled',
      spread: 'single',
    });
  });
});
