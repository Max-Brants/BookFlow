import { describe, expect, it } from 'vitest';

import {
  bookDetailBackLink,
  contextualBookPath,
  isSuggestionListKey,
} from '../pages/bookDetailContext';

describe('book detail contexts', () => {
  it('builds stable paths for each owning section', () => {
    expect(contextualBookPath('catalog', 42)).toBe('/catalog/42');
    expect(contextualBookPath('library', 42)).toBe('/library/42');
    expect(contextualBookPath('kobo', 42)).toBe('/kobo/42');
    expect(contextualBookPath('trending', 42, 'fiction')).toBe('/suggestions/fiction/42');
  });

  it('returns context-specific back destinations and labels', () => {
    expect(bookDetailBackLink('catalog')).toEqual({
      path: '/catalog',
      labelKey: 'catalogDetail.back',
    });
    expect(bookDetailBackLink('library')).toEqual({
      path: '/library',
      labelKey: 'catalogDetail.backLibrary',
    });
    expect(bookDetailBackLink('kobo')).toEqual({
      path: '/kobo',
      labelKey: 'catalogDetail.backKobo',
    });
    expect(bookDetailBackLink('trending', 'cooking')).toEqual({
      path: '/suggestions/cooking',
      labelKey: 'catalogDetail.backTrending',
    });
  });

  it('accepts only known trending list keys', () => {
    expect(isSuggestionListKey('overall')).toBe(true);
    expect(isSuggestionListKey('non_fiction')).toBe(true);
    expect(isSuggestionListKey('unknown')).toBe(false);
    expect(isSuggestionListKey(undefined)).toBe(false);
  });
});
