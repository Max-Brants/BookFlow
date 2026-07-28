import type { V1CatalogBookDetail } from '../types/v1';
import { normalizeBookDescription } from '../utils/bookDescription';

type DetailBook = V1CatalogBookDetail['book'];

export type CatalogBookReference =
  | { kind: 'bookId'; value: number }
  | { kind: 'isbn'; value: string };

export const resolveCatalogBookReference = (
  rawBookId: string | undefined,
  rawIsbn: string | undefined,
): CatalogBookReference | null => {
  const isbn = rawIsbn?.trim();
  if (isbn) return { kind: 'isbn', value: isbn };

  const bookId = Number(rawBookId);
  if (Number.isInteger(bookId) && bookId > 0) return { kind: 'bookId', value: bookId };
  return null;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const firstText = (...values: unknown[]): string | null => {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  }
  return null;
};

const firstPositiveInteger = (...values: unknown[]): number | null => {
  for (const value of values) {
    let parsed = Number.NaN;
    if (typeof value === 'number') parsed = value;
    if (typeof value === 'string' && value.trim()) parsed = Number(value);
    if (Number.isInteger(parsed) && parsed > 0) return parsed;
  }
  return null;
};

const textList = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => firstText(isRecord(item) ? item.name : item))
    .filter((item): item is string => Boolean(item));
};

export interface BookDetailPresentation {
  description: string | null;
  publisher: string | null;
  pageCount: number | null;
  isbn: string | null;
  genres: string[];
  formats: string[];
}

export const presentBookDetail = (book: DetailBook): BookDetailPresentation => {
  const metadata = isRecord(book.metadata) ? book.metadata : {};
  const description = firstText(book.description, metadata.description);
  const formats = Array.from(
    new Set((book.formats ?? []).map((format) => format.trim().toUpperCase()).filter(Boolean)),
  );
  const genres = Array.from(
    new Set([...textList(metadata.genres), ...textList(metadata.categories)]),
  );

  return {
    description: description === null ? null : normalizeBookDescription(description),
    publisher: firstText(metadata.publisher, metadata.imprint),
    pageCount: firstPositiveInteger(
      metadata.page_count,
      metadata.pageCount,
      metadata.pages,
      metadata.number_of_pages,
    ),
    isbn: firstText(book.isbn_13, book.isbn, metadata.isbn_13, metadata.isbn_10),
    genres,
    formats,
  };
};

export const requestStatusKind = (
  status: string | null | undefined,
): 'progress' | 'success' | 'danger' | 'neutral' => {
  if (status === 'fulfilled') return 'success';
  if (status === 'rejected' || status === 'cancelled') return 'danger';
  if (status === 'pending_approval' || status === 'approved') return 'progress';
  return 'neutral';
};

export const blocksNewRequest = (status: string | null | undefined): boolean =>
  status === 'pending_approval' || status === 'approved';

export const catalogPrimaryAction = (
  detail: Pick<V1CatalogBookDetail, 'in_library' | 'available_formats'>,
  canAddToLibrary: boolean,
): 'open-library' | 'add-library' | 'request' => {
  if (detail.in_library) return 'open-library';
  if (canAddToLibrary && detail.available_formats.length > 0) return 'add-library';
  return 'request';
};
