import { describe, expect, it } from 'vitest';

import {
  dashboardSuggestionLists,
  loadDashboardData,
  requestStatusKind,
  requestStatusTone,
  showOptionalDashboardShelf,
} from '../pages/dashboardData';

describe('loadDashboardData', () => {
  it('keeps active reading progress when the independent recent-catalog call fails', async () => {
    const result = await loadDashboardData({
      recentCatalog: async () => {
        throw new Error('catalog unavailable');
      },
      userRequests: async () => ({ items: [], offset: 0, limit: 10, total: 0 }),
      readingProgress: async () => ({
        items: [
          {
            book_id: 1,
            progress: 25,
            active: 1,
            source: 'web',
            revision: 1,
            updated_at: '2026-07-27T10:00:00Z',
            title: 'Dune',
          },
        ],
        offset: 0,
        limit: 50,
        total: 1,
      }),
      suggestions: async () => ({ snapshot: null, lists: [] }),
    });

    expect(result.reading).toHaveLength(1);
    expect(result.reading[0]).toMatchObject({ book_id: 1, progress: 25, title: 'Dune' });
    expect(result.recent).toEqual([]);
    expect(result.requests).toEqual([]);
    expect(result.suggestions.lists).toEqual([]);
    expect(result.errors).toEqual({ recent: 'catalog unavailable' });
  });

  it('keeps all six bestseller sections available in the loaded suggestions response', async () => {
    const keys = ['overall', 'fiction', 'non_fiction', 'thriller', 'youth', 'cooking'];
    const result = await loadDashboardData({
      recentCatalog: async () => ({ items: [], offset: 0, limit: 12 }),
      userRequests: async () => ({ items: [], offset: 0, limit: 10, total: 0 }),
      readingProgress: async () => ({ items: [], offset: 0, limit: 50 }),
      suggestions: async () => ({
        snapshot: { year: 2026, week: 30, fetched_at: '2026-07-27T10:00:00Z' },
        lists: keys.map((key) => ({ key, label: key, total: 0, items: [] })),
      }),
    });

    expect(result.suggestions.lists.map((list) => list.key)).toEqual(keys);
    expect(result.suggestions.snapshot).toMatchObject({ year: 2026, week: 30 });
  });

  it('keeps the other dashboard rows available when personal requests fail', async () => {
    const result = await loadDashboardData({
      recentCatalog: async () => ({
        items: [{ id: 7, title: 'Dune', author: 'Frank Herbert' }],
        offset: 0,
        limit: 12,
      }),
      userRequests: async () => {
        throw new Error('requests unavailable');
      },
      readingProgress: async () => ({ items: [], offset: 0, limit: 50 }),
      suggestions: async () => ({ snapshot: null, lists: [] }),
    });

    expect(result.recent).toHaveLength(1);
    expect(result.requests).toEqual([]);
    expect(result.errors).toEqual({ requests: 'requests unavailable' });
  });

  it('shows only the overall Bestseller 60 on the dashboard and limits it to ten books', () => {
    const lists = dashboardSuggestionLists({
      snapshot: null,
      lists: [
        {
          key: 'overall',
          label: 'Bestseller 60',
          total: 12,
          items: Array.from({ length: 12 }, (_, index) => ({
            id: index + 1,
            title: `Book ${index + 1}`,
            author: null,
            in_library: false,
            request_status: null,
          })),
        },
        {
          key: 'fiction',
          label: 'Fiction',
          total: 1,
          items: [
            {
              id: 99,
              title: 'Genre book',
              author: null,
              in_library: false,
              request_status: null,
            },
          ],
        },
      ],
    });

    expect(lists.map((list) => list.key)).toEqual(['overall']);
    expect(lists[0]?.items).toHaveLength(10);
    expect(lists[0]?.total).toBe(12);
  });
});

describe('request status presentation', () => {
  it('maps successful, active, failed and unknown request states', () => {
    expect(requestStatusTone('fulfilled', null)).toBe('success');
    expect(requestStatusKind('fulfilled', null)).toBe('available');
    expect(requestStatusTone('pending', 'downloading')).toBe('progress');
    expect(requestStatusKind('pending', 'downloading')).toBe('processing');
    expect(requestStatusKind('pending_approval', null)).toBe('processing');
    expect(requestStatusKind('fulfilled', 'available')).toBe('available');
    expect(requestStatusKind('rejected', null)).toBe('rejected');
    expect(requestStatusKind('cancelled', null)).toBe('cancelled');
    expect(requestStatusKind('pending', 'error')).toBe('failed');
    expect(requestStatusKind('mystery', null)).toBe('unknown');
  });
});

describe('optional dashboard shelves', () => {
  it('hides an empty shelf after loading while preserving loading and error states', () => {
    expect(showOptionalDashboardShelf(false, undefined, 0)).toBe(false);
    expect(showOptionalDashboardShelf(true, undefined, 0)).toBe(true);
    expect(showOptionalDashboardShelf(false, 'Unable to load', 0)).toBe(true);
    expect(showOptionalDashboardShelf(false, undefined, 1)).toBe(true);
  });
});
