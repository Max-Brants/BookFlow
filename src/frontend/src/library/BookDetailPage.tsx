import { useCallback, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import { useLanguage } from '../contexts/LanguageContext';
import { useDependencyEffect } from '../hooks/useMountEffect';
import {
  downloadLibraryFile,
  getLibraryBook,
  isApiResponseError,
  unlinkLibraryRelease,
} from '../services/api';
import { V1ApiError, v1Api } from '../services/v1Api';
import type { Book } from '../types';
import type { V1BookDetail, V1ReadingProgress } from '../types/v1';
import { withBasePath } from '../utils/basePath';
import { normalizeBookDescription } from '../utils/bookDescription';
import { createIdempotencyKey } from '../utils/idempotencyKey';
import {
  formatFileSize,
  groupFilesByRelease,
  latestFilesByFormat,
  type BookDetailResponse,
  type LibraryFile,
} from './types';

interface BookDetailPageProps {
  autoFindReleases: boolean;
  canFindReleases: boolean;
  isRequestOnly: boolean;
  koboEnabled: boolean;
  onFindReleases: (book: Book) => void;
  onShowToast: (message: string, type: 'success' | 'error' | 'info') => void;
}

interface BookDetailLocationState {
  autoFindReleases?: boolean;
}

const hasAutoFindReleasesIntent = (state: unknown): state is BookDetailLocationState =>
  typeof state === 'object' &&
  state !== null &&
  Object.getOwnPropertyDescriptor(state, 'autoFindReleases')?.value === true;

const toReleaseBook = (book: BookDetailResponse): Book => ({
  id: book.provider_book_id ?? String(book.book_id),
  book_id: book.book_id,
  provider: book.metadata_provider ?? undefined,
  provider_id: book.provider_book_id ?? undefined,
  title: book.title ?? 'Untitled',
  author: book.author ?? '',
  year: book.publish_year?.toString(),
  preview: book.cover_url ?? undefined,
  subtitle: book.subtitle ?? undefined,
  series_name: book.series_name ?? undefined,
  series_position: book.series_position ?? undefined,
});

const dateLabel = (date: string | null): string =>
  date ? new Date(date).toLocaleDateString() : 'date unknown';

export const shouldAutoFindReleases = ({
  canFindReleases,
  autoFindReleases,
  firstAddIntent,
  hasFiles,
  hasInFlight,
  alreadyOpened,
}: {
  canFindReleases: boolean;
  autoFindReleases: boolean;
  firstAddIntent: boolean;
  hasFiles: boolean;
  hasInFlight: boolean;
  alreadyOpened: boolean;
}): boolean =>
  canFindReleases &&
  autoFindReleases &&
  firstAddIntent &&
  !hasFiles &&
  !hasInFlight &&
  !alreadyOpened;

const RequestState = ({
  request,
  onRequest,
  onCancel,
}: {
  request: V1BookDetail['request'];
  onRequest: () => void;
  onCancel: () => void;
}) => {
  const { t } = useLanguage();
  if (!request) {
    return (
      <div className="mt-4 rounded-lg bg-(--bg-soft) px-4 py-4">
        <p className="text-sm text-gray-600 dark:text-gray-300">
          {t('bookDetail.requestMissingFiles')}
        </p>
        <button
          type="button"
          className="mt-3 cursor-pointer rounded-md bg-violet-700 px-3 py-2 text-sm font-medium text-white hover:bg-violet-800"
          onClick={onRequest}
        >
          {t('bookDetail.requestBook')}
        </button>
      </div>
    );
  }

  const labels = {
    pending_approval: t('bookDetail.requestPending'),
    approved: t('bookDetail.requestProcessInProgress'),
    cancelled: t('bookDetail.requestCancelled'),
    fulfilled: t('bookDetail.bookAvailable'),
    rejected: t('bookDetail.requestDeclined'),
  } as const;
  return (
    <div className="mt-4 rounded-lg bg-(--bg-soft) px-4 py-4">
      <p className="text-sm font-medium text-(--text)">{labels[request.status]}</p>
      {(request.status === 'pending_approval' || request.status === 'approved') && (
        <button
          type="button"
          className="hover-action mt-3 cursor-pointer rounded-md px-2 py-1 text-sm font-medium text-rose-700 dark:text-rose-300"
          onClick={onCancel}
        >
          {t('bookDetail.cancelRequest')}
        </button>
      )}
    </div>
  );
};

const AvailableFiles = ({
  book,
  onDownload,
  onFindReleases,
  onUnlinkRelease,
}: {
  book: BookDetailResponse;
  onDownload: (file: LibraryFile) => void;
  onFindReleases: () => void;
  onUnlinkRelease: (file: LibraryFile) => void;
}) => {
  const { t } = useLanguage();
  const releases = groupFilesByRelease(book.files);
  const latestFiles = latestFilesByFormat(book.files);

  return (
    <section className="mt-10">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-(--text)">{t('bookDetail.availableFiles')}</h2>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
            {t('bookDetail.filesHelp')}
          </p>
        </div>
        <button
          type="button"
          className="hover-action cursor-pointer rounded-md px-2 py-1 text-sm font-medium text-emerald-700 dark:text-emerald-300"
          onClick={onFindReleases}
        >
          {t('bookDetail.findRelease')}
        </button>
      </div>
      {latestFiles.length > 0 ? (
        <div className="mt-4">
          <div className="rounded-lg bg-(--bg-soft) px-4 py-2">
            {latestFiles.map((file) => (
              <div
                key={file.history_id}
                className="flex items-center gap-3 border-b border-(--border-muted) py-3 last:border-0"
              >
                <span className="w-16 text-sm font-semibold text-(--text)">
                  {file.format?.toUpperCase() || t('requestProcesses.unknown')}
                </span>
                <span className="text-sm text-gray-600 dark:text-gray-300">
                  {formatFileSize(file.size) || t('bookDetail.sizeUnknown')}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs text-gray-500">
                  {file.indexer_display_name || t('bookDetail.unknownSource')}
                </span>
                {file.downloadable_by_me && (
                  <button
                    type="button"
                    className="hover-action cursor-pointer rounded-md px-2 py-1 text-sm font-medium text-sky-700 dark:text-sky-300"
                    onClick={() => onDownload(file)}
                  >
                    {t('bookDetail.download')}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-4 rounded-lg bg-(--bg-soft) px-4 py-4 text-sm text-gray-600 dark:text-gray-300">
          {book.in_flight.length ? t('bookDetail.releaseDownloading') : t('bookDetail.noFiles')}
        </div>
      )}
      <details className="mt-6">
        <summary className="cursor-pointer text-sm font-medium text-gray-600 dark:text-gray-300">
          {t('bookDetail.advancedReleases')}
          {releases.length ? ` (${releases.length})` : ''}
        </summary>
        {releases.length > 0 && (
          <div className="mt-3 space-y-2 border-l border-(--border-muted) pl-4">
            {releases.map(([taskId, files]) => (
              <div key={taskId} className="rounded-lg bg-(--bg-soft) px-4 py-3">
                <div className="flex items-center gap-3">
                  <p className="min-w-0 flex-1 text-sm font-medium text-(--text)">
                    {files[0].indexer_display_name || t('bookDetail.unknownSource')}
                  </p>
                  {files.some((file) => file.downloadable_by_me) && (
                    <button
                      type="button"
                      className="hover-action cursor-pointer rounded-md px-2 py-1 text-xs font-medium text-rose-700 dark:text-rose-300"
                      onClick={() => onUnlinkRelease(files[0])}
                    >
                      {t('bookDetail.unlinkRelease')}
                    </button>
                  )}
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  {t('bookDetail.releaseFileCount', { count: files.length })} ·{' '}
                  {t('bookDetail.grabbedAt', { date: dateLabel(files[0].downloaded_at) })}
                  {files[0].protocol && ` · ${files[0].protocol}`}
                </p>
                {files.map((file) => (
                  <div key={file.history_id} className="flex items-center gap-3 pt-3 text-sm">
                    <span className="font-medium text-(--text)">
                      {file.format?.toUpperCase() || t('common.unknown')}
                    </span>
                    <span className="text-xs text-gray-500">
                      {formatFileSize(file.size) || t('bookDetail.sizeUnknown')}
                    </span>
                    {file.downloadable_by_me && (
                      <button
                        type="button"
                        className="hover-action ml-auto cursor-pointer rounded-md px-2 py-1 text-sm font-medium text-sky-700 dark:text-sky-300"
                        onClick={() => onDownload(file)}
                      >
                        {t('bookDetail.download')}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </details>
    </section>
  );
};

export const BookDetailPage = ({
  autoFindReleases,
  canFindReleases,
  isRequestOnly,
  koboEnabled,
  onFindReleases,
  onShowToast,
}: BookDetailPageProps) => {
  const { t } = useLanguage();
  const { bookId: rawBookId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const bookId = Number(rawBookId);
  const [book, setBook] = useState<BookDetailResponse | null>(null);
  const [persisted, setPersisted] = useState<V1BookDetail | null>(null);
  const [readingProgress, setReadingProgress] = useState<V1ReadingProgress | null>(null);
  const [readingPercent, setReadingPercent] = useState<number | null>(null);
  const [metadataNote, setMetadataNote] = useState('');
  const [metadataField, setMetadataField] = useState('title');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [autoOpenedFor, setAutoOpenedFor] = useState<number | null>(null);
  const firstAddIntent = hasAutoFindReleasesIntent(location.state);

  const load = useCallback(async () => {
    if (!Number.isInteger(bookId) || bookId < 1) {
      setError('Not in your library');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [detail, persistedDetail, progress] = await Promise.all([
        getLibraryBook(bookId),
        v1Api.book(bookId),
        // The collection endpoint intentionally returns active rows only.  A
        // completed book is inactive, but we still need its 100% state so the
        // user can explicitly reset it before starting again.
        v1Api.readingProgressForBook(bookId).catch((caught: unknown) => {
          if (caught instanceof V1ApiError && caught.code === 'progress_not_found') {
            return null;
          }
          throw caught;
        }),
      ]);
      setBook(detail);
      setPersisted(persistedDetail);
      setReadingProgress(progress?.progress ?? null);
      setReadingPercent(progress?.progress.progress ?? null);
    } catch (caught) {
      if (isApiResponseError(caught) && (caught.status === 403 || caught.status === 404)) {
        setError('Not in your library');
      } else {
        setError(caught instanceof Error ? caught.message : 'Failed to load this book');
      }
    } finally {
      setLoading(false);
    }
  }, [bookId]);

  useDependencyEffect(() => {
    void load();
  }, [load]);

  useDependencyEffect(() => {
    if (
      book &&
      shouldAutoFindReleases({
        canFindReleases,
        autoFindReleases,
        firstAddIntent,
        hasFiles: book.files.length > 0,
        hasInFlight: book.in_flight.length > 0,
        alreadyOpened: autoOpenedFor === book.book_id,
      })
    ) {
      setAutoOpenedFor(book.book_id);
      void navigate(location.pathname, { replace: true, state: null });
      onFindReleases(toReleaseBook(book));
    }
  }, [
    autoFindReleases,
    autoOpenedFor,
    book,
    canFindReleases,
    firstAddIntent,
    location.pathname,
    navigate,
    onFindReleases,
  ]);

  const mutate = async (action: () => Promise<void>, success: string) => {
    try {
      await action();
      onShowToast(success, 'success');
      await load();
    } catch (caught) {
      onShowToast(caught instanceof Error ? caught.message : 'Action failed', 'error');
    }
  };

  if (loading) return <BookDetailSkeleton />;
  if (error) {
    const unavailable = error === 'Not in your library';
    return (
      <section className="mx-auto max-w-5xl px-4 py-10 text-center sm:px-6 lg:px-8">
        <h1 className="text-xl font-semibold text-(--text)">{error}</h1>
        <button
          type="button"
          className="hover-action mt-4 cursor-pointer rounded-md border border-(--border-muted) px-3 py-2 text-sm"
          onClick={() => (unavailable ? void navigate('/library') : void load())}
        >
          {unavailable ? t('bookDetail.backToLibrary') : t('bookDetail.retry')}
        </button>
      </section>
    );
  }
  if (!book) return null;

  const metadata = [
    book.publish_year,
    book.series_name &&
      `${book.series_name}${book.series_position ? ` #${book.series_position}` : ''}`,
    book.language?.toUpperCase(),
    book.isbn_13 && `ISBN ${book.isbn_13}`,
  ].filter(Boolean);

  return (
    <section className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-10">
      <header className="flex gap-5 border-b border-(--border-muted) pb-8">
        {book.cover_url ? (
          <img
            src={withBasePath(book.cover_url)}
            alt={t('common.coverOf', { title: book.title ?? t('bookDetail.unknownTitle') })}
            className="h-52 w-36 rounded-lg object-cover shadow-lg"
          />
        ) : (
          <div className="flex h-52 w-36 items-center justify-center rounded-lg bg-(--bg-soft) text-xs text-gray-500">
            {t('bookDetail.noCover')}
          </div>
        )}
        <div className="min-w-0 self-end">
          <p className="text-xs font-semibold tracking-[0.16em] text-emerald-700 uppercase dark:text-emerald-300">
            {t('bookDetail.inLibrary')}
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-(--text)">{book.title}</h1>
          {book.subtitle && (
            <p className="mt-1 text-lg text-gray-600 dark:text-gray-300">{book.subtitle}</p>
          )}
          <p className="mt-3 text-sm font-medium text-gray-700 dark:text-gray-200">
            {book.author || t('common.unknownAuthor')}
          </p>
          {metadata.length > 0 && (
            <p className="mt-3 text-xs text-gray-500">{metadata.join(' · ')}</p>
          )}
        </div>
      </header>
      {book.metadata_json?.display_fields?.length ? (
        <dl className="mt-6 flex flex-wrap gap-3">
          {book.metadata_json.display_fields.slice(0, 3).map((field) => (
            <div key={field.label} className="rounded-lg bg-(--bg-soft) px-3 py-2">
              <dt className="text-xs text-gray-500">{field.label}</dt>
              <dd className="mt-0.5 text-sm font-semibold text-(--text)">{field.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {persisted && (
        <section className="mt-8 rounded-xl border border-(--border-muted) p-4">
          <h2 className="font-semibold text-(--text)">{t('bookDetail.persistedDelivery')}</h2>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span className="rounded bg-(--bg-soft) px-2 py-1">
              {t('bookDetail.requestStatus', { status: persisted.request?.status ?? 'none' })}
            </span>
            <span className="rounded bg-(--bg-soft) px-2 py-1">
              {t('bookDetail.requestProcessStatus', {
                status: persisted.request?.request_process_status ?? 'none',
              })}
            </span>
            {persisted.request?.next_search_at && (
              <span className="rounded bg-(--bg-soft) px-2 py-1">
                {t('bookDetail.nextSearch', {
                  date: new Date(persisted.request.next_search_at).toLocaleString(),
                })}
              </span>
            )}
            {koboEnabled && (
              <span className="rounded bg-(--bg-soft) px-2 py-1">
                {t('bookDetail.koboStatus', {
                  status: persisted.kobo?.desired_state ?? t('bookDetail.koboNotAdded'),
                })}
              </span>
            )}
          </div>
          {koboEnabled && persisted.files[0] && (
            <button
              type="button"
              className="hover-action mt-4 rounded-md border border-(--border-muted) px-3 py-2 text-sm"
              onClick={() =>
                void mutate(
                  async () => {
                    if (persisted.kobo?.desired_state === 'active') {
                      await v1Api.removeKoboBook(bookId);
                    } else {
                      await v1Api.addKoboBook(
                        bookId,
                        persisted.files[0].id,
                        persisted.files[0].file_format,
                      );
                    }
                  },
                  persisted.kobo?.desired_state === 'active'
                    ? t('bookDetail.removedFromKobo')
                    : t('bookDetail.addedToKobo'),
                )
              }
            >
              {persisted.kobo?.desired_state === 'active'
                ? t('bookDetail.removeFromKobo')
                : t('bookDetail.addToKobo')}
            </button>
          )}
        </section>
      )}
      <section className="mt-6 rounded-xl border border-(--border-muted) p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-semibold text-(--text)">{t('progress.title')}</h2>
            <p className="mt-1 text-sm opacity-65">{t('progress.help')}</p>
          </div>
          {readingPercent !== null && (
            <span className="text-sm font-semibold">{Math.round(readingPercent)}%</span>
          )}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <input
            aria-label={t('progress.label')}
            className="w-28 rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
            type="number"
            min="0"
            max="100"
            value={readingPercent ?? 0}
            onChange={(event) => setReadingPercent(Number(event.target.value))}
          />
          <button
            type="button"
            className="rounded-md bg-violet-700 px-3 py-2 text-sm font-medium text-white"
            onClick={() =>
              void mutate(async () => {
                const next = Math.max(0, Math.min(100, readingPercent ?? 0));
                await v1Api.setReadingProgress(bookId, next);
              }, t('progress.saved'))
            }
          >
            {t('progress.save')}
          </button>
          {readingProgress !== null && (
            <button
              type="button"
              className="rounded-md border border-(--border-muted) px-3 py-2 text-sm"
              onClick={() =>
                void mutate(async () => {
                  await v1Api.clearReadingProgress(bookId);
                }, t('progress.resetSaved'))
              }
            >
              {t('progress.reset')}
            </button>
          )}
        </div>
      </section>
      {isRequestOnly ? (
        <section className="mt-10">
          <h2 className="font-semibold text-(--text)">{t('bookDetail.availability')}</h2>
          {book.files.length > 0 ? (
            <p className="mt-4 rounded-lg bg-(--bg-soft) px-4 py-4 text-sm text-gray-600 dark:text-gray-300">
              {t('bookDetail.filesAvailable')}
            </p>
          ) : (
            <RequestState
              request={persisted?.request ?? null}
              onRequest={() => void navigate(`/catalog/${book.book_id}`)}
              onCancel={() => {
                const requestId = persisted?.request?.id;
                if (requestId) {
                  void mutate(async () => {
                    await v1Api.cancelRequest(requestId, createIdempotencyKey());
                  }, t('bookDetail.requestCancelled'));
                }
              }}
            />
          )}
        </section>
      ) : (
        <AvailableFiles
          book={book}
          onDownload={(file) =>
            void mutate(
              () => downloadLibraryFile(book.book_id, { historyId: file.history_id }),
              t('bookDetail.downloadStarted'),
            )
          }
          onFindReleases={() => onFindReleases(toReleaseBook(book))}
          onUnlinkRelease={(file) =>
            void mutate(
              () => unlinkLibraryRelease(book.book_id, file.history_id),
              t('bookDetail.releaseUnlinked'),
            )
          }
        />
      )}
      <article className="mt-10 max-w-4xl border-t border-(--border-muted) pt-6">
        <h2 className="text-sm font-semibold text-(--text)">{t('bookDetail.about')}</h2>
        <p className="mt-3 leading-7 whitespace-pre-line text-gray-700 dark:text-gray-200">
          {normalizeBookDescription(book.metadata_json?.description || '') ||
            t('bookDetail.noDescription')}
        </p>
      </article>
      <section className="mt-8 max-w-4xl rounded-xl border border-(--border-muted) p-4">
        <h2 className="font-semibold text-(--text)">{t('metadataReport.title')}</h2>
        <p className="mt-1 text-sm opacity-65">{t('metadataReport.help')}</p>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <select
            value={metadataField}
            onChange={(event) => setMetadataField(event.target.value)}
            className="rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
          >
            <option value="title">{t('metadata.field.title')}</option>
            <option value="author">{t('metadata.field.author')}</option>
            <option value="series_name">{t('metadata.field.series')}</option>
            <option value="description">{t('metadata.field.description')}</option>
            <option value="cover_url">{t('metadata.field.cover')}</option>
          </select>
          <input
            value={metadataNote}
            onChange={(event) => setMetadataNote(event.target.value)}
            className="min-w-0 flex-1 rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
            placeholder={t('metadataReport.placeholder')}
          />
          <button
            type="button"
            disabled={!metadataNote.trim()}
            className="rounded-md border border-(--border-muted) px-3 py-2 text-sm font-medium"
            onClick={() => {
              void mutate(async () => {
                await v1Api.createMetadataReport(bookId, metadataField, metadataNote);
              }, t('metadataReport.sent'));
              setMetadataNote('');
            }}
          >
            {t('catalogDetail.report')}
          </button>
        </div>
      </section>
    </section>
  );
};

const BookDetailSkeleton = () => (
  <section className="mx-auto max-w-7xl animate-pulse px-4 py-8 sm:px-6 lg:px-10">
    <div className="h-52 w-36 rounded bg-gray-200 dark:bg-gray-700" />
    <div className="mt-6 h-20 rounded-xl bg-gray-200 dark:bg-gray-700" />
  </section>
);
