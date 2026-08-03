// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LanguageProvider } from '../contexts/LanguageContext';
import { RequestsPage } from '../pages/RequestsPage';
import { v1Api } from '../services/v1Api';
import type { V1AdminRequest } from '../types/v1';

const adminRequest = (
  id: number,
  bookId: number,
  status: V1AdminRequest['status'],
  title: string,
): V1AdminRequest => ({
  id,
  book_id: bookId,
  request_process_id: bookId + 100,
  status,
  content_type: 'ebook',
  add_to_kobo_when_available: 0,
  created_at: '2026-08-02T10:00:00Z',
  updated_at: '2026-08-02T10:00:00Z',
  book_title: title,
  book_author: 'Author',
  requester_name: 'Reader',
});

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('RequestsPage requestId deep link', () => {
  it('switches to History and focuses the linked request group', async () => {
    vi.spyOn(v1Api, 'adminRequests').mockResolvedValue({
      items: [
        adminRequest(1, 10, 'approved', 'Active book'),
        adminRequest(24, 20, 'fulfilled', 'Historic book'),
      ],
      total: 2,
      offset: 0,
      limit: 200,
    });
    vi.spyOn(v1Api, 'requestProcesses').mockResolvedValue({
      items: [
        {
          id: 110,
          book_id: 10,
          status: 'searching',
          monitoring_enabled: 1,
          next_search_at: null,
          active_attempt_id: null,
        },
        {
          id: 120,
          book_id: 20,
          status: 'completed',
          monitoring_enabled: 0,
          next_search_at: null,
          active_attempt_id: null,
        },
      ],
      total: 2,
      offset: 0,
      limit: 200,
    });

    render(
      <MemoryRouter initialEntries={['/requests?requestId=24']}>
        <LanguageProvider>
          <RequestsPage isAdmin onShowToast={vi.fn()} />
        </LanguageProvider>
      </MemoryRouter>,
    );

    const title = await screen.findByText('Historic book');
    expect(screen.queryByText('Active book')).toBeNull();
    const article = title.closest('article');
    expect(article?.className).toContain('ring-violet-500/35');
    await waitFor(() => expect(document.activeElement).toBe(article));
  });

  it('keeps Active selected for an active linked request', async () => {
    vi.spyOn(v1Api, 'adminRequests').mockResolvedValue({
      items: [adminRequest(24, 20, 'approved', 'Active linked book')],
      total: 1,
      offset: 0,
      limit: 200,
    });
    vi.spyOn(v1Api, 'requestProcesses').mockResolvedValue({
      items: [],
      total: 0,
      offset: 0,
      limit: 200,
    });

    render(
      <MemoryRouter initialEntries={['/requests?requestId=24']}>
        <LanguageProvider>
          <RequestsPage isAdmin onShowToast={vi.fn()} />
        </LanguageProvider>
      </MemoryRouter>,
    );

    const title = await screen.findByText('Active linked book');
    await waitFor(() => expect(document.activeElement).toBe(title.closest('article')));
  });
});
