import { useDependencyEffect } from '../../hooks/useMountEffect';
import { canReadInBrowser } from '../../reader/formatCapabilities';
import { readerFileFromV1 } from '../../reader/readerApi';
import { v1Api } from '../../services/v1Api';
import { startOfflineProgressSync } from './offlineProgressSync';
import {
  currentOpenReaderFileIds,
  offlineReadingLibrary,
  offlineReadingStore,
  progressFromV1,
  sendPendingProgress,
} from './offlineRuntime';

interface OfflineReadingCoordinatorProps {
  accountId: string;
}

/**
 * Keeps the three most recently active Continue Reading titles available.
 * Failures are intentionally silent: reading online must never depend on the
 * background offline cache succeeding.
 */
export const OfflineReadingCoordinator = ({ accountId }: OfflineReadingCoordinatorProps) => {
  useDependencyEffect(() => {
    const sync = startOfflineProgressSync(offlineReadingStore, accountId, sendPendingProgress);
    let cancelled = false;
    let caching = false;

    const cacheContinueReading = async () => {
      if (caching || !navigator.onLine) return;
      caching = true;
      try {
        const page = await v1Api.readingProgress();
        const candidates = page.items
          .filter((item) => item.active === 1 && (item.progression ?? item.progress / 100) < 1)
          .toSorted(
            (left, right) =>
              Date.parse(right.reader_updated_at ?? right.updated_at) -
              Date.parse(left.reader_updated_at ?? left.updated_at),
          )
          .slice(0, 3)
          .toReversed();
        const selectedFileIds = new Set<number>();

        await Promise.all(
          candidates.map(async (progress) => {
            if (cancelled) return;
            const detail = await v1Api.book(progress.book_id);
            const file =
              detail.files.find(
                (entry) => entry.id === progress.file_id && canReadInBrowser(entry.file_format),
              ) ?? detail.files.find((entry) => canReadInBrowser(entry.file_format));
            if (!file) return;
            selectedFileIds.add(file.id);
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
            const cached = await offlineReadingLibrary.getBook(accountId, file.id);
            const protectedFileIds = currentOpenReaderFileIds();
            if (cached) {
              await offlineReadingLibrary.cacheBook({ ...cached, ...metadata }, protectedFileIds);
              await offlineReadingLibrary.refreshBook(accountId, file.id);
            } else {
              await offlineReadingLibrary.downloadAndCache(metadata, protectedFileIds);
            }
          }),
        );
        if (!cancelled) {
          const cachedBooks = await offlineReadingLibrary.listContinueReading(accountId);
          await Promise.all(
            cachedBooks
              .filter(
                (book) =>
                  !selectedFileIds.has(book.fileId) && !currentOpenReaderFileIds().has(book.fileId),
              )
              .map((book) => offlineReadingStore.deleteBook(accountId, book.fileId)),
          );
        }
      } finally {
        caching = false;
      }
    };

    const updateCache = () => void cacheContinueReading().catch(() => undefined);
    const updateCacheWhenVisible = () => {
      if (document.visibilityState === 'visible') updateCache();
    };
    void cacheContinueReading().catch(() => undefined);
    window.addEventListener('online', updateCache);
    document.addEventListener('visibilitychange', updateCacheWhenVisible);
    return () => {
      cancelled = true;
      sync.stop();
      window.removeEventListener('online', updateCache);
      document.removeEventListener('visibilitychange', updateCacheWhenVisible);
    };
  }, [accountId]);

  return null;
};
