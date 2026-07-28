import { describe, expect, it } from 'vitest';

import { submitIssueReport, V1ApiError, v1Api } from '../services/v1Api';

const rotateKoboTokenFetchMock = async (
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> => {
  let requestUrl: string;
  if (typeof input === 'string') {
    requestUrl = input;
  } else if (input instanceof URL) {
    requestUrl = input.href;
  } else {
    requestUrl = input.url;
  }
  expect(requestUrl).toContain('/api/v1/users/me/kobo-token/42/rotate');
  expect(init?.method).toBe('POST');
  expect(new Headers(init?.headers).get('X-BookFlow-CSRF')).toBe('1');
  return new Response(
    JSON.stringify({
      token_id: 43,
      token: 'new-private-token',
      sync_url: '/api/kobo/new-private-token/v1/library/sync',
      shown_once: true,
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
};

describe('v1 API client', () => {
  it('retains the backend correlation id on structured API errors', () => {
    const error = new V1ApiError({
      code: 'forbidden',
      message: 'Administrator access required',
      details: null,
      correlation_id: 'correlation-123',
    });

    expect(error.code).toBe('forbidden');
    expect(error.correlationId).toBe('correlation-123');
    expect(error.message).toBe('Administrator access required');
  });

  it('submits issue reports as multipart data with CSRF and an idempotency key', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input, init) => {
      let requestUrl: string;
      if (input instanceof Request) requestUrl = input.url;
      else if (input instanceof URL) requestUrl = input.href;
      else requestUrl = input;
      expect(requestUrl).toContain('/api/v1/issue-reports');
      expect(init?.method).toBe('POST');
      expect(init?.credentials).toBe('include');
      expect(init?.body).toBeInstanceOf(FormData);
      const headers = new Headers(init?.headers);
      expect(headers.get('X-BookFlow-CSRF')).toBe('1');
      expect(headers.get('Idempotency-Key')).toBe('issue-report-1');
      expect(headers.has('Content-Type')).toBe(false);
      return new Response(JSON.stringify({ issue_number: 123, attachment_status: 'attached' }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const data = new FormData();
      data.set('title', 'Broken search');
      await expect(submitIssueReport(data, 'issue-report-1')).resolves.toMatchObject({
        issue_number: 123,
        attachment_status: 'attached',
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('parses the v1 error envelope returned for an issue report', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({ error: { code: 'issue_report_rate_limited', message: 'Try later' } }),
        { status: 429, headers: { 'Content-Type': 'application/json' } },
      );

    try {
      await expect(submitIssueReport(new FormData(), 'issue-report-2')).rejects.toMatchObject({
        name: 'V1ApiError',
        code: 'issue_report_rate_limited',
        message: 'Try later',
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('rotates a Kobo token through the personal token endpoint', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = rotateKoboTokenFetchMock;

    try {
      await expect(v1Api.rotateKoboToken(42)).resolves.toMatchObject({ token_id: 43 });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('loads the admin maintenance status', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input) => {
      let requestUrl: string;
      if (typeof input === 'string') {
        requestUrl = input;
      } else if (input instanceof URL) {
        requestUrl = input.href;
      } else {
        requestUrl = input.url;
      }
      expect(requestUrl).toContain('/api/v1/admin/maintenance');
      return new Response(
        JSON.stringify({
          database_integrity: 'ok',
          pending_jobs: 2,
          migrations: [],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };

    try {
      await expect(v1Api.maintenance()).resolves.toMatchObject({
        database_integrity: 'ok',
        pending_jobs: 2,
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('loads suggestions and a paginated suggestion list', async () => {
    const originalFetch = globalThis.fetch;
    const requestedUrls: string[] = [];
    globalThis.fetch = async (input) => {
      const requestUrl = input instanceof Request ? input.url : String(input);
      requestedUrls.push(requestUrl);
      return new Response(
        JSON.stringify(
          requestUrl.includes('/suggestions/overall')
            ? { items: [], offset: 30, limit: 15, total: 60, label: 'Bestseller 60' }
            : { snapshot: null, lists: [] },
        ),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };

    try {
      await expect(v1Api.suggestions()).resolves.toMatchObject({ lists: [] });
      await expect(v1Api.suggestionList('overall', 30, 15)).resolves.toMatchObject({ total: 60 });
      expect(requestedUrls).toEqual([
        expect.stringContaining('/api/v1/suggestions'),
        expect.stringContaining('/api/v1/suggestions/overall?offset=30&limit=15'),
      ]);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('loads the current user request shelf with pagination', async () => {
    const originalFetch = globalThis.fetch;
    let requestedUrl = '';
    globalThis.fetch = async (input) => {
      requestedUrl = input instanceof Request ? input.url : String(input);
      return new Response(JSON.stringify({ items: [], offset: 10, limit: 5, total: 12 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      await expect(v1Api.userRequests(10, 5)).resolves.toMatchObject({ total: 12 });
      expect(requestedUrl).toContain('/api/v1/users/me/requests?offset=10&limit=5');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('cancels an administrative request process through the process endpoint', async () => {
    const originalFetch = globalThis.fetch;
    let requestedUrl = '';
    let requestedMethod = '';
    globalThis.fetch = async (input, init) => {
      requestedUrl = input instanceof Request ? input.url : String(input);
      requestedMethod = init?.method ?? 'GET';
      return new Response(
        JSON.stringify({ request_process_id: 70, status: 'cancelled', request_ids: [50] }),
        { status: 202, headers: { 'Content-Type': 'application/json' } },
      );
    };

    try {
      await expect(v1Api.cancelRequestProcess(70)).resolves.toMatchObject({
        status: 'cancelled',
        request_ids: [50],
      });
      expect(requestedUrl).toContain('/api/v1/admin/request-processes/70/cancel');
      expect(requestedMethod).toBe('POST');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('bounds request creation so the UI cannot wait forever', async () => {
    const originalFetch = globalThis.fetch;
    let requestSignal: AbortSignal | null | undefined;
    globalThis.fetch = async (_input, init) => {
      requestSignal = init?.signal;
      return new Response(
        JSON.stringify({
          request: {
            id: 51,
            book_id: 10,
            request_process_id: null,
            status: 'pending_approval',
          },
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } },
      );
    };

    try {
      await v1Api.createRequest({ book_id: 10, profile_id: 1 }, 'request-10');
      expect(requestSignal).toBeInstanceOf(AbortSignal);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('uses catalog entity and patcher manifest endpoints', async () => {
    const originalFetch = globalThis.fetch;
    const requestedUrls: string[] = [];
    globalThis.fetch = async (input) => {
      const requestUrl = input instanceof Request ? input.url : String(input);
      requestedUrls.push(requestUrl);
      const payload = requestUrl.includes('/kobo/patcher/manifest')
        ? { available: true, protocol_version: 1, sha256: 'a'.repeat(64) }
        : { items: [], offset: 30, limit: 30, total: 30 };
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };
    try {
      await expect(
        v1Api.catalogEntities('authors', { q: 'Le Guin', offset: 30 }),
      ).resolves.toMatchObject({ total: 30 });
      await expect(v1Api.patcherManifest()).resolves.toMatchObject({ available: true });
      expect(requestedUrls).toEqual([
        expect.stringContaining('/api/v1/catalog/authors?offset=30&limit=30&q=Le+Guin'),
        expect.stringContaining('/api/v1/kobo/patcher/manifest'),
      ]);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('loads inactive progress and explicitly clears it before a new reading session', async () => {
    const originalFetch = globalThis.fetch;
    const requests: Array<{ url: string; method: string; body: string | null }> = [];
    globalThis.fetch = async (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      requests.push({
        url,
        method: init?.method ?? 'GET',
        body: typeof init?.body === 'string' ? init.body : null,
      });
      return new Response(
        JSON.stringify(
          init?.method === 'DELETE'
            ? { book_id: 9, reset: true }
            : {
                progress: {
                  book_id: 9,
                  progress: 100,
                  active: 0,
                  source: 'web',
                  revision: 4,
                  updated_at: '2026-01-01T00:00:00Z',
                },
              },
        ),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    try {
      await expect(v1Api.readingProgressForBook(9)).resolves.toMatchObject({
        progress: { progress: 100, active: 0 },
      });
      await expect(v1Api.clearReadingProgress(9)).resolves.toEqual({ book_id: 9, reset: true });
      expect(requests).toHaveLength(2);
      expect(requests[0]).toMatchObject({ method: 'GET', body: null });
      expect(requests[0]?.url).toContain('/api/v1/users/me/reading-progress/9');
      expect(requests[1]).toMatchObject({ method: 'DELETE', body: null });
      expect(requests[1]?.url).toContain('/api/v1/users/me/reading-progress/9');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('uses the paged server-side library query contract', async () => {
    const originalFetch = globalThis.fetch;
    let requestedUrl = '';
    globalThis.fetch = async (input) => {
      requestedUrl = input instanceof Request ? input.url : String(input);
      return new Response(JSON.stringify({ items: [], total: 151, offset: 60, limit: 30 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };
    try {
      await expect(
        v1Api.library({
          q: 'Le Guin',
          file_state: 'with-files',
          format: 'kepub',
          sort: 'author',
          offset: 60,
          limit: 30,
        }),
      ).resolves.toMatchObject({ total: 151, offset: 60, limit: 30 });
      expect(requestedUrl).toContain(
        '/api/v1/library/books?offset=60&limit=30&q=Le+Guin&file_state=with-files&format=kepub&sort=author',
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('posts stable book ids to the bulk library endpoint', async () => {
    const originalFetch = globalThis.fetch;
    const requests: Array<{ url: string; method: string; body: string | null }> = [];
    globalThis.fetch = async (input, init) => {
      requests.push({
        url: input instanceof Request ? input.url : String(input),
        method: init?.method ?? 'GET',
        body: typeof init?.body === 'string' ? init.body : null,
      });
      return new Response(
        JSON.stringify({
          results: [{ book_id: 10, canonical_book_id: 10, status: 'added' }],
          summary: { submitted: 1, added: 1, already_in_library: 0, failed: 0 },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    try {
      await expect(v1Api.bulkAddLibraryBooks([10])).resolves.toMatchObject({
        summary: { added: 1 },
      });
      expect(requests).toHaveLength(1);
      expect(requests[0]?.url).toContain('/api/v1/library/books/bulk');
      expect(requests[0]).toMatchObject({
        method: 'POST',
        body: '{"book_ids":[10]}',
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('sends monitor definition fields and can ignore or restore an owned discovery', async () => {
    const originalFetch = globalThis.fetch;
    const requests: Array<{ url: string; method: string; body: string | null }> = [];
    globalThis.fetch = async (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      requests.push({
        url,
        method: init?.method ?? 'GET',
        body: typeof init?.body === 'string' ? init.body : null,
      });
      return new Response(
        JSON.stringify({
          monitor: {},
          discovery: {
            id: 4,
            monitor_id: 3,
            provider: 'hardcover',
            provider_book_id: 'book-4',
            book_id: null,
            state: 'ignored',
            payload_json: '{}',
            discovered_at: '2026-01-01T00:00:00Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    try {
      await v1Api.createMonitor({
        type: 'author',
        query: 'Ursula Le Guin',
        provider: 'openlibrary',
        provider_id: 'OL123A',
        action: 'notify',
        add_to_kobo: false,
        scan_interval_seconds: 21_600,
      });
      await v1Api.updateMonitorDiscovery(3, 4, 'ignored');
      expect(requests).toHaveLength(2);
      expect(requests[0]).toMatchObject({ method: 'POST' });
      expect(requests[0]?.url).toContain('/api/v1/monitors');
      expect(requests[0]?.body).toContain('"provider_id":"OL123A"');
      expect(requests[1]).toMatchObject({ method: 'PATCH', body: '{"state":"ignored"}' });
      expect(requests[1]?.url).toContain('/api/v1/monitors/3/discoveries/4');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('retains metadata review candidates on a preview response', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input) => {
      let requestUrl: string;
      if (input instanceof Request) requestUrl = input.url;
      else if (input instanceof URL) requestUrl = input.href;
      else requestUrl = input;
      expect(requestUrl).toContain('/api/v1/admin/books/7/metadata/preview');
      return new Response(
        JSON.stringify({
          book_id: 7,
          current_values: { title: 'Current', cover_url: 'https://covers.example/current.jpg' },
          provider_values: [
            {
              source: 'hardcover',
              source_identifier: 'hc-7',
              values: { title: 'Candidate', cover_url: 'https://covers.example/candidate.jpg' },
            },
          ],
          changes: [{ field: 'title', before: 'Current', after: 'Candidate' }],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    try {
      const preview = await v1Api.previewMetadata(7, { title: 'Candidate' });
      expect(preview.current_values.title).toBe('Current');
      expect(preview.provider_values[0]).toMatchObject({
        source: 'hardcover',
        values: { title: 'Candidate' },
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('loads and reverts metadata history with an explicit localized reason', async () => {
    const originalFetch = globalThis.fetch;
    const requests: Array<{ url: string; method: string; body: string | null }> = [];
    globalThis.fetch = async (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      requests.push({
        url,
        method: init?.method ?? 'GET',
        body: typeof init?.body === 'string' ? init.body : null,
      });
      return new Response(
        JSON.stringify(init?.method === 'POST' ? { changes: [] } : { items: [] }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      );
    };
    try {
      await expect(v1Api.metadataHistory(12)).resolves.toEqual({ items: [] });
      await v1Api.revertMetadata(12, 7, 'Restore revision 7');
      expect(requests).toHaveLength(2);
      expect(requests[0]).toMatchObject({ method: 'GET', body: null });
      expect(requests[0]?.url).toContain('/api/v1/admin/books/12/metadata/history');
      expect(requests[1]).toMatchObject({
        method: 'POST',
        body: '{"reason":"Restore revision 7"}',
      });
      expect(requests[1]?.url).toContain('/api/v1/admin/books/12/metadata/revert/7');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
