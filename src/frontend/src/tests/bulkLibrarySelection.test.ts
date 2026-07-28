import { describe, expect, it } from 'vitest';

import {
  reconcileBulkSelection,
  selectAvailablePage,
  toggleBookSelection,
} from '../pages/bulkLibrarySelection';

describe('bulk library selection', () => {
  it('toggles stable book ids', () => {
    expect([...toggleBookSelection(new Set([1]), 2).selected]).toEqual([1, 2]);
    expect([...toggleBookSelection(new Set([1, 2]), 1).selected]).toEqual([2]);
  });

  it('selects only available page items and respects the limit', () => {
    const update = selectAvailablePage(
      new Set([1]),
      [
        { id: 2, in_library: false },
        { id: 3, in_library: true },
        { id: 4, in_library: false },
      ],
      2,
    );

    expect([...update.selected]).toEqual([1, 2]);
    expect(update.limitReached).toBe(true);
  });

  it('keeps failed books selected for retry', () => {
    const selected = reconcileBulkSelection(new Set([1, 2, 3, 4]), [
      { book_id: 1, status: 'added' },
      { book_id: 2, status: 'already_in_library' },
      { book_id: 3, status: 'unavailable' },
      { book_id: 4, status: 'not_found' },
    ]);

    expect([...selected]).toEqual([3, 4]);
  });
});
