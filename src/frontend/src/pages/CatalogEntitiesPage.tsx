import { useCallback, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { DiscoverNavigation } from '../components/DiscoverNavigation';
import { useLanguage } from '../contexts/LanguageContext';
import { useDependencyEffect } from '../hooks/useMountEffect';
import { v1Api } from '../services/v1Api';
import type { V1CatalogEntity } from '../types/v1';

export const CatalogEntitiesPage = ({ kind }: { kind: 'authors' | 'series' }) => {
  const { t } = useLanguage();
  const [params, setParams] = useSearchParams();
  const [items, setItems] = useState<V1CatalogEntity[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const q = params.get('q') ?? '';
  const [searchDraft, setSearchDraft] = useState(q);
  const offset = Math.max(0, Number(params.get('offset') ?? 0) || 0);
  const limit = 30;
  const label = kind === 'authors' ? t('following.author') : t('following.series');
  const load = useCallback(async () => {
    try {
      const page = await v1Api.catalogEntities(kind, { q, offset, limit });
      setItems(page.items);
      setTotal(page.total ?? page.items.length);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('common.loadFailed'));
    }
  }, [kind, offset, q, t]);
  useDependencyEffect(() => {
    void load();
  }, [load]);
  useDependencyEffect(() => {
    setSearchDraft(q);
  }, [q]);
  const update = (values: Record<string, string>) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        Object.entries(values).forEach(([key, value]) =>
          value ? next.set(key, value) : next.delete(key),
        );
        return next;
      },
      { replace: true },
    );
  const filterKey = kind === 'authors' ? 'author_id' : 'series_id';
  return (
    <section className="max-w-4xl pb-16">
      <div className="mb-7">
        <p className="text-xs font-semibold tracking-widest text-violet-600 uppercase">
          {t('catalog.eyebrow')}
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">{label}</h1>
      </div>
      <DiscoverNavigation />
      <form
        className="mb-5 flex gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          update({ q: searchDraft, offset: '' });
        }}
      >
        <input
          className="min-w-0 flex-1 rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
          value={searchDraft}
          onChange={(event) => setSearchDraft(event.target.value)}
          placeholder={t('catalog.entitySearch', { kind: label.toLowerCase() })}
          aria-label={t('catalog.entitySearch', { kind: label.toLowerCase() })}
        />
        <button
          type="submit"
          className="rounded-md border border-(--border-muted) px-3 py-2 text-sm"
        >
          {t('catalog.search')}
        </button>
      </form>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="bookflow-panel divide-y rounded-2xl">
        {items.map((item) => (
          <div key={item.id} className="flex items-center gap-3 p-4 hover:bg-(--hover-surface)">
            <Link to={`/catalog?${filterKey}=${item.id}`} className="min-w-0 flex-1">
              <span className="font-medium">{item.name}</span>
              <span className="ml-3 text-sm opacity-60">
                {t('catalog.entityBooks', { count: item.book_count })}
              </span>
            </Link>
            <Link
              to={`/monitors?type=${kind === 'authors' ? 'author' : 'series'}&query=${encodeURIComponent(item.name)}`}
              className="shrink-0 rounded-md border border-(--border-muted) px-3 py-1.5 text-xs font-medium"
            >
              {t('nav.following')}
            </Link>
          </div>
        ))}
        {!error && !items.length && (
          <p className="p-6 text-sm opacity-65">
            {t('catalog.entityEmpty', { kind: label.toLowerCase() })}
          </p>
        )}
      </div>
      <nav className="mt-6 flex justify-between">
        <button
          type="button"
          className="rounded border border-(--border-muted) px-3 py-2 text-sm disabled:opacity-50"
          disabled={!offset}
          onClick={() => update({ offset: String(Math.max(0, offset - limit)) })}
        >
          {t('catalog.previous')}
        </button>
        <button
          type="button"
          className="rounded border border-(--border-muted) px-3 py-2 text-sm disabled:opacity-50"
          disabled={offset + items.length >= total}
          onClick={() => update({ offset: String(offset + limit) })}
        >
          {t('catalog.next')}
        </button>
      </nav>
    </section>
  );
};
