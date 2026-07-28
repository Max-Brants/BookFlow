import { describe, expect, it } from 'vitest';

import { normalizeBookDescription } from '../utils/bookDescription';

describe('normalizeBookDescription', () => {
  it('decodes HTML entities and provider line-break tags', () => {
    expect(
      normalizeBookDescription(
        'Leven als Gort &amp; vrienden</br>Een tweede regel<br/>Een derde regel',
      ),
    ).toBe('Leven als Gort & vrienden\nEen tweede regel\nEen derde regel');
  });

  it('removes markup while preserving its readable text', () => {
    expect(
      normalizeBookDescription(
        '<p>Een <strong>rijke</strong> beschrijving.</p><p>Nog een alinea.</p>',
      ),
    ).toBe('Een rijke beschrijving.\nNog een alinea.');
  });

  it('decodes numeric entities and normalizes whitespace', () => {
    expect(normalizeBookDescription('ISBN&#58;\u00a0 9789026175220\n\n\nEinde')).toBe(
      'ISBN:  9789026175220\n\nEinde',
    );
  });
});
