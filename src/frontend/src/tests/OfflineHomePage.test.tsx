// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { LanguageProvider } from '../contexts/LanguageContext';
import { OfflineHomePage } from '../pages/OfflineHomePage';

const refreshBooks = vi.fn(async () => undefined);

vi.mock('../library/offline/OfflineReadingCoordinator', () => ({
  useOfflineReading: () => ({
    books: [
      {
        accountId: 'reader',
        bookId: 42,
        fileId: 84,
        title: 'Stored Book',
        author: 'Offline Author',
        format: 'epub',
        coverUrl: null,
        contentUrl: '/api/content',
        content: new Blob(['book']),
        cover: null,
        etag: null,
        contentType: 'application/epub+zip',
        lastAccessedAt: '2026-07-29T12:00:00.000Z',
        progress: {
          locator: 'chapter-3',
          progression: 0.37,
          completed: false,
          lastReadAt: '2026-07-29T12:00:00.000Z',
        },
      },
    ],
    cachedFileIds: new Set([84]),
    status: 'ready',
    failedBookCount: 0,
    refreshBooks,
  }),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('OfflineHomePage', () => {
  it('opens a stored book through its exact reader route', () => {
    render(
      <MemoryRouter>
        <LanguageProvider>
          <OfflineHomePage />
        </LanguageProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Available without a connection' })).toBeTruthy();
    expect(screen.getByRole('link', { name: /Stored Book/ }).getAttribute('href')).toBe(
      '/library/42/read/84',
    );
    expect(screen.getByText('37% read')).toBeTruthy();
  });
});
