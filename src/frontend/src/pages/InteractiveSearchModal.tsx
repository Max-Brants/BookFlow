import { useCallback, useMemo, useRef, useState } from 'react';

import { useLanguage } from '../contexts/LanguageContext';
import { useDependencyEffect } from '../hooks/useMountEffect';
import { v1Api } from '../services/v1Api';
import type { V1Attempt, V1Candidate, V1RequestProcess, V1RequestSearchRun } from '../types/v1';
import {
  formatBytes,
  sortInteractiveCandidates,
  type InteractiveSearchSort,
} from './interactiveSearchModel';

interface InteractiveSearchModalProps {
  requestProcess: V1RequestProcess;
  title: string;
  onClose: () => void;
  onShowToast: (message: string, type: 'success' | 'error' | 'info') => void;
  onChanged: () => Promise<void>;
}

const terminalStatuses = new Set<V1RequestSearchRun['status']>(['completed', 'partial', 'failed']);
const isRejected = (candidate: V1Candidate): boolean =>
  candidate.accepted !== 1 || candidate.blocked === 1;
const toInteractiveSearchSort = (value: string): InteractiveSearchSort =>
  value === 'title' || value === 'seeders' || value === 'size' ? value : 'score';
const errorMessage = (caught: unknown): string =>
  caught instanceof Error ? caught.message : 'Search failed.';
const runErrors = (run: V1RequestSearchRun | null): string[] => {
  if (!run?.errors_json) return [];
  try {
    const parsed: unknown = JSON.parse(run.errors_json);
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
      return Object.values(parsed).map(String);
    }
    return [String(parsed)];
  } catch {
    return [run.errors_json];
  }
};

export const InteractiveSearchModal = ({
  requestProcess,
  title,
  onClose,
  onShowToast,
  onChanged,
}: InteractiveSearchModalProps) => {
  const { t } = useLanguage();
  const [candidates, setCandidates] = useState<V1Candidate[]>([]);
  const [attempts, setAttempts] = useState<V1Attempt[]>([]);
  const [searchRun, setSearchRun] = useState<V1RequestSearchRun | null>(null);
  const [sort, setSort] = useState<InteractiveSearchSort>('score');
  const [searching, setSearching] = useState(true);
  const [loadingResults, setLoadingResults] = useState(false);
  const [showAttempts, setShowAttempts] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollCount = useRef(0);

  const clearPoll = () => {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };
  useDependencyEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearPoll();
    };
  }, []);

  const refreshRun = useCallback(
    async (runId: number) => {
      setLoadingResults(true);
      try {
        const [candidatePage, attemptPage, runResponse] = await Promise.all([
          v1Api.candidates(requestProcess.id, runId),
          v1Api.attempts(requestProcess.id),
          v1Api.requestSearchRun(requestProcess.id, runId),
        ]);
        if (!mounted.current) return null;
        setCandidates(candidatePage.items);
        setAttempts(attemptPage.items);
        setSearchRun(runResponse.search_run);
        setSearching(!terminalStatuses.has(runResponse.search_run.status));
        setError(null);
        return runResponse.search_run;
      } catch (caught) {
        if (mounted.current) setError(errorMessage(caught));
        return null;
      } finally {
        if (mounted.current) setLoadingResults(false);
      }
    },
    [requestProcess.id],
  );

  const startSearch = useCallback(async () => {
    clearPoll();
    pollCount.current = 0;
    setSearching(true);
    setError(null);
    setCandidates([]);
    setAttempts([]);
    setSearchRun(null);
    try {
      const response = await v1Api.interactiveSearch(requestProcess.id);
      if (!mounted.current) return;
      await refreshRun(response.search_run.id);
    } catch (caught) {
      if (mounted.current) {
        setError(errorMessage(caught));
        setSearching(false);
      }
    }
  }, [refreshRun, requestProcess.id]);
  useDependencyEffect(() => {
    void startSearch();
  }, [startSearch]);
  useDependencyEffect(() => {
    if (!searchRun || terminalStatuses.has(searchRun.status)) return;
    pollCount.current += 1;
    if (pollCount.current > 80) {
      setSearching(false);
      setError('The search is taking longer than expected. Refresh to keep checking this run.');
      return;
    }
    clearPoll();
    pollTimer.current = setTimeout(() => void refreshRun(searchRun.id), 750);
  }, [refreshRun, searchRun]);

  const grab = async (candidate: V1Candidate) => {
    const force = isRejected(candidate);
    let reason: string | undefined;
    if (force) {
      if (
        // oxlint-disable-next-line no-alert -- a forced profile override needs deliberate admin confirmation.
        !window.confirm(
          'This release was rejected by the active profile or blocklist. Force the grab anyway?',
        )
      )
        return;
      // oxlint-disable-next-line no-alert -- the backend persists this reason in the override audit.
      reason = window.prompt('Required audit reason for this override')?.trim();
      if (!reason) return;
    }
    try {
      await v1Api.selectCandidate(candidate.id, force, reason);
      onShowToast(
        force ? 'Release force-grabbed and audit recorded' : 'Release queued for download',
        'success',
      );
      await Promise.all([searchRun ? refreshRun(searchRun.id) : Promise.resolve(), onChanged()]);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  const ordered = useMemo(() => sortInteractiveCandidates(candidates, sort), [candidates, sort]);
  const errors = runErrors(searchRun);
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-3 pt-8 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="interactive-search-heading"
    >
      <section className="w-full max-w-7xl rounded-2xl bg-(--bg) shadow-2xl">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-(--border-muted) p-5">
          <div>
            <p className="text-xs font-semibold tracking-widest text-violet-600 uppercase dark:text-violet-300">
              {t('interactiveSearch.title')}
            </p>
            <h2 id="interactive-search-heading" className="mt-1 text-xl font-semibold">
              {title}
            </h2>
            <p className="mt-1 text-sm opacity-65">{t('interactiveSearch.freshSearch')}</p>
          </div>
          <button
            type="button"
            className="rounded-full p-2 text-xl hover:bg-(--hover-surface)"
            onClick={onClose}
            aria-label={t('interactiveSearch.close')}
          >
            ×
          </button>
        </header>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-(--border-muted) px-5 py-3">
          <p className="text-sm">
            {searching
              ? t('interactiveSearch.searching')
              : t('interactiveSearch.results', { count: candidates.length })}
            {searchRun ? ` · ${searchRun.status} · ${searchRun.candidate_count}` : ''}
          </p>
          <div className="flex gap-2">
            <select
              aria-label={t('interactiveSearch.sort')}
              value={sort}
              onChange={(event) => setSort(toInteractiveSearchSort(event.target.value))}
              className="rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
            >
              <option value="score">{t('interactiveSearch.sortScore')}</option>
              <option value="seeders">{t('interactiveSearch.sortPeers')}</option>
              <option value="size">{t('interactiveSearch.sortSize')}</option>
              <option value="title">{t('interactiveSearch.sortTitle')}</option>
            </select>
            <button
              type="button"
              className="rounded-md border border-(--border-muted) px-3 py-2 text-sm"
              disabled={searching || loadingResults}
              onClick={() => void startSearch()}
            >
              {t('interactiveSearch.searchAgain')}
            </button>
            <button
              type="button"
              className="rounded-md border border-(--border-muted) px-3 py-2 text-sm"
              disabled={loadingResults || !searchRun}
              onClick={() => searchRun && void refreshRun(searchRun.id)}
            >
              {t('interactiveSearch.refresh')}
            </button>
          </div>
        </div>
        {error && (
          <p className="mx-5 mt-4 rounded border border-red-400/35 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-200">
            {error}
          </p>
        )}
        {errors.length > 0 && (
          <p className="mx-5 mt-4 rounded border border-amber-400/35 bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-200">
            {errors.join(' · ')}
          </p>
        )}
        <div className="overflow-x-auto p-5">
          <table className="w-full min-w-[960px] text-left text-sm">
            <thead className="border-b border-(--border-muted) text-xs tracking-wide uppercase opacity-60">
              <tr>
                <th className="px-2 py-3">{t('interactiveSearch.release')}</th>
                <th className="px-2 py-3">{t('interactiveSearch.source')}</th>
                <th className="px-2 py-3">{t('interactiveSearch.protocol')}</th>
                <th className="px-2 py-3">{t('interactiveSearch.size')}</th>
                <th className="px-2 py-3">{t('interactiveSearch.peers')}</th>
                <th className="px-2 py-3">{t('interactiveSearch.languageFormat')}</th>
                <th className="px-2 py-3">{t('interactiveSearch.score')}</th>
                <th className="px-2 py-3">{t('interactiveSearch.decision')}</th>
                <th className="px-2 py-3">{t('interactiveSearch.action')}</th>
              </tr>
            </thead>
            <tbody>
              {ordered.map((candidate) => (
                <tr key={candidate.id} className="border-b border-(--border-muted)/70 align-top">
                  <td className="max-w-sm px-2 py-3 font-medium">
                    {candidate.title ?? `#${candidate.id}`}
                  </td>
                  <td className="px-2 py-3">
                    {candidate.source ?? '—'}
                    {candidate.indexer ? ` / ${candidate.indexer}` : ''}
                  </td>
                  <td className="px-2 py-3">{candidate.protocol ?? '—'}</td>
                  <td className="px-2 py-3">{formatBytes(candidate.size_bytes)}</td>
                  <td className="px-2 py-3">
                    {candidate.seeders ?? 0} / {candidate.peers ?? 0}
                  </td>
                  <td className="px-2 py-3">
                    {candidate.language ?? '—'} / {candidate.file_format?.toUpperCase() ?? '—'}
                  </td>
                  <td className="px-2 py-3 font-semibold">{candidate.total_score}</td>
                  <td
                    className={`max-w-xs px-2 py-3 ${isRejected(candidate) ? 'text-amber-700 dark:text-amber-300' : 'text-emerald-700 dark:text-emerald-300'}`}
                  >
                    {isRejected(candidate)
                      ? candidate.reject_reasons?.join(', ') ||
                        (candidate.blocked === 1 ? 'Blocked' : 'Rejected by profile')
                      : t('interactiveSearch.eligible')}
                  </td>
                  <td className="px-2 py-3">
                    <button
                      type="button"
                      className="rounded bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white"
                      onClick={() => void grab(candidate)}
                    >
                      {isRejected(candidate)
                        ? t('interactiveSearch.grabOverride')
                        : t('interactiveSearch.grab')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!searching && ordered.length === 0 && (
            <p className="py-8 text-center text-sm opacity-65">
              {t('interactiveSearch.noResults')}
            </p>
          )}
        </div>
        <footer className="border-t border-(--border-muted) px-5 py-4">
          <button
            type="button"
            className="text-sm font-medium underline"
            onClick={() => setShowAttempts((current) => !current)}
          >
            {showAttempts
              ? t('interactiveSearch.hideAttempts', { count: attempts.length })
              : t('interactiveSearch.showAttempts', { count: attempts.length })}
          </button>
          {showAttempts && (
            <div className="mt-3 space-y-1 text-sm">
              {attempts.length === 0 ? (
                <p className="opacity-65">{t('interactiveSearch.noAttempts')}</p>
              ) : (
                attempts.map((attempt) => (
                  <p key={attempt.id}>
                    #{attempt.attempt_number} · {attempt.status}
                    {attempt.error_message ? ` · ${attempt.error_message}` : ''}
                  </p>
                ))
              )}
            </div>
          )}
        </footer>
      </section>
    </div>
  );
};
