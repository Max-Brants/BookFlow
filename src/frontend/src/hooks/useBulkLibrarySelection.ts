import { useCallback, useState } from 'react';

import {
  reconcileBulkSelection,
  selectAvailablePage,
  toggleBookSelection,
} from '../pages/bulkLibrarySelection';
import { v1Api } from '../services/v1Api';
import type { V1BulkLibraryResponse, V1BulkLibraryResult, V1CatalogBook } from '../types/v1';
import { useDependencyEffect } from './useMountEffect';

export interface BulkLibrarySelection {
  active: boolean;
  selected: ReadonlySet<number>;
  busy: boolean;
  limitReached: boolean;
  response: V1BulkLibraryResponse | null;
  error: string | null;
  setActive: (active: boolean) => void;
  toggle: (bookId: number) => void;
  selectPage: (books: ReadonlyArray<Pick<V1CatalogBook, 'id' | 'in_library'>>) => void;
  clear: () => void;
  submit: (
    onSuccess: (successfulIds: ReadonlySet<number>, results: V1BulkLibraryResult[]) => void,
  ) => Promise<void>;
}

export const useBulkLibrarySelection = (contextKey: string): BulkLibrarySelection => {
  const [active, setActiveState] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [limitReached, setLimitReached] = useState(false);
  const [response, setResponse] = useState<V1BulkLibraryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useDependencyEffect(() => {
    setActiveState(false);
    setSelected(new Set());
    setLimitReached(false);
    setResponse(null);
    setError(null);
  }, [contextKey]);

  const setActive = useCallback((nextActive: boolean) => {
    setActiveState(nextActive);
    setLimitReached(false);
    setResponse(null);
    setError(null);
    if (!nextActive) setSelected(new Set());
  }, []);

  const toggle = useCallback((bookId: number) => {
    setResponse(null);
    setError(null);
    setSelected((current) => {
      const update = toggleBookSelection(current, bookId);
      setLimitReached(update.limitReached);
      return update.selected;
    });
  }, []);

  const selectPage = useCallback(
    (books: ReadonlyArray<Pick<V1CatalogBook, 'id' | 'in_library'>>) => {
      setResponse(null);
      setError(null);
      setSelected((current) => {
        const update = selectAvailablePage(current, books);
        setLimitReached(update.limitReached);
        return update.selected;
      });
    },
    [],
  );

  const clear = useCallback(() => {
    setSelected(new Set());
    setLimitReached(false);
    setResponse(null);
    setError(null);
  }, []);

  const submit = useCallback(
    async (
      onSuccess: (successfulIds: ReadonlySet<number>, results: V1BulkLibraryResult[]) => void,
    ) => {
      if (selected.size === 0 || busy) return;
      setBusy(true);
      setError(null);
      setResponse(null);
      try {
        const result = await v1Api.bulkAddLibraryBooks([...selected]);
        const successfulIds = new Set(
          result.results
            .filter((item) => item.status === 'added' || item.status === 'already_in_library')
            .map((item) => item.book_id),
        );
        onSuccess(successfulIds, result.results);
        const remaining = reconcileBulkSelection(selected, result.results);
        setSelected(remaining);
        setResponse(result);
        if (remaining.size === 0) setActiveState(false);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : 'The books could not be added');
      } finally {
        setBusy(false);
      }
    },
    [busy, selected],
  );

  return {
    active,
    selected,
    busy,
    limitReached,
    response,
    error,
    setActive,
    toggle,
    selectPage,
    clear,
    submit,
  };
};
