import type { V1BulkLibraryResult, V1CatalogBook } from '../types/v1';

export const BULK_LIBRARY_LIMIT = 100;

export interface SelectionUpdate {
  selected: Set<number>;
  limitReached: boolean;
}

export const toggleBookSelection = (
  current: ReadonlySet<number>,
  bookId: number,
  limit = BULK_LIBRARY_LIMIT,
): SelectionUpdate => {
  const selected = new Set(current);
  if (selected.has(bookId)) {
    selected.delete(bookId);
    return { selected, limitReached: false };
  }
  if (selected.size >= limit) {
    return { selected, limitReached: true };
  }
  selected.add(bookId);
  return { selected, limitReached: false };
};

export const selectAvailablePage = (
  current: ReadonlySet<number>,
  books: ReadonlyArray<Pick<V1CatalogBook, 'id' | 'in_library'>>,
  limit = BULK_LIBRARY_LIMIT,
): SelectionUpdate => {
  const selected = new Set(current);
  let limitReached = false;
  for (const book of books) {
    if (book.in_library || selected.has(book.id)) continue;
    if (selected.size >= limit) {
      limitReached = true;
      break;
    }
    selected.add(book.id);
  }
  return { selected, limitReached };
};

export const reconcileBulkSelection = (
  current: ReadonlySet<number>,
  results: ReadonlyArray<V1BulkLibraryResult>,
): Set<number> => {
  const selected = new Set(current);
  for (const result of results) {
    if (result.status === 'added' || result.status === 'already_in_library') {
      selected.delete(result.book_id);
    }
  }
  return selected;
};
