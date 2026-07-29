import { describe, expect, it, vi } from 'vitest';

import { initialOnlineStatus } from '../contexts/NetworkStatusContext';
import {
  MemoryOfflineReadingStore,
  OfflineReadingLibrary,
  type CacheBookInput,
  type ContentFetcher,
} from '../library/offline';
import {
  selectOfflineReadingCandidates,
  syncOfflineContinueReading,
} from '../library/offline/OfflineReadingCoordinator';
import type { V1BookDetail, V1ReadingProgress } from '../types/v1';

const accountId = 'offline-user';
const timestamp = (day: number) => `2026-07-${String(day).padStart(2, '0')}T12:00:00.000Z`;

const progress = (bookId: number, day: number, overrides = {}): V1ReadingProgress => ({
  book_id: bookId,
  file_id: bookId,
  progress: day,
  progression: day / 100,
  active: 1,
  source: 'reader',
  revision: 1,
  updated_at: timestamp(day),
  reader_updated_at: timestamp(day),
  ...overrides,
});

const detail = (bookId: number): V1BookDetail => ({
  book: {
    id: bookId,
    title: `Book ${bookId}`,
    author: 'Offline Author',
    language: 'en',
    publish_year: 2026,
    cover_url: null,
    formats: ['epub'],
    request_status: null,
    request_process_status: null,
    kobo_state: null,
  },
  files: [
    {
      id: bookId,
      file_format: 'epub',
      size_bytes: 12,
      mime_type: 'application/epub+zip',
      imported_at: timestamp(1),
      granted_at: timestamp(1),
    },
  ],
  entitled: true,
  request: null,
  kobo: null,
});

const cachedInput = (bookId: number): CacheBookInput => ({
  accountId,
  bookId,
  fileId: bookId,
  title: `Book ${bookId}`,
  author: 'Offline Author',
  format: 'epub',
  coverUrl: null,
  contentUrl: `/api/v1/library/books/${bookId}/files/${bookId}/content`,
  content: new Blob([`book-${bookId}`], { type: 'application/epub+zip' }),
  progress: {
    locator: '',
    progression: bookId / 100,
    completed: false,
    lastReadAt: timestamp(bookId),
  },
});

const requestUrl = (input: RequestInfo | URL): string => {
  if (typeof input === 'string') return input;
  return input instanceof URL ? input.href : input.url;
};

const partialFailureFetcher: ContentFetcher = async (input) => {
  const url = requestUrl(input);
  if (url.includes('/2/')) throw new Error('temporary download failure');
  return new Response(new Blob([url]), {
    status: 200,
    headers: { 'Content-Type': 'application/epub+zip' },
  });
};

describe('offline PWA flow', () => {
  it('detects a cold offline start without making a request', () => {
    vi.stubGlobal('navigator', { onLine: false });
    expect(initialOnlineStatus()).toBe(false);
    vi.unstubAllGlobals();
  });

  it('selects only the three newest incomplete active books', () => {
    const selected = selectOfflineReadingCandidates([
      progress(1, 1),
      progress(4, 4),
      progress(2, 2),
      progress(5, 5, { active: 0 }),
      progress(3, 3),
      progress(6, 6, { progression: 1 }),
    ]);
    expect(selected.map((item) => item.book_id)).toEqual([4, 3, 2]);
  });

  it('keeps syncing after one candidate fails and removes stale cached books', async () => {
    const store = new MemoryOfflineReadingStore();
    const library = new OfflineReadingLibrary(store, partialFailureFetcher, () => timestamp(10));
    await library.cacheBook(cachedInput(9));
    const api = {
      readingProgress: async () => ({
        items: [progress(1, 1), progress(2, 2), progress(3, 3)],
        offset: 0,
        limit: 3,
      }),
      book: async (bookId: number) => detail(bookId),
    };

    const result = await syncOfflineContinueReading(
      accountId,
      api,
      library,
      store,
      () => new Set(),
    );

    expect(result.failedBookIds).toEqual([2]);
    expect(result.books.map((book) => book.fileId)).toEqual([3, 1]);
    expect(await library.getBook(accountId, 9)).toBeNull();
  });

  it('retains an already cached desired book when its refresh fails', async () => {
    const store = new MemoryOfflineReadingStore();
    let failRefresh = false;
    const fetcher: ContentFetcher = async () => {
      if (failRefresh) throw new Error('offline refresh failed');
      return new Response(new Blob(['cached']), {
        status: 200,
        headers: { 'Content-Type': 'application/epub+zip' },
      });
    };
    const library = new OfflineReadingLibrary(store, fetcher, () => timestamp(10));
    await library.cacheBook(cachedInput(2));
    failRefresh = true;
    const api = {
      readingProgress: async () => ({
        items: [progress(2, 2)],
        offset: 0,
        limit: 3,
      }),
      book: async () => detail(2),
    };

    const result = await syncOfflineContinueReading(
      accountId,
      api,
      library,
      store,
      () => new Set(),
    );

    expect(result.failedBookIds).toEqual([2]);
    expect(result.books.map((book) => book.fileId)).toEqual([2]);
  });
});
