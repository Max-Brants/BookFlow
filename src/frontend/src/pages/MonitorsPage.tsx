import { useCallback, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { useLanguage } from '../contexts/LanguageContext';
import { useDependencyEffect } from '../hooks/useMountEffect';
import { v1Api } from '../services/v1Api';
import type { V1Monitor, V1MonitorDiscovery } from '../types/v1';

const SCAN_INTERVALS = [
  { seconds: 3_600, hours: 1 },
  { seconds: 21_600, hours: 6 },
  { seconds: 86_400, hours: 24 },
  { seconds: 604_800, hours: 168 },
] as const;

const discoveryTitle = (item: V1MonitorDiscovery): string => {
  try {
    const payload: unknown = JSON.parse(item.payload_json);
    if (
      typeof payload === 'object' &&
      payload !== null &&
      'title' in payload &&
      typeof payload.title === 'string'
    ) {
      return payload.title;
    }
  } catch {
    // Legacy rows without a provider payload keep their stable identifier.
  }
  return item.provider_book_id;
};

interface MonitorsPageProps {
  canAutoAcquire?: boolean;
  koboEnabled?: boolean;
}

export const MonitorsPage = ({
  canAutoAcquire = false,
  koboEnabled = false,
}: MonitorsPageProps) => {
  const { t } = useLanguage();
  const [searchParams] = useSearchParams();
  const monitorActionLabel = (value: V1Monitor['action']) => {
    if (value === 'request') return t('following.request');
    if (value === 'auto_acquire') return t('following.acquire');
    return t('following.notify');
  };
  const [items, setItems] = useState<V1Monitor[]>([]);
  const [name, setName] = useState(() => searchParams.get('query') ?? '');
  const [providerId, setProviderId] = useState('');
  const [kind, setKind] = useState<'author' | 'series'>(() =>
    searchParams.get('type') === 'series' ? 'series' : 'author',
  );
  const [action, setAction] = useState<V1Monitor['action']>('notify');
  const [provider, setProvider] = useState<'hardcover' | 'openlibrary'>(() =>
    searchParams.get('type') === 'series' ? 'hardcover' : 'openlibrary',
  );
  const [scanInterval, setScanInterval] = useState(86_400);
  const [addToKobo, setAddToKobo] = useState(false);
  const [discoveries, setDiscoveries] = useState<Record<number, V1MonitorDiscovery[]>>({});
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setItems((await v1Api.monitors()).items);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('common.loadFailed'));
    }
  }, [t]);
  useDependencyEffect(() => {
    void load();
  }, [load]);
  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      await v1Api.createMonitor({
        type: kind,
        // `query` is the adapter-independent search profile.  A future
        // structured `search_profile` response is retained by the client type.
        query: name.trim(),
        provider,
        provider_id: providerId.trim() || null,
        action,
        add_to_kobo: addToKobo,
        scan_interval_seconds: scanInterval,
      });
      setName('');
      setProviderId('');
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('common.loadFailed'));
    }
  };
  const setMonitorKind = (value: string) => {
    if (value === 'author' || value === 'series') {
      setKind(value);
      if (value === 'series') setProvider('hardcover');
    }
  };
  const setMonitorAction = (value: string) => {
    if (value === 'notify' || value === 'request' || value === 'auto_acquire') setAction(value);
  };
  const loadDiscoveries = async (monitorId: number) => {
    try {
      const page = await v1Api.monitorDiscoveries(monitorId);
      setDiscoveries((current) => ({ ...current, [monitorId]: page.items }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('common.loadFailed'));
    }
  };
  const setDiscoveryState = async (
    monitorId: number,
    discoveryId: number,
    state: Extract<V1MonitorDiscovery['state'], 'discovered' | 'ignored'>,
  ) => {
    try {
      const { discovery } = await v1Api.updateMonitorDiscovery(monitorId, discoveryId, state);
      setDiscoveries((current) => ({
        ...current,
        [monitorId]: (current[monitorId] ?? []).map((item) =>
          item.id === discovery.id ? discovery : item,
        ),
      }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('following.discoveryUpdateFailed'));
    }
  };
  const scanLabel = (seconds: number | undefined) => {
    const configured = seconds ?? 86_400;
    const matching = SCAN_INTERVALS.find((interval) => interval.seconds === configured);
    return matching
      ? t('following.scanEveryHours', { hours: matching.hours })
      : t('following.scanEveryMinutes', { minutes: Math.max(1, Math.round(configured / 60)) });
  };

  return (
    <section className="max-w-4xl pb-16">
      <div className="mb-7">
        <p className="text-xs font-semibold tracking-widest text-violet-600 uppercase dark:text-violet-300">
          {t('following.eyebrow')}
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">{t('following.title')}</h1>
        <p className="mt-2 text-sm opacity-65">{t('following.subtitle')}</p>
      </div>
      <form
        className="bookflow-panel grid gap-3 rounded-2xl p-4 sm:grid-cols-2"
        onSubmit={(event) => void create(event)}
      >
        <label className="grid gap-1 text-sm sm:col-span-2">
          <span className="font-medium">{t('following.searchProfile')}</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
            placeholder={t('following.placeholder')}
            aria-label={t('following.searchProfile')}
          />
          <span className="text-xs opacity-60">{t('following.searchProfileHelp')}</span>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">{t('following.type')}</span>
          <select
            value={kind}
            onChange={(event) => setMonitorKind(event.target.value)}
            className="rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
          >
            <option value="author">{t('following.author')}</option>
            <option value="series">{t('following.series')}</option>
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">{t('following.provider')}</span>
          <select
            value={provider}
            onChange={(event) =>
              setProvider(event.target.value === 'hardcover' ? 'hardcover' : 'openlibrary')
            }
            className="rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
          >
            <option value="openlibrary" disabled={kind === 'series'}>
              Open Library
            </option>
            <option value="hardcover">Hardcover</option>
          </select>
        </label>
        <details className="text-sm sm:col-span-2">
          <summary className="cursor-pointer font-medium opacity-70">
            {t('common.advanced')}
          </summary>
          <label className="mt-3 grid gap-1">
            <span className="font-medium">{t('following.providerId')}</span>
            <input
              value={providerId}
              onChange={(event) => setProviderId(event.target.value)}
              className="rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
              placeholder={t('following.providerIdPlaceholder')}
            />
            <span className="text-xs opacity-60">{t('following.providerIdHelp')}</span>
          </label>
        </details>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">{t('following.scanSchedule')}</span>
          <select
            value={scanInterval}
            onChange={(event) => setScanInterval(Number(event.target.value))}
            className="rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
          >
            {SCAN_INTERVALS.map((interval) => (
              <option key={interval.seconds} value={interval.seconds}>
                {t('following.scanEveryHours', { hours: interval.hours })}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">{t('following.action')}</span>
          <select
            value={action}
            onChange={(event) => setMonitorAction(event.target.value)}
            className="rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
          >
            <option value="notify">{t('following.notify')}</option>
            <option value="request">{t('following.request')}</option>
            <option value="auto_acquire" disabled={!canAutoAcquire}>
              {t('following.acquire')}
            </option>
          </select>
          {!canAutoAcquire && (
            <span className="text-xs opacity-60">{t('following.acquireRestricted')}</span>
          )}
        </label>
        {koboEnabled && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={addToKobo}
              onChange={(event) => setAddToKobo(event.target.checked)}
            />
            {t('following.koboIntent')}
          </label>
        )}
        <button
          type="submit"
          className="rounded-md bg-violet-700 px-3 py-2 text-sm font-medium text-white sm:col-span-2"
        >
          {t('following.add')}
        </button>
      </form>
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      <div className="bookflow-panel mt-6 divide-y rounded-2xl">
        {items.length ? (
          items.map((monitor) => (
            <article key={monitor.id} className="p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="font-medium">{monitor.query}</h2>
                  <p className="mt-1 text-xs opacity-65">
                    {monitor.type === 'author' ? t('following.author') : t('following.series')} ·{' '}
                    {monitorActionLabel(monitor.action)} ·{' '}
                    {scanLabel(monitor.scan_interval_seconds)}
                  </p>
                  <p className="mt-1 text-xs opacity-60">
                    {t('following.provider')}: {monitor.provider ?? t('following.unknownProvider')}
                    {monitor.provider_id
                      ? ` · ${t('following.providerId')}: ${monitor.provider_id}`
                      : ''}
                    {' · '}
                    {monitor.next_scan_at
                      ? t('following.nextScan', {
                          date: new Date(monitor.next_scan_at).toLocaleDateString(),
                        })
                      : t('following.scanScheduled')}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="rounded border border-(--border-muted) px-3 py-1.5 text-sm"
                    onClick={() => void loadDiscoveries(monitor.id)}
                  >
                    {t('following.results')}
                  </button>
                  <button
                    type="button"
                    className="rounded border border-(--border-muted) px-3 py-1.5 text-sm"
                    onClick={() =>
                      void v1Api
                        .scanMonitor(monitor.id)
                        .catch((caught: unknown) =>
                          setError(
                            caught instanceof Error ? caught.message : t('common.loadFailed'),
                          ),
                        )
                    }
                  >
                    {t('following.scan')}
                  </button>
                  <button
                    type="button"
                    className="rounded border border-(--border-muted) px-3 py-1.5 text-sm"
                    onClick={() =>
                      void v1Api
                        .updateMonitor(monitor.id, {
                          status: monitor.status === 'paused' ? 'active' : 'paused',
                        })
                        .then(load)
                        .catch((caught: unknown) =>
                          setError(
                            caught instanceof Error ? caught.message : t('common.loadFailed'),
                          ),
                        )
                    }
                  >
                    {monitor.status === 'paused' ? t('following.resume') : t('following.pause')}
                  </button>
                  {koboEnabled && (
                    <button
                      type="button"
                      className="rounded border border-(--border-muted) px-3 py-1.5 text-sm"
                      onClick={() =>
                        void v1Api
                          .updateMonitor(monitor.id, { add_to_kobo: !monitor.add_to_kobo })
                          .then(load)
                          .catch((caught: unknown) =>
                            setError(
                              caught instanceof Error ? caught.message : t('common.loadFailed'),
                            ),
                          )
                      }
                    >
                      {monitor.add_to_kobo ? t('following.koboOn') : t('following.koboOff')}
                    </button>
                  )}
                  <button
                    type="button"
                    className="rounded px-2 py-1.5 text-sm text-rose-700"
                    onClick={() =>
                      void v1Api
                        .deleteMonitor(monitor.id)
                        .then(load)
                        .catch((caught: unknown) =>
                          setError(
                            caught instanceof Error ? caught.message : t('common.loadFailed'),
                          ),
                        )
                    }
                  >
                    {t('common.delete')}
                  </button>
                </div>
              </div>
              {discoveries[monitor.id] && (
                <div className="mt-3 space-y-3 border-t border-(--border-muted) pt-3 text-sm">
                  {(['discovered', 'present', 'future', 'requested', 'ignored'] as const).map(
                    (state) => {
                      const group = discoveries[monitor.id].filter((item) => item.state === state);
                      if (!group.length) return null;
                      return (
                        <section key={state}>
                          <h3 className="text-xs font-semibold tracking-wide uppercase opacity-60">
                            {t(`following.state.${state}`)}
                          </h3>
                          <ul className="mt-1">
                            {group.map((item) => (
                              <li
                                key={item.id}
                                className="flex items-center justify-between gap-3 py-1"
                              >
                                <span className="min-w-0 truncate">{discoveryTitle(item)}</span>
                                <span className="flex shrink-0 items-center gap-2">
                                  <span className="text-xs opacity-60">
                                    {t(`following.state.${item.state}`)}
                                  </span>
                                  <button
                                    type="button"
                                    className="rounded border border-(--border-muted) px-2 py-1 text-xs"
                                    onClick={() =>
                                      void setDiscoveryState(
                                        monitor.id,
                                        item.id,
                                        item.state === 'ignored' ? 'discovered' : 'ignored',
                                      )
                                    }
                                  >
                                    {item.state === 'ignored'
                                      ? t('following.restoreDiscovery')
                                      : t('following.ignoreDiscovery')}
                                  </button>
                                </span>
                              </li>
                            ))}
                          </ul>
                        </section>
                      );
                    },
                  )}
                  {!discoveries[monitor.id].length && (
                    <p className="opacity-60">{t('following.noDiscoveries')}</p>
                  )}
                </div>
              )}
            </article>
          ))
        ) : (
          <p className="p-6 text-sm opacity-65">{t('following.empty')}</p>
        )}
      </div>
    </section>
  );
};
