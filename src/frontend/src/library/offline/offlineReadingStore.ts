/*
 * IndexedDB's DOM declarations return `any` for persisted records. This is the
 * one containment boundary: every value stored here is written by this module.
 */
/* oxlint-disable typescript/no-unsafe-assignment, typescript/no-unsafe-type-assertion, typescript/no-unnecessary-type-assertion, typescript/no-unnecessary-type-parameters */
import type { OfflineBook, PendingProgress } from './types';

export interface OfflineReadingStore {
  getBook(accountId: string, fileId: number): Promise<OfflineBook | null>;
  listBooks(accountId: string): Promise<OfflineBook[]>;
  putBook(book: OfflineBook): Promise<void>;
  deleteBook(accountId: string, fileId: number): Promise<void>;
  getPendingProgress(accountId: string, fileId: number): Promise<PendingProgress | null>;
  listPendingProgress(accountId: string): Promise<PendingProgress[]>;
  putPendingProgress(progress: PendingProgress): Promise<void>;
  deletePendingProgress(accountId: string, fileId: number): Promise<void>;
  clearAccount(accountId: string): Promise<void>;
}

export const OFFLINE_READER_DATABASE_NAME = 'bookflow-offline-reader';
export const OFFLINE_READER_DATABASE_VERSION = 2;
const BOOKS_STORE = 'books';
const PROGRESS_STORE = 'progress';
export const OFFLINE_BOOTSTRAP_STORE = 'bootstrap';

type StoredBook = OfflineBook & { key: string };
type StoredProgress = PendingProgress & { key: string };

const recordKey = (accountId: string, fileId: number): string => `${accountId}:${fileId}`;

export const openOfflineReaderDatabase = (): Promise<IDBDatabase> =>
  new Promise((resolve, reject) => {
    const request = indexedDB.open(OFFLINE_READER_DATABASE_NAME, OFFLINE_READER_DATABASE_VERSION);
    request.addEventListener('error', () =>
      reject(request.error ?? new Error('Unable to open offline storage')),
    );
    request.addEventListener('upgradeneeded', () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(BOOKS_STORE)) {
        const books = database.createObjectStore(BOOKS_STORE, { keyPath: 'key' });
        books.createIndex('accountId', 'accountId', { unique: false });
      }
      if (!database.objectStoreNames.contains(PROGRESS_STORE)) {
        const progress = database.createObjectStore(PROGRESS_STORE, { keyPath: 'key' });
        progress.createIndex('accountId', 'accountId', { unique: false });
      }
      if (!database.objectStoreNames.contains(OFFLINE_BOOTSTRAP_STORE)) {
        database.createObjectStore(OFFLINE_BOOTSTRAP_STORE, { keyPath: 'key' });
      }
    });
    request.addEventListener('success', () => resolve(request.result));
  });

const requestResult = <T>(request: IDBRequest<T>): Promise<T> =>
  new Promise((resolve, reject) => {
    request.addEventListener('success', () => resolve(request.result));
    request.addEventListener('error', () =>
      reject(request.error ?? new Error('Offline storage request failed')),
    );
  });

const transactionComplete = (transaction: IDBTransaction): Promise<void> =>
  new Promise((resolve, reject) => {
    transaction.addEventListener('complete', () => resolve());
    transaction.addEventListener('error', () =>
      reject(transaction.error ?? new Error('Offline storage transaction failed')),
    );
    transaction.addEventListener('abort', () =>
      reject(transaction.error ?? new Error('Offline storage transaction aborted')),
    );
  });

const withoutKey = <T extends { key: string }>(record: T): Omit<T, 'key'> => {
  const { key: _key, ...value } = record;
  return value;
};

/** Browser IndexedDB implementation. It deliberately stores all values under an account id. */
export class IndexedDbOfflineReadingStore implements OfflineReadingStore {
  async getBook(accountId: string, fileId: number): Promise<OfflineBook | null> {
    const database = await openOfflineReaderDatabase();
    try {
      const transaction = database.transaction(BOOKS_STORE, 'readonly');
      const record = await requestResult(
        transaction.objectStore(BOOKS_STORE).get(recordKey(accountId, fileId)),
      );
      await transactionComplete(transaction);
      return record ? (withoutKey(record as StoredBook) as OfflineBook) : null;
    } finally {
      database.close();
    }
  }

  async listBooks(accountId: string): Promise<OfflineBook[]> {
    return this.listByAccount<StoredBook, OfflineBook>(BOOKS_STORE, accountId);
  }

  async putBook(book: OfflineBook): Promise<void> {
    await this.put(BOOKS_STORE, { ...book, key: recordKey(book.accountId, book.fileId) });
  }

  async deleteBook(accountId: string, fileId: number): Promise<void> {
    await this.delete(BOOKS_STORE, recordKey(accountId, fileId));
  }

  async getPendingProgress(accountId: string, fileId: number): Promise<PendingProgress | null> {
    const database = await openOfflineReaderDatabase();
    try {
      const transaction = database.transaction(PROGRESS_STORE, 'readonly');
      const record = await requestResult(
        transaction.objectStore(PROGRESS_STORE).get(recordKey(accountId, fileId)),
      );
      await transactionComplete(transaction);
      return record ? (withoutKey(record as StoredProgress) as PendingProgress) : null;
    } finally {
      database.close();
    }
  }

  async listPendingProgress(accountId: string): Promise<PendingProgress[]> {
    return this.listByAccount<StoredProgress, PendingProgress>(PROGRESS_STORE, accountId);
  }

  async putPendingProgress(progress: PendingProgress): Promise<void> {
    await this.put(PROGRESS_STORE, {
      ...progress,
      key: recordKey(progress.accountId, progress.fileId),
    });
  }

  async deletePendingProgress(accountId: string, fileId: number): Promise<void> {
    await this.delete(PROGRESS_STORE, recordKey(accountId, fileId));
  }

  async clearAccount(accountId: string): Promise<void> {
    const database = await openOfflineReaderDatabase();
    try {
      const transaction = database.transaction([BOOKS_STORE, PROGRESS_STORE], 'readwrite');
      const deletes = [BOOKS_STORE, PROGRESS_STORE].map((storeName) => {
        const index = transaction.objectStore(storeName).index('accountId');
        const range = IDBKeyRange.only(accountId);
        return new Promise<void>((resolve, reject) => {
          const request = index.openCursor(range);
          request.addEventListener('error', () =>
            reject(request.error ?? new Error('Unable to clear offline account')),
          );
          request.addEventListener('success', () => {
            const cursor = request.result;
            if (!cursor) {
              resolve();
              return;
            }
            cursor.delete();
            cursor.continue();
          });
        });
      });
      await Promise.all(deletes);
      await transactionComplete(transaction);
    } finally {
      database.close();
    }
  }

  private async listByAccount<T extends { key: string }, R>(
    storeName: string,
    accountId: string,
  ): Promise<R[]> {
    const database = await openOfflineReaderDatabase();
    try {
      const transaction = database.transaction(storeName, 'readonly');
      const records = await requestResult(
        transaction.objectStore(storeName).index('accountId').getAll(IDBKeyRange.only(accountId)),
      );
      await transactionComplete(transaction);
      return (records as T[]).map((record) => withoutKey(record) as R);
    } finally {
      database.close();
    }
  }

  private async put(storeName: string, record: StoredBook | StoredProgress): Promise<void> {
    const database = await openOfflineReaderDatabase();
    try {
      const transaction = database.transaction(storeName, 'readwrite');
      await requestResult(transaction.objectStore(storeName).put(record));
      await transactionComplete(transaction);
    } finally {
      database.close();
    }
  }

  private async delete(storeName: string, key: string): Promise<void> {
    const database = await openOfflineReaderDatabase();
    try {
      const transaction = database.transaction(storeName, 'readwrite');
      await requestResult(transaction.objectStore(storeName).delete(key));
      await transactionComplete(transaction);
    } finally {
      database.close();
    }
  }
}

/** Small in-memory implementation for deterministic unit tests and SSR adapters. */
export class MemoryOfflineReadingStore implements OfflineReadingStore {
  private readonly books = new Map<string, OfflineBook>();
  private readonly progress = new Map<string, PendingProgress>();

  async getBook(accountId: string, fileId: number): Promise<OfflineBook | null> {
    return this.books.get(recordKey(accountId, fileId)) ?? null;
  }

  async listBooks(accountId: string): Promise<OfflineBook[]> {
    return [...this.books.values()].filter((entry) => entry.accountId === accountId);
  }

  async putBook(book: OfflineBook): Promise<void> {
    this.books.set(recordKey(book.accountId, book.fileId), book);
  }

  async deleteBook(accountId: string, fileId: number): Promise<void> {
    this.books.delete(recordKey(accountId, fileId));
  }

  async getPendingProgress(accountId: string, fileId: number): Promise<PendingProgress | null> {
    return this.progress.get(recordKey(accountId, fileId)) ?? null;
  }

  async listPendingProgress(accountId: string): Promise<PendingProgress[]> {
    return [...this.progress.values()].filter((entry) => entry.accountId === accountId);
  }

  async putPendingProgress(progress: PendingProgress): Promise<void> {
    this.progress.set(recordKey(progress.accountId, progress.fileId), progress);
  }

  async deletePendingProgress(accountId: string, fileId: number): Promise<void> {
    this.progress.delete(recordKey(accountId, fileId));
  }

  async clearAccount(accountId: string): Promise<void> {
    for (const book of await this.listBooks(accountId)) {
      this.books.delete(recordKey(accountId, book.fileId));
    }
    for (const update of await this.listPendingProgress(accountId)) {
      this.progress.delete(recordKey(accountId, update.fileId));
    }
  }
}
