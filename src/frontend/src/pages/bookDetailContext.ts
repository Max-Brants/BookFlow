import type { TranslationKey } from '../i18n/translations';

export const SUGGESTION_LIST_LABELS = {
  overall: 'suggestions.list.overall',
  fiction: 'suggestions.list.fiction',
  non_fiction: 'suggestions.list.non_fiction',
  thriller: 'suggestions.list.thriller',
  youth: 'suggestions.list.youth',
  cooking: 'suggestions.list.cooking',
} as const satisfies Record<string, TranslationKey>;

export type SuggestionListKey = keyof typeof SUGGESTION_LIST_LABELS;
export type BookDetailContext = 'catalog' | 'library' | 'kobo' | 'trending';

export const isSuggestionListKey = (value: string | undefined): value is SuggestionListKey =>
  Boolean(value && Object.hasOwn(SUGGESTION_LIST_LABELS, value));

export const contextualBookPath = (
  context: BookDetailContext,
  bookId: number,
  listKey: SuggestionListKey = 'overall',
): string => {
  if (context === 'library') return `/library/${bookId}`;
  if (context === 'kobo') return `/kobo/${bookId}`;
  if (context === 'trending') return `/suggestions/${listKey}/${bookId}`;
  return `/catalog/${bookId}`;
};

export const bookDetailBackLink = (
  context: BookDetailContext,
  listKey: SuggestionListKey = 'overall',
): { path: string; labelKey: TranslationKey } => {
  if (context === 'library') {
    return { path: '/library', labelKey: 'catalogDetail.backLibrary' };
  }
  if (context === 'kobo') {
    return { path: '/kobo', labelKey: 'catalogDetail.backKobo' };
  }
  if (context === 'trending') {
    return {
      path: `/suggestions/${listKey}`,
      labelKey: 'catalogDetail.backTrending',
    };
  }
  return { path: '/catalog', labelKey: 'catalogDetail.back' };
};
