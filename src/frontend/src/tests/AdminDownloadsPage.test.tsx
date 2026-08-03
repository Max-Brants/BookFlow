// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AdminDownloadsPage } from '../pages/AdminDownloadsPage';

afterEach(cleanup);

describe('AdminDownloadsPage', () => {
  it('shows Retry only when the backend allows it and opens non-retryable requests', () => {
    const onRetry = vi.fn();
    const onOpenRequest = vi.fn();
    render(
      <AdminDownloadsPage
        status={{
          error: {
            retryable: { id: 'retryable', title: 'Retryable', author: '', retry_available: true },
            requested: {
              id: 'requested',
              title: 'Requested',
              author: '',
              request_id: 24,
              retry_available: false,
            },
            blocked: { id: 'blocked', title: 'Blocked', author: '' },
          },
        }}
        onCancel={vi.fn()}
        onRetry={onRetry}
        onOpenRequest={onOpenRequest}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getAllByRole('button', { name: 'Retry' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledWith('retryable');
    fireEvent.click(screen.getByRole('button', { name: 'Open request' }));
    expect(onOpenRequest).toHaveBeenCalledWith(24);
    expect(screen.getByText('Blocked').closest('article')?.querySelector('button')).toBeNull();
  });
});
