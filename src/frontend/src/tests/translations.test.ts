import { describe, expect, it } from 'vitest';

import { translations } from '../i18n/translations';

describe('GUI translations', () => {
  it('keeps the English and Dutch translation catalogs in sync', () => {
    expect(Object.keys(translations.nl).toSorted()).toEqual(
      Object.keys(translations.en).toSorted(),
    );
  });

  it.each(['en', 'nl'] as const)('contains no empty %s translations', (language) => {
    const emptyKeys = Object.entries(translations[language])
      .filter(([, value]) => value.trim().length === 0)
      .map(([key]) => key);

    expect(emptyKeys).toEqual([]);
  });

  it('uses localized Dutch labels for Kobo controls', () => {
    expect(translations.nl['nav.koboSync']).toBe('Kobo-sync');
    expect(translations.nl['library.koboTitle']).toBe('Kobo-sync');
    expect(translations.nl['reader.downloadPatcher']).toBe('Windows-patcher downloaden');
  });
});
