import { describe, expect, it } from 'vitest';

import {
  canReadInBrowser,
  readerCapabilityForFormat,
  readerKindForFormat,
} from '../reader/formatCapabilities';

describe('browser reader format capabilities', () => {
  it('recognizes reflowable foliate formats case-insensitively', () => {
    expect(readerCapabilityForFormat('.EPUB')).toEqual({ kind: 'reflowable', adapter: 'foliate' });
    expect(readerCapabilityForFormat('azw3')).toEqual({ kind: 'reflowable', adapter: 'foliate' });
    expect(readerCapabilityForFormat('fb2')).toEqual({ kind: 'reflowable', adapter: 'foliate' });
  });

  it('uses the fixed-layout engines for comics and PDFs', () => {
    expect(readerCapabilityForFormat('CBZ')).toEqual({ kind: 'fixed', adapter: 'foliate' });
    expect(readerKindForFormat('pdf')).toBe('fixed');
  });

  it('leaves unsupported formats download-only', () => {
    expect(canReadInBrowser('cbr')).toBe(false);
    expect(canReadInBrowser('djvu')).toBe(false);
    expect(canReadInBrowser(null)).toBe(false);
  });
});
