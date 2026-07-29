import { Link } from 'react-router-dom';

import { useLanguage } from '../contexts/LanguageContext';
import { useDependencyEffect } from '../hooks/useMountEffect';
import { useOfflineReading } from '../library/offline/OfflineReadingCoordinator';

export const OfflineHomePage = () => {
  const { t } = useLanguage();
  const { books, status, failedBookCount, refreshBooks } = useOfflineReading();

  useDependencyEffect(() => {
    void refreshBooks();
  }, [refreshBooks]);

  return (
    <main className="min-h-screen bg-(--bg) px-4 py-8 text-(--text) sm:px-6">
      <section className="mx-auto max-w-3xl">
        <div className="mb-8 flex items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold tracking-widest text-violet-600 uppercase dark:text-violet-300">
              {t('offline.eyebrow')}
            </p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight">{t('offline.title')}</h1>
          </div>
          <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-900 dark:bg-amber-400/15 dark:text-amber-200">
            {t('offline.status')}
          </span>
        </div>

        <p className="mb-7 max-w-2xl text-sm opacity-70">{t('offline.intro')}</p>

        {status === 'loading' && <p className="text-sm opacity-70">{t('offline.loading')}</p>}

        {status === 'error' && (
          <div className="mb-6 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
            {failedBookCount > 0
              ? t('offline.partialFailure', { count: failedBookCount })
              : t('offline.cacheFailure')}
          </div>
        )}

        {status !== 'loading' && books.length === 0 && (
          <div className="bookflow-panel rounded-2xl p-8 text-center">
            <h2 className="text-lg font-semibold">{t('offline.emptyTitle')}</h2>
            <p className="mt-2 text-sm opacity-70">{t('offline.emptyHelp')}</p>
          </div>
        )}

        {books.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2">
            {books.map((book) => {
              const progress = Math.round(book.progress.progression * 100);
              return (
                <Link
                  key={book.fileId}
                  to={`/library/${book.bookId}/read/${book.fileId}`}
                  className="bookflow-panel group flex min-w-0 gap-4 rounded-2xl p-4 transition hover:border-violet-500/70 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-500"
                >
                  <div className="flex aspect-[2/3] w-20 shrink-0 items-center justify-center rounded-lg bg-linear-to-br from-violet-700 via-indigo-800 to-slate-950 px-2 text-center text-sm font-bold text-white">
                    {book.title}
                  </div>
                  <div className="min-w-0 flex-1 self-center">
                    <p className="truncate font-semibold">{book.title}</p>
                    <p className="truncate text-sm opacity-65">
                      {book.author || t('common.unknownAuthor')}
                    </p>
                    <div className="mt-3 flex items-center justify-between gap-3 text-xs">
                      <span className="rounded bg-(--hover-surface) px-2 py-1 font-semibold">
                        {book.format.toUpperCase()}
                      </span>
                      <span>{t('offline.progress', { progress })}</span>
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-black/15 dark:bg-white/15">
                      <div
                        className="h-full bg-linear-to-r from-violet-500 to-sky-400"
                        style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }}
                      />
                    </div>
                    <p className="mt-3 text-sm font-semibold text-violet-700 group-hover:underline dark:text-violet-300">
                      {t('offline.open')}
                    </p>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </main>
  );
};
