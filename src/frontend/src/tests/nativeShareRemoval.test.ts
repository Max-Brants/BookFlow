import { readFile } from 'node:fs/promises';

import { describe, expect, it } from 'vitest';

const sourceRoot = new URL('..', import.meta.url);
const readSource = (path: string) => readFile(new URL(path, sourceRoot), 'utf8');

describe('native book sharing removal', () => {
  it('keeps the Web Share action out of the catalog and browser reader', async () => {
    const source = (
      await Promise.all([
        readSource('pages/CatalogBookPage.tsx'),
        readSource('reader/ReaderPage.tsx'),
        readSource('reader/components/BrowserReader.tsx'),
        readSource('reader/components/ReaderToolbar.tsx'),
        readSource('reader/fileActions.ts'),
        readSource('i18n/translations.ts'),
      ])
    ).join('\n');

    expect(source).not.toContain('navigator.share');
    expect(source).not.toContain('shareBookFile');
    expect(source).not.toContain('openOtherApp');
    expect(source).not.toContain('sharePreparation');
  });
});
