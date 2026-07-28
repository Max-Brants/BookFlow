import type { AppConfig, LibraryCapability } from '../../types';
import { OFFLINE_BOOTSTRAP_STORE, openOfflineReaderDatabase } from './offlineReadingStore';

const BOOTSTRAP_KEY = 'last-authenticated';

/**
 * Deliberately small, non-secret snapshot used only to render a cached PWA
 * while /api/auth/check is unreachable. Do not put cookies, tokens or headers
 * in this structure.
 */
export interface OfflinePwaProfile {
  accountId: string;
  username: string | null;
  displayName: string | null;
  isAdmin: boolean;
  libraryCapability: LibraryCapability | null;
}

export interface OfflinePwaBootstrap {
  profile: OfflinePwaProfile;
  /** Public application configuration required to draw the shell. */
  config: AppConfig;
  savedAt: string;
}

type StoredBootstrap = OfflinePwaBootstrap & { key: typeof BOOTSTRAP_KEY };

// The `object` narrowing above intentionally checks the small persisted shape
// before this local record view; IndexedDB values are otherwise `unknown`.
/* oxlint-disable typescript/no-unsafe-type-assertion */
const isStoredBootstrap = (value: unknown): value is StoredBootstrap => {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return (
    record.key === BOOTSTRAP_KEY &&
    typeof record.savedAt === 'string' &&
    record.profile !== null &&
    typeof record.profile === 'object' &&
    typeof (record.profile as Record<string, unknown>).accountId === 'string'
  );
};
/* oxlint-enable typescript/no-unsafe-type-assertion */

const transactionComplete = (transaction: IDBTransaction): Promise<void> =>
  new Promise((resolve, reject) => {
    transaction.addEventListener('complete', () => resolve());
    transaction.addEventListener('error', () =>
      reject(transaction.error ?? new Error('Offline bootstrap transaction failed')),
    );
    transaction.addEventListener('abort', () =>
      reject(transaction.error ?? new Error('Offline bootstrap transaction aborted')),
    );
  });

/** Save a profile only after a successful authenticated online bootstrap. */
export const saveOfflinePwaBootstrap = async (
  bootstrap: Omit<OfflinePwaBootstrap, 'savedAt'>,
  clock: () => string = () => new Date().toISOString(),
): Promise<void> => {
  const database = await openOfflineReaderDatabase();
  try {
    const transaction = database.transaction(OFFLINE_BOOTSTRAP_STORE, 'readwrite');
    transaction.objectStore(OFFLINE_BOOTSTRAP_STORE).put({
      ...bootstrap,
      savedAt: clock(),
      key: BOOTSTRAP_KEY,
    } satisfies StoredBootstrap);
    await transactionComplete(transaction);
  } finally {
    database.close();
  }
};

/** Returns null when no online authenticated session has been cached before. */
export const readOfflinePwaBootstrap = async (): Promise<OfflinePwaBootstrap | null> => {
  const database = await openOfflineReaderDatabase();
  try {
    const transaction = database.transaction(OFFLINE_BOOTSTRAP_STORE, 'readonly');
    const request = transaction.objectStore(OFFLINE_BOOTSTRAP_STORE).get(BOOTSTRAP_KEY);
    const record = await new Promise<unknown>((resolve, reject) => {
      request.addEventListener('success', () => resolve(request.result));
      request.addEventListener('error', () =>
        reject(request.error ?? new Error('Unable to read offline bootstrap')),
      );
    });
    await transactionComplete(transaction);
    if (!isStoredBootstrap(record)) return null;
    const { key: _key, ...bootstrap } = record;
    return bootstrap;
  } finally {
    database.close();
  }
};

/** Called during explicit logout; it never clears a different user's snapshot. */
export const clearOfflinePwaBootstrap = async (accountId: string): Promise<void> => {
  const cached = await readOfflinePwaBootstrap();
  if (!cached || cached.profile.accountId !== accountId) return;
  const database = await openOfflineReaderDatabase();
  try {
    const transaction = database.transaction(OFFLINE_BOOTSTRAP_STORE, 'readwrite');
    transaction.objectStore(OFFLINE_BOOTSTRAP_STORE).delete(BOOTSTRAP_KEY);
    await transactionComplete(transaction);
  } finally {
    database.close();
  }
};
