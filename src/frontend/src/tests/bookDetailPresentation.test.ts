import { describe, expect, it } from 'vitest';

import {
  blocksNewRequest,
  catalogPrimaryAction,
  presentBookDetail,
  requestStatusKind,
  resolveCatalogBookReference,
} from '../pages/bookDetailPresentation';
import type { V1CatalogBookDetail } from '../types/v1';

const detailBook = (
  overrides: Partial<V1CatalogBookDetail['book']> = {},
): V1CatalogBookDetail['book'] => ({
  id: 7,
  title: 'Piranesi',
  author: 'Susanna Clarke',
  ...overrides,
});

describe('presentBookDetail', () => {
  it('builds useful facts from typed fields and provider metadata', () => {
    expect(
      presentBookDetail(
        detailBook({
          isbn_13: '9781526622433',
          formats: ['epub', 'EPUB', 'pdf'],
          metadata: {
            description: 'A labyrinthine novel.',
            publisher: 'Bloomsbury',
            pageCount: 272,
            genres: ['Fantasy', { name: 'Literary fiction' }],
          },
        }),
      ),
    ).toEqual({
      description: 'A labyrinthine novel.',
      publisher: 'Bloomsbury',
      pageCount: 272,
      isbn: '9781526622433',
      genres: ['Fantasy', 'Literary fiction'],
      formats: ['EPUB', 'PDF'],
    });
  });

  it('falls back to metadata ISBN values', () => {
    expect(
      presentBookDetail(
        detailBook({
          metadata: { isbn_10: '1526622424' },
        }),
      ).isbn,
    ).toBe('1526622424');
  });

  it('normalizes provider HTML in descriptions', () => {
    expect(
      presentBookDetail(
        detailBook({
          description: 'Gort &amp; vrienden</br><em>In Frankrijk</em>',
        }),
      ).description,
    ).toBe('Gort & vrienden\nIn Frankrijk');
  });
});

describe('requestStatusKind', () => {
  it('maps request states to stable presentation tones', () => {
    expect(requestStatusKind('approved')).toBe('progress');
    expect(requestStatusKind('fulfilled')).toBe('success');
    expect(requestStatusKind('rejected')).toBe('danger');
    expect(requestStatusKind(undefined)).toBe('neutral');
  });
});

describe('blocksNewRequest', () => {
  it('only blocks while a request is active', () => {
    expect(blocksNewRequest('pending_approval')).toBe(true);
    expect(blocksNewRequest('approved')).toBe(true);
    expect(blocksNewRequest('cancelled')).toBe(false);
    expect(blocksNewRequest('rejected')).toBe(false);
    expect(blocksNewRequest(undefined)).toBe(false);
  });
});

describe('catalogPrimaryAction', () => {
  it('offers library addition for an available book that is not on the personal shelf', () => {
    expect(
      catalogPrimaryAction(
        {
          in_library: false,
          available_formats: ['epub'],
        },
        true,
      ),
    ).toBe('add-library');
  });

  it('opens only books that are actually on the personal shelf', () => {
    expect(
      catalogPrimaryAction(
        {
          in_library: true,
          available_formats: ['epub'],
        },
        true,
      ),
    ).toBe('open-library');
  });
});

describe('resolveCatalogBookReference', () => {
  it('resolves both numeric catalog routes and ISBN routes', () => {
    expect(resolveCatalogBookReference('42', undefined)).toEqual({ kind: 'bookId', value: 42 });
    expect(resolveCatalogBookReference(undefined, '9789026175220')).toEqual({
      kind: 'isbn',
      value: '9789026175220',
    });
  });

  it('rejects routes without a usable book reference', () => {
    expect(resolveCatalogBookReference(undefined, undefined)).toBeNull();
    expect(resolveCatalogBookReference('not-a-number', undefined)).toBeNull();
  });
});
