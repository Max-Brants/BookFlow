import type { V1CatalogBook } from '../types/v1';

type CatalogBookReference = Pick<V1CatalogBook, 'id' | 'isbn' | 'isbn_13'>;

const normalizedIsbn = (value: string | null | undefined): string | null => {
  const compact = value?.replaceAll(/[\s-]/g, '').toUpperCase();
  return compact && (compact.length === 10 || compact.length === 13) ? compact : null;
};

export const catalogBookPath = (book: CatalogBookReference): string => {
  const isbn = normalizedIsbn(book.isbn_13) ?? normalizedIsbn(book.isbn);
  return isbn ? `/catalog/isbn/${encodeURIComponent(isbn)}` : `/catalog/${book.id}`;
};
