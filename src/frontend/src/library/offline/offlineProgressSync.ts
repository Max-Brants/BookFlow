import { isServerProgressNewer } from './offlineReadingLibrary';
import type { OfflineReadingStore } from './offlineReadingStore';
import type { OfflineBook, ProgressSender, ProgressSyncSummary, ReadingProgress } from './types';

const EMPTY_SUMMARY: ProgressSyncSummary = { sent: 0, discardedAsStale: 0, failed: 0 };

const replaceProgressWhenCurrentIsNotNewer = (
  book: OfflineBook,
  incoming: ReadingProgress,
): OfflineBook => {
  if (isServerProgressNewer(book.progress.lastReadAt, incoming.lastReadAt)) return book;
  return { ...book, progress: incoming, lastAccessedAt: incoming.lastReadAt };
};

const removeQueueEntryIfUnchanged = async (
  store: OfflineReadingStore,
  accountId: string,
  fileId: number,
  sentAt: string,
): Promise<void> => {
  // A user may turn a page while the request is in flight. Never discard that
  // newer action merely because the older request has completed.
  const current = await store.getPendingProgress(accountId, fileId);
  if (current?.lastReadAt === sentAt) {
    await store.deletePendingProgress(accountId, fileId);
  }
};

/** Flushes pending local updates and refuses to overwrite a newer server position. */
export const syncOfflineProgress = async (
  store: OfflineReadingStore,
  accountId: string,
  send: ProgressSender,
): Promise<ProgressSyncSummary> => {
  const pending = await store.listPendingProgress(accountId);
  const results = await Promise.all(
    pending.map(async (update): Promise<ProgressSyncSummary> => {
      try {
        const response = await send(update);
        const server = response.progress;
        if (server && isServerProgressNewer(server.lastReadAt, update.lastReadAt)) {
          const book = await store.getBook(accountId, update.fileId);
          if (book) await store.putBook(replaceProgressWhenCurrentIsNotNewer(book, server));
          await removeQueueEntryIfUnchanged(store, accountId, update.fileId, update.lastReadAt);
          return { sent: 0, discardedAsStale: 1, failed: 0 };
        }
        if (server) {
          const book = await store.getBook(accountId, update.fileId);
          if (book) await store.putBook(replaceProgressWhenCurrentIsNotNewer(book, server));
        }
        await removeQueueEntryIfUnchanged(store, accountId, update.fileId, update.lastReadAt);
        return { sent: 1, discardedAsStale: 0, failed: 0 };
      } catch {
        // Leave this exact action in the queue. The next online event retries it.
        return { sent: 0, discardedAsStale: 0, failed: 1 };
      }
    }),
  );
  return results.reduce(
    (summary, result) => ({
      sent: summary.sent + result.sent,
      discardedAsStale: summary.discardedAsStale + result.discardedAsStale,
      failed: summary.failed + result.failed,
    }),
    { ...EMPTY_SUMMARY },
  );
};

export interface OfflineProgressSyncController {
  syncNow(): Promise<ProgressSyncSummary>;
  stop(): void;
}

/**
 * Sync immediately, after reconnect, whenever the PWA becomes visible, and
 * every five minutes while it is open. Timers are deliberately not used in a
 * service worker, because a suspended PWA cannot reliably run them.
 */
export const startOfflineProgressSync = (
  store: OfflineReadingStore,
  accountId: string,
  send: ProgressSender,
  windowObject: Pick<
    Window,
    'addEventListener' | 'removeEventListener' | 'setInterval' | 'clearInterval'
  > = window,
  documentObject: Pick<
    Document,
    'addEventListener' | 'removeEventListener' | 'visibilityState'
  > = document,
): OfflineProgressSyncController => {
  let stopped = false;
  const syncNow = async () => {
    if (stopped || (typeof navigator !== 'undefined' && !navigator.onLine)) return EMPTY_SUMMARY;
    return syncOfflineProgress(store, accountId, send);
  };
  const onOnline = () => void syncNow();
  const onVisibilityChange = () => {
    if (documentObject.visibilityState === 'visible') void syncNow();
  };
  windowObject.addEventListener('online', onOnline);
  documentObject.addEventListener('visibilitychange', onVisibilityChange);
  const timer = windowObject.setInterval(() => void syncNow(), 5 * 60 * 1000);
  void syncNow();
  return {
    syncNow,
    stop: () => {
      stopped = true;
      windowObject.removeEventListener('online', onOnline);
      documentObject.removeEventListener('visibilitychange', onVisibilityChange);
      windowObject.clearInterval(timer);
    },
  };
};
