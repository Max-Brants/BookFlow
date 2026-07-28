import { useLanguage } from '../contexts/LanguageContext';
import type { V1BulkLibraryResponse } from '../types/v1';

interface BulkLibraryActionBarProps {
  visible: boolean;
  selectedCount: number;
  busy: boolean;
  limitReached: boolean;
  response: V1BulkLibraryResponse | null;
  error: string | null;
  onSelectPage: () => void;
  onClear: () => void;
  onCancel: () => void;
  onSubmit: () => void;
}

export const BulkLibraryActionBar = ({
  visible,
  selectedCount,
  busy,
  limitReached,
  response,
  error,
  onSelectPage,
  onClear,
  onCancel,
  onSubmit,
}: BulkLibraryActionBarProps) => {
  const { t } = useLanguage();
  if (!visible && !response && !error) return null;

  const resultMessage = response
    ? t('bulkLibrary.result', {
        added: response.summary.added,
        existing: response.summary.already_in_library,
        failed: response.summary.failed,
      })
    : null;
  const unavailableIds =
    response?.results
      .filter((result) => result.status === 'unavailable')
      .map((result) => `#${result.book_id}`)
      .join(', ') ?? '';
  const notFoundIds =
    response?.results
      .filter((result) => result.status === 'not_found')
      .map((result) => `#${result.book_id}`)
      .join(', ') ?? '';
  let submitLabel = t('bulkLibrary.addSelected', { count: selectedCount });
  if (response?.summary.failed) {
    submitLabel = t('bulkLibrary.retrySelected', { count: selectedCount });
  }
  if (busy) {
    submitLabel = t('bulkLibrary.adding');
  }

  if (!visible) {
    return (
      <div
        className="fixed right-3 bottom-3 left-3 z-50 mx-auto flex max-w-2xl items-center gap-3 rounded-2xl border border-violet-500/40 bg-(--bg) p-4 shadow-2xl"
        aria-live="polite"
      >
        <p className={`min-w-0 flex-1 text-sm ${error ? 'text-red-600' : ''}`}>
          {error || resultMessage}
        </p>
        <button
          type="button"
          onClick={onClear}
          className="rounded-md border border-(--border-muted) px-3 py-2 text-sm"
        >
          {t('common.close')}
        </button>
      </div>
    );
  }

  return (
    <div
      className="fixed right-3 bottom-3 left-3 z-50 mx-auto max-w-4xl rounded-2xl border border-violet-500/40 bg-(--bg) p-3 shadow-2xl sm:p-4"
      role="region"
      aria-label={t('bulkLibrary.actions')}
    >
      <div className="flex flex-wrap items-center gap-2">
        <strong className="mr-auto text-sm">
          {t('bulkLibrary.selected', { count: selectedCount })}
        </strong>
        <button
          type="button"
          onClick={onSelectPage}
          disabled={busy}
          className="rounded-md border border-(--border-muted) px-3 py-2 text-sm disabled:opacity-50"
        >
          {t('bulkLibrary.selectPage')}
        </button>
        <button
          type="button"
          onClick={onClear}
          disabled={busy || selectedCount === 0}
          className="rounded-md border border-(--border-muted) px-3 py-2 text-sm disabled:opacity-50"
        >
          {t('bulkLibrary.clear')}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="rounded-md border border-(--border-muted) px-3 py-2 text-sm disabled:opacity-50"
        >
          {t('common.cancel')}
        </button>
        <button
          type="button"
          onClick={onSubmit}
          disabled={busy || selectedCount === 0}
          className="rounded-md bg-violet-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          {submitLabel}
        </button>
      </div>
      <div className="mt-2 text-xs" aria-live="polite">
        {limitReached && <p className="text-amber-600">{t('bulkLibrary.limit')}</p>}
        {resultMessage && <p>{resultMessage}</p>}
        {unavailableIds && (
          <p className="text-amber-700">
            {t('bulkLibrary.unavailableDetails', { ids: unavailableIds })}
          </p>
        )}
        {notFoundIds && (
          <p className="text-red-600">{t('bulkLibrary.notFoundDetails', { ids: notFoundIds })}</p>
        )}
        {error && <p className="text-red-600">{error}</p>}
      </div>
    </div>
  );
};
