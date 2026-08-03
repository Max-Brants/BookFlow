import type { StatusData } from '../types';

interface AdminDownloadsPageProps {
  status: StatusData;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
  onOpenRequest: (requestId: number) => void;
  onRefresh: () => void;
}

const buckets: Array<[keyof StatusData, string]> = [
  ['queued', 'Queued'],
  ['resolving', 'Resolving'],
  ['locating', 'Locating'],
  ['downloading', 'Downloading'],
  ['complete', 'Completed'],
  ['error', 'Failed'],
  ['cancelled', 'Cancelled'],
];

export const AdminDownloadsPage = ({
  status,
  onCancel,
  onRetry,
  onOpenRequest,
  onRefresh,
}: AdminDownloadsPageProps) => (
  <section className="pb-16">
    <div className="flex items-end justify-between gap-4">
      <div>
        <h1 className="text-3xl font-semibold">Downloads</h1>
        <p className="mt-2 text-sm opacity-65">Live queue and recent download history.</p>
      </div>
      <button
        type="button"
        className="rounded-md border border-(--border-muted) px-3 py-2 text-sm"
        onClick={onRefresh}
      >
        Refresh
      </button>
    </div>
    <div className="mt-6 space-y-6">
      {buckets.map(([key, label]) => {
        const items = Object.entries(status[key] ?? {});
        return (
          <section key={key}>
            <h2 className="font-semibold">
              {label} <span className="text-sm font-normal opacity-55">({items.length})</span>
            </h2>
            <div className="mt-2 space-y-2">
              {items.map(([id, book]) => (
                <article
                  key={id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-(--border-muted) p-3"
                >
                  <div>
                    <p className="font-medium">{book.title || 'Untitled'}</p>
                    <p className="text-xs opacity-60">
                      {book.author || 'Unknown author'}
                      {book.status_message ? ` · ${book.status_message}` : ''}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {!['complete', 'error', 'cancelled'].includes(key) && (
                      <button
                        type="button"
                        className="rounded border border-red-500/40 px-3 py-1.5 text-xs text-red-700"
                        onClick={() => onCancel(id)}
                      >
                        Cancel
                      </button>
                    )}
                    {(key === 'error' || key === 'cancelled') && book.retry_available === true && (
                      <button
                        type="button"
                        className="rounded border border-(--border-muted) px-3 py-1.5 text-xs"
                        onClick={() => onRetry(id)}
                      >
                        Retry
                      </button>
                    )}
                    {(key === 'error' || key === 'cancelled') &&
                      book.retry_available !== true &&
                      typeof book.request_id === 'number' &&
                      book.request_id > 0 && (
                        <button
                          type="button"
                          className="rounded border border-(--border-muted) px-3 py-1.5 text-xs"
                          onClick={() => {
                            if (typeof book.request_id === 'number') onOpenRequest(book.request_id);
                          }}
                        >
                          Open request
                        </button>
                      )}
                  </div>
                </article>
              ))}
              {items.length === 0 && <p className="text-sm opacity-55">Nothing here.</p>}
            </div>
          </section>
        );
      })}
    </div>
  </section>
);
