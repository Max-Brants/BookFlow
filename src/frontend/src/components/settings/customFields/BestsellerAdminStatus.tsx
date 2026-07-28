import { useCallback, useState } from 'react';

import { useLanguage } from '../../../contexts/LanguageContext';
import { useDependencyEffect } from '../../../hooks/useMountEffect';
import { v1Api } from '../../../services/v1Api';
import type { V1BestsellerAdminStatus } from '../../../types/v1';
import type { CustomSettingsFieldRendererProps } from './types';

const formatDate = (value: string | null, language: 'en' | 'nl'): string => {
  if (!value) return language === 'nl' ? 'Nog niet beschikbaar' : 'Not available yet';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(language === 'nl' ? 'nl-NL' : 'en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
};

export const BestsellerAdminStatus = ({ onShowToast }: CustomSettingsFieldRendererProps) => {
  const { language } = useLanguage();
  const [status, setStatus] = useState<V1BestsellerAdminStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [scheduling, setScheduling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await v1Api.bestsellerStatus());
      setError(null);
    } catch (caught) {
      const fallback =
        language === 'nl' ? 'Status kon niet worden geladen.' : 'Status could not be loaded.';
      setError(caught instanceof Error ? caught.message : fallback);
    } finally {
      setLoading(false);
    }
  }, [language]);

  useDependencyEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const handleSync = async () => {
    setScheduling(true);
    try {
      await v1Api.syncBestseller();
      onShowToast?.(
        language === 'nl' ? 'Trending-update is ingepland.' : 'Trending update has been scheduled.',
        'success',
      );
      window.setTimeout(() => void loadStatus(), 1500);
    } catch (caught) {
      const fallback =
        language === 'nl'
          ? 'Trending-update kon niet worden gestart.'
          : 'Trending update could not be started.';
      onShowToast?.(caught instanceof Error ? caught.message : fallback, 'error');
    } finally {
      setScheduling(false);
    }
  };

  const snapshot = status?.active_snapshot ?? status?.last_success;
  const unavailable = language === 'nl' ? 'Nog niet beschikbaar' : 'Not available yet';
  const version = snapshot
    ? `${snapshot.year}-${String(snapshot.week).padStart(2, '0')}`
    : unavailable;
  let actionLabel = language === 'nl' ? 'Nu bijwerken' : 'Update now';
  if (scheduling) {
    actionLabel = language === 'nl' ? 'Update inplannen…' : 'Scheduling update…';
  }

  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.035] p-5 shadow-sm">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold tracking-[0.16em] text-sky-400 uppercase">
            {language === 'nl' ? 'Synchronisatie' : 'Synchronization'}
          </p>
          <h3 className="mt-1 text-lg font-semibold">
            {language === 'nl' ? 'Trending-gegevens' : 'Trending data'}
          </h3>
          <p className="mt-1 max-w-2xl text-sm text-(--text-muted)">
            {language === 'nl'
              ? 'Haal de nieuwste Bestseller 60-lijsten direct op. De update draait veilig op de achtergrond.'
              : 'Fetch the latest Bestseller 60 lists now. The update runs safely in the background.'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void handleSync()}
          disabled={scheduling}
          className="shrink-0 rounded-xl bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-sky-500 disabled:cursor-wait disabled:opacity-60"
        >
          {actionLabel}
        </button>
      </div>

      <dl className="mt-5 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-white/8 bg-black/10 p-3">
          <dt className="text-xs text-(--text-muted)">
            {language === 'nl' ? 'Laatste controle' : 'Last check'}
          </dt>
          <dd className="mt-1 text-sm font-medium">
            {loading ? '…' : formatDate(status?.last_checked_at ?? null, language)}
          </dd>
        </div>
        <div className="rounded-xl border border-white/8 bg-black/10 p-3">
          <dt className="text-xs text-(--text-muted)">
            {language === 'nl' ? 'Laatste succesvolle update' : 'Last successful update'}
          </dt>
          <dd className="mt-1 text-sm font-medium">
            {loading ? '…' : formatDate(snapshot?.completed_at ?? null, language)}
          </dd>
        </div>
        <div className="rounded-xl border border-white/8 bg-black/10 p-3">
          <dt className="text-xs text-(--text-muted)">
            {language === 'nl' ? 'Versie (jaar-week)' : 'Version (year-week)'}
          </dt>
          <dd className="mt-1 text-sm font-semibold text-sky-300">{loading ? '…' : version}</dd>
        </div>
      </dl>

      {status?.last_error && (
        <p className="mt-3 rounded-xl border border-red-500/20 bg-red-500/8 px-3 py-2 text-sm text-red-300">
          {language === 'nl' ? 'Laatste fout: ' : 'Last error: '}
          {status.last_error}
        </p>
      )}
      {error && <p className="mt-3 text-sm text-red-300">{error}</p>}
    </section>
  );
};
