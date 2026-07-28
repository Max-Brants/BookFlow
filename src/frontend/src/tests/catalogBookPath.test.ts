import { describe, expect, it } from 'vitest';

import { catalogBookPath } from '../utils/catalogBookPath';

describe('catalogBookPath', () => {
  it('uses a normalized ISBN-13 route in preference to ISBN-10', () => {
    expect(
      catalogBookPath({
        id: 42,
        isbn: '0-306-40615-2',
        isbn_13: '978-0-306-40615-7',
      }),
    ).toBe('/catalog/isbn/9780306406157');
  });

  it('uses a normalized ISBN route when ISBN-13 is unavailable', () => {
    expect(catalogBookPath({ id: 42, isbn: '0 306 40615 2' })).toBe('/catalog/isbn/0306406152');
  });

  it('falls back to the numeric catalog route when no usable ISBN exists', () => {
    expect(catalogBookPath({ id: 42, isbn: 'too-short', isbn_13: null })).toBe('/catalog/42');
  });
});
