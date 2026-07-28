import { v1Api } from '../services/v1Api';
import { getApiBase } from '../utils/basePath';
import type { ReaderFile, ReaderProgress } from './types';

const locatorValue = (locator: unknown): string => {
  if (!locator || typeof locator !== 'object' || !('value' in locator)) return '';
  return typeof locator.value === 'string' ? locator.value : '';
};

const readerContentUrl = (bookId: number, fileId: number): string =>
  `${getApiBase()}/v1/library/books/${bookId}/files/${fileId}/content`;

/**
 * The initial reader API deliberately uses BookFlow's existing, book-scoped
 * progress endpoint. A device-local locator preserves the exact location until
 * the server accepts locators in a future API revision.
 */
export const getReaderProgress = async (bookId: number): Promise<ReaderProgress | null> => {
  try {
    const { progress } = await v1Api.readingProgressForBook(bookId);
    return {
      value: locatorValue(progress.locator),
      progression: progress.progression ?? progress.progress / 100,
      completed: progress.completed ?? progress.active === 0,
      updatedAt: progress.reader_updated_at ?? progress.updated_at,
    };
  } catch {
    return null;
  }
};

export const saveReaderProgress = async (
  bookId: number,
  fileId: number,
  progress: ReaderProgress,
): Promise<Awaited<ReturnType<typeof v1Api.setReadingProgress>>> => {
  const clientUpdatedAt = progress.updatedAt ?? new Date().toISOString();
  return v1Api.setReadingProgress(bookId, progress.progression, false, {
    fileId,
    locator: { value: progress.value, progression: progress.progression },
    clientUpdatedAt,
    completed: progress.completed,
  });
};

export const readerFileFromV1 = (input: {
  bookId: number;
  fileId: number;
  title: string;
  author?: string | null;
  format: string;
  etag?: string | null;
}): ReaderFile => ({
  ...input,
  contentUrl: readerContentUrl(input.bookId, input.fileId),
});
