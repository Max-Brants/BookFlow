import type { ReactNode } from 'react';
import { createContext, useCallback, useContext, useMemo, useState } from 'react';

import { useNetworkStatus } from '../../contexts/NetworkStatusContext';
import { useDependencyEffect } from '../../hooks/useMountEffect';
import { canReadInBrowser } from '../../reader/formatCapabilities';
import { readerFileFromV1 } from '../../reader/readerApi';
import { v1Api } from '../../services/v1Api';
import type { V1BookDetail, V1Page, V1ReadingProgress } from '../../types/v1';
import { startOfflineProgressSync } from './offlineProgressSync';
import type { OfflineReadingLibrary } from './offlineReadingLibrary';
import type { OfflineReadingStore } from './offlineReadingStore';
import {
  currentOpenReaderFileIds,
  offlineReadingLibrary,
  offlineReadingStore,
  progressFromV1,
  sendPendingProgress,
} from './offlineRuntime';
import type { OfflineBook } from './types';

interface OfflineReadingApi {
  readingProgress: () => Promise<V1Page<V1ReadingProgress>>;
  book: (bookId: number) => Promise<V1BookDetail>;
}

export interface OfflineCacheSyncResult {
  books: OfflineBook[];
  failedBookIds: number[];
}

export const selectOfflineReadingCandidates = (items: V1ReadingProgress[]): V1ReadingProgress[] =>
  items
    .filter((item) => item.active === 1 && (item.progression ?? item.progress / 100) < 1)
    .toSorted(
      (left, right) =>
        Date.parse(right.reader_updated_at ?? right.updated_at) -
        Date.parse(left.reader_updated_at ?? left.updated_at),
    )
    .slice(0, 3);

/**
 * Cache candidates oldest-to-newest so the newest activity wins eviction.
 * Each candidate is isolated: one unavailable file must not block the rest.
 */
export const syncOfflineContinueReading = async (
  accountId: string,
  api: OfflineReadingApi = v1Api,
  library: OfflineReadingLibrary = offlineReadingLibrary,
  store: OfflineReadingStore = offlineReadingStore,
  protectedFileIds: () => ReadonlySet<number> = currentOpenReaderFileIds,
): Promise<OfflineCacheSyncResult> => {
  const page = await api.readingProgress();
  const candidates = selectOfflineReadingCandidates(page.items);
  const desiredBookIds = new Set(candidates.map((candidate) => candidate.book_id));
  const desiredFileIds = new Set(
    candidates
      .map((candidate) => candidate.file_id)
      .filter((fileId): fileId is number => typeof fileId === 'number'),
  );
  const failedBookIds: number[] = [];

  /* oxlint-disable no-await-in-loop -- deterministic cache eviction requires ordered writes */
  for (const progress of candidates.toReversed()) {
    try {
      const detail = await api.book(progress.book_id);
      const file =
        detail.files.find(
          (entry) => entry.id === progress.file_id && canReadInBrowser(entry.file_format),
        ) ?? detail.files.find((entry) => canReadInBrowser(entry.file_format));
      if (!file) {
        failedBookIds.push(progress.book_id);
        continue;
      }
      desiredFileIds.add(file.id);
      const readerFile = readerFileFromV1({
        bookId: progress.book_id,
        fileId: file.id,
        title: detail.book.title,
        author: detail.book.author,
        format: file.file_format,
      });
      const metadata = {
        accountId,
        bookId: progress.book_id,
        fileId: file.id,
        title: detail.book.title,
        author: detail.book.author,
        format: file.file_format,
        coverUrl: detail.book.cover_url,
        contentUrl: readerFile.contentUrl,
        progress: progressFromV1(progress),
      };
      const cached = await library.getBook(accountId, file.id);
      if (cached) {
        await library.cacheBook({ ...cached, ...metadata }, protectedFileIds());
        await library.refreshBook(accountId, file.id);
      } else {
        await library.downloadAndCache(metadata, protectedFileIds());
      }
    } catch {
      failedBookIds.push(progress.book_id);
    }
  }
  /* oxlint-enable no-await-in-loop */

  const cachedBooks = await library.listContinueReading(accountId);
  await Promise.all(
    cachedBooks
      .filter(
        (book) =>
          !desiredFileIds.has(book.fileId) &&
          !desiredBookIds.has(book.bookId) &&
          !protectedFileIds().has(book.fileId),
      )
      .map((book) => store.deleteBook(accountId, book.fileId)),
  );
  return {
    books: await library.listContinueReading(accountId),
    failedBookIds,
  };
};

type OfflineCacheStatus = 'loading' | 'syncing' | 'ready' | 'error';

interface OfflineReadingContextValue {
  books: OfflineBook[];
  cachedFileIds: ReadonlySet<number>;
  status: OfflineCacheStatus;
  failedBookCount: number;
  refreshBooks: () => Promise<void>;
}

const OfflineReadingContext = createContext<OfflineReadingContextValue>({
  books: [],
  cachedFileIds: new Set(),
  status: 'loading',
  failedBookCount: 0,
  refreshBooks: async () => undefined,
});

export const useOfflineReading = (): OfflineReadingContextValue =>
  useContext(OfflineReadingContext);

export const OfflineReadingProvider = ({
  accountId,
  children,
}: {
  accountId: string;
  children: ReactNode;
}) => {
  const { isOnline } = useNetworkStatus();
  const [books, setBooks] = useState<OfflineBook[]>([]);
  const [status, setStatus] = useState<OfflineCacheStatus>('loading');
  const [failedBookCount, setFailedBookCount] = useState(0);

  const refreshBooks = useCallback(async () => {
    try {
      const cached = await offlineReadingLibrary.listContinueReading(accountId);
      setBooks(cached);
      setStatus((current) => (current === 'syncing' ? current : 'ready'));
    } catch {
      setStatus('error');
    }
  }, [accountId]);

  useDependencyEffect(() => {
    let cancelled = false;
    void offlineReadingLibrary
      .listContinueReading(accountId)
      .then((cached) => {
        if (cancelled) return;
        setBooks(cached);
        setStatus('ready');
      })
      .catch(() => {
        if (!cancelled) setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [accountId]);

  useDependencyEffect(() => {
    const sync = startOfflineProgressSync(offlineReadingStore, accountId, sendPendingProgress);
    return () => sync.stop();
  }, [accountId]);

  useDependencyEffect(() => {
    if (!isOnline) return undefined;
    let cancelled = false;
    let syncing = false;
    const updateCache = async () => {
      if (syncing) return;
      syncing = true;
      setStatus('syncing');
      try {
        const result = await syncOfflineContinueReading(accountId);
        if (cancelled) return;
        setBooks(result.books);
        setFailedBookCount(result.failedBookIds.length);
        setStatus(result.failedBookIds.length ? 'error' : 'ready');
      } catch {
        if (!cancelled) {
          setFailedBookCount(0);
          setStatus('error');
        }
      } finally {
        syncing = false;
      }
    };
    const updateWhenVisible = () => {
      if (document.visibilityState === 'visible') void updateCache();
    };
    void updateCache();
    document.addEventListener('visibilitychange', updateWhenVisible);
    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', updateWhenVisible);
    };
  }, [accountId, isOnline]);

  const value = useMemo(
    () => ({
      books,
      cachedFileIds: new Set(books.map((book) => book.fileId)),
      status,
      failedBookCount,
      refreshBooks,
    }),
    [books, failedBookCount, refreshBooks, status],
  );

  return <OfflineReadingContext.Provider value={value}>{children}</OfflineReadingContext.Provider>;
};
