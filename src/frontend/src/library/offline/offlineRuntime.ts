import { v1Api } from '../../services/v1Api';
import type { V1ReadingProgress } from '../../types/v1';
import { OfflineReadingLibrary } from './offlineReadingLibrary';
import { IndexedDbOfflineReadingStore } from './offlineReadingStore';
import type { PendingProgress, ReadingProgress } from './types';

export const offlineReadingStore = new IndexedDbOfflineReadingStore();
export const offlineReadingLibrary = new OfflineReadingLibrary(offlineReadingStore);
const openReaderFileIds = new Set<number>();

export const protectOfflineReaderFile = (fileId: number): (() => void) => {
  openReaderFileIds.add(fileId);
  return () => openReaderFileIds.delete(fileId);
};

export const currentOpenReaderFileIds = (): ReadonlySet<number> => new Set(openReaderFileIds);

export const progressFromV1 = (progress: V1ReadingProgress): ReadingProgress => {
  const locator =
    progress.locator &&
    typeof progress.locator === 'object' &&
    'value' in progress.locator &&
    typeof progress.locator.value === 'string'
      ? progress.locator.value
      : '';
  return {
    locator,
    progression: progress.progression ?? progress.progress / 100,
    completed: progress.completed ?? progress.active === 0,
    lastReadAt: progress.reader_updated_at ?? progress.updated_at,
  };
};

export const sendPendingProgress = async (
  pending: PendingProgress,
): Promise<{ progress: ReadingProgress | null }> => {
  const response = await v1Api.setReadingProgress(pending.bookId, pending.progression, false, {
    fileId: pending.fileId,
    locator: { value: pending.locator, progression: pending.progression },
    clientUpdatedAt: pending.lastReadAt,
    completed: pending.completed,
  });
  return { progress: progressFromV1(response.progress) };
};
