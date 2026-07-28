import { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { BookSelectionControl } from '../components/BookSelectionControl';
import { BulkLibraryActionBar } from '../components/BulkLibraryActionBar';
import { DiscoverNavigation } from '../components/DiscoverNavigation';
import { useLanguage } from '../contexts/LanguageContext';
import { useBulkLibrarySelection } from '../hooks/useBulkLibrarySelection';
import { useDependencyEffect } from '../hooks/useMountEffect';
import type { TranslationKey } from '../i18n/translations';
import { v1Api } from '../services/v1Api';
import type { V1SuggestionBook } from '../types/v1';
import { withBasePath } from '../utils/basePath';
import { catalogBookPath } from '../utils/catalogBookPath';

const PAGE_SIZE = 30;

const LIST_LABELS: Record<string, TranslationKey> = {
  overall: 'suggestions.list.overall',
  fiction: 'suggestions.list.fiction',
  non_fiction: 'suggestions.list.non_fiction',
  thriller: 'suggestions.list.thriller',
  youth: 'suggestions.list.youth',
  cooking: 'suggestions.list.cooking',
};

const Cover = ({ book, alt }: { book: V1SuggestionBook; alt: string }) =>
  book.cover_url ? (
    <img
      className="bookflow-cover aspect-[2/3] w-full rounded-xl object-cover"
      src={withBasePath(book.cover_url)}
      alt={alt}
      loading="lazy"
    />
  ) : (
    <div className="bookflow-cover flex aspect-[2/3] items-center justify-center rounded-xl bg-linear-to-br from-violet-700 via-indigo-700 to-slate-900 text-3xl font-semibold text-white">
      {book.title.slice(0, 1).toUpperCase()}
    </div>
  );

export const SuggestionsPage = () => {
  const { t } = useLanguage();
  const listKey = useParams().listKey ?? '';
  const [books, setBooks] = useState<V1SuggestionBook[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bulk = useBulkLibrarySelection(listKey);

  const load = useCallback(
    async (offset = 0) => {
      if (!listKey) {
        setBooks([]);
        setTotal(0);
        setLoading(false);
        setError(t('suggestions.invalid'));
        return;
      }
      if (offset === 0) setLoading(true);
      else setLoadingMore(true);
      setError(null);
      try {
        const page = await v1Api.suggestionList(listKey, offset, PAGE_SIZE);
        setTotal(page.total ?? page.items.length + offset);
        setBooks((current) => (offset === 0 ? page.items : [...current, ...page.items]));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : t('suggestions.loadFailed'));
      } finally {
        if (offset === 0) setLoading(false);
        else setLoadingMore(false);
      }
    },
    [listKey, t],
  );

  useDependencyEffect(() => {
    void load();
  }, [load]);

  const hasMore = books.length < total;
  const label = t(LIST_LABELS[listKey] ?? 'suggestions.title');
  return (
    <section className="pb-16">
      <div className="mb-7">
        <p className="text-xs font-semibold tracking-widest text-violet-600 uppercase dark:text-violet-300">
          {t('suggestions.eyebrow')}
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">{label}</h1>
      </div>
      <DiscoverNavigation />
      <div className="mb-4 flex justify-end">
        <button
          type="button"
          onClick={() => bulk.setActive(!bulk.active)}
          className={`rounded-md border px-3 py-2 text-sm font-medium ${
            bulk.active ? 'border-violet-500 bg-violet-600 text-white' : 'border-(--border-muted)'
          }`}
        >
          {bulk.active ? t('bulkLibrary.cancelSelection') : t('bulkLibrary.select')}
        </button>
      </div>
      <nav
        className="scrollbar-hide mb-8 flex gap-2 overflow-x-auto pb-2"
        aria-label={t('suggestions.title')}
      >
        {Object.entries(LIST_LABELS).map(([key, translationKey]) => (
          <Link
            key={key}
            to={`/suggestions/${key}`}
            className={`shrink-0 rounded-full border px-3 py-1.5 text-sm transition ${
              key === listKey
                ? 'border-violet-500 bg-violet-600 text-white'
                : 'border-(--border-muted) bg-(--bg-soft) hover:border-violet-500/60'
            }`}
          >
            {t(translationKey)}
          </Link>
        ))}
      </nav>
      {loading && <p className="py-10 text-sm opacity-65">{t('suggestions.loading')}</p>}
      {error && (
        <div className="bookflow-panel rounded-2xl border-red-500/30 p-5 text-sm text-red-600">
          {error}{' '}
          <button type="button" className="underline" onClick={() => void load()}>
            {t('common.retry')}
          </button>
        </div>
      )}
      {!loading && !error && !books.length && (
        <p className="bookflow-panel rounded-2xl p-8 text-center text-sm opacity-65">
          {t('suggestions.empty')}
        </p>
      )}
      {!loading && !error && books.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-x-4 gap-y-8 sm:grid-cols-3 lg:grid-cols-5">
            {books.map((book) => (
              <article key={book.id} className="relative min-w-0">
                <Link
                  to={catalogBookPath(book)}
                  tabIndex={bulk.active ? -1 : undefined}
                  className="block"
                >
                  <Cover book={book} alt={t('common.coverOf', { title: book.title })} />
                  <h2 className="mt-2 truncate font-semibold">{book.title}</h2>
                  <p className="truncate text-sm opacity-65">
                    {book.author || t('common.unknownAuthor')}
                  </p>
                </Link>
                <BookSelectionControl
                  active={bulk.active}
                  inLibrary={book.in_library}
                  selected={bulk.selected.has(book.id)}
                  title={book.title}
                  onToggle={() => bulk.toggle(book.id)}
                />
              </article>
            ))}
          </div>
          {hasMore && (
            <div className="mt-8 flex justify-center">
              <button
                type="button"
                disabled={loadingMore}
                onClick={() => void load(books.length)}
                className="rounded-md border border-(--border-muted) px-4 py-2 text-sm font-medium disabled:opacity-50"
              >
                {loadingMore ? t('suggestions.loadingMore') : t('suggestions.loadMore')}
              </button>
            </div>
          )}
        </>
      )}
      <BulkLibraryActionBar
        visible={bulk.active}
        selectedCount={bulk.selected.size}
        busy={bulk.busy}
        limitReached={bulk.limitReached}
        response={bulk.response}
        error={bulk.error}
        onSelectPage={() => bulk.selectPage(books)}
        onClear={bulk.clear}
        onCancel={() => bulk.setActive(false)}
        onSubmit={() =>
          void bulk.submit((successfulIds) => {
            setBooks((current) =>
              current.map((book) =>
                successfulIds.has(book.id) ? { ...book, in_library: true } : book,
              ),
            );
          })
        }
      />
    </section>
  );
};
