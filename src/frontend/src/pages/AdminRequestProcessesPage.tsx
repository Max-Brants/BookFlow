import { useState } from 'react';

import { useLanguage } from '../contexts/LanguageContext';
import { useDependencyEffect } from '../hooks/useMountEffect';
import { v1Api } from '../services/v1Api';
import type { V1AdminRequest, V1Attempt, V1Candidate, V1RequestProcess } from '../types/v1';

export const AdminRequestProcessesPage = () => {
  const { t } = useLanguage();
  const [requestProcesses, setRequestProcesses] = useState<V1RequestProcess[]>([]);
  const [details, setDetails] = useState<
    Record<number, { candidates: V1Candidate[]; attempts: V1Attempt[] }>
  >({});
  const [error, setError] = useState<string | null>(null);
  const [pendingRequests, setPendingRequests] = useState<V1AdminRequest[]>([]);

  const load = async () => {
    try {
      const [requestProcessPage, requestPage] = await Promise.all([
        v1Api.requestProcesses(),
        v1Api.adminRequests('pending_approval'),
      ]);
      setRequestProcesses(requestProcessPage.items);
      setPendingRequests(requestPage.items);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('requestProcesses.loadFailed'));
    }
  };

  useDependencyEffect(() => {
    void load();
  }, [t]);

  const loadDetails = async (requestProcessId: number) => {
    const [candidates, attempts] = await Promise.all([
      v1Api.candidates(requestProcessId),
      v1Api.attempts(requestProcessId),
    ]);
    setDetails((current) => ({
      ...current,
      [requestProcessId]: { candidates: candidates.items, attempts: attempts.items },
    }));
  };

  return (
    <section className="pb-16">
      <h1 className="text-3xl font-semibold text-(--text)">{t('requestProcesses.title')}</h1>
      <p className="mt-2 text-sm opacity-65">{t('requestProcesses.help')}</p>
      {error && <p className="mt-6 text-sm text-red-600">{error}</p>}
      <section className="mt-6" aria-labelledby="pending-requests-heading">
        <h2 id="pending-requests-heading" className="font-semibold">
          {t('requestProcesses.pendingRequests')}
        </h2>
        <div className="mt-3 space-y-2">
          {pendingRequests.map((request) => (
            <article
              key={request.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-(--border-muted) p-4"
            >
              <div>
                <p className="font-medium">{request.book_title}</p>
                <p className="mt-1 text-xs opacity-65">
                  {t('requestProcesses.requestNumber', { number: request.id })}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="rounded bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-700"
                  onClick={() =>
                    void v1Api
                      .approveRequest(request.id)
                      .then(load)
                      .catch((caught: unknown) =>
                        setError(
                          caught instanceof Error
                            ? caught.message
                            : t('requestProcesses.approvalFailed'),
                        ),
                      )
                  }
                >
                  {t('requestProcesses.approve')}
                </button>
                <button
                  type="button"
                  className="rounded border border-red-500/40 px-3 py-1.5 text-xs text-red-700 dark:text-red-300"
                  onClick={() =>
                    void v1Api
                      .rejectRequest(request.id)
                      .then(load)
                      .catch((caught: unknown) =>
                        setError(
                          caught instanceof Error
                            ? caught.message
                            : t('requestProcesses.rejectionFailed'),
                        ),
                      )
                  }
                >
                  {t('requestProcesses.reject')}
                </button>
              </div>
            </article>
          ))}
          {pendingRequests.length === 0 && (
            <p className="rounded-xl border border-dashed border-(--border-muted) p-4 text-sm opacity-65">
              {t('requestProcesses.noPendingRequests')}
            </p>
          )}
        </div>
      </section>
      <div className="mt-8 space-y-4">
        {requestProcesses.map((requestProcess) => (
          <article
            key={requestProcess.id}
            className="rounded-xl border border-(--border-muted) p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold">
                  {t('requestProcesses.bookNumber', { number: requestProcess.book_id })} ·{' '}
                  {requestProcess.status}
                </h2>
                <p className="mt-1 text-xs opacity-65">
                  {t('requestProcesses.nextSearch', {
                    date: requestProcess.next_search_at ?? t('requestProcesses.notScheduled'),
                  })}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="rounded border border-(--border-muted) px-3 py-1.5 text-xs"
                  onClick={() =>
                    void v1Api
                      .searchNow(requestProcess.id)
                      .then(load)
                      .catch((caught: unknown) => {
                        setError(
                          caught instanceof Error
                            ? caught.message
                            : t('requestProcesses.searchFailed'),
                        );
                      })
                  }
                >
                  {t('requestProcesses.searchNow')}
                </button>
                <button
                  type="button"
                  className="rounded border border-(--border-muted) px-3 py-1.5 text-xs"
                  onClick={() =>
                    void v1Api
                      .setMonitoring(requestProcess.id, requestProcess.monitoring_enabled !== 1)
                      .then(load)
                  }
                >
                  {requestProcess.monitoring_enabled === 1
                    ? t('requestProcesses.unmonitor')
                    : t('requestProcesses.monitor')}
                </button>
                <button
                  type="button"
                  className="rounded border border-(--border-muted) px-3 py-1.5 text-xs"
                  onClick={() => void loadDetails(requestProcess.id)}
                >
                  {t('requestProcesses.details')}
                </button>
              </div>
            </div>
            {details[requestProcess.id] && (
              <div className="mt-4 grid gap-4 text-xs sm:grid-cols-2">
                <div>
                  <h3 className="font-semibold">{t('requestProcesses.candidates')}</h3>
                  {details[requestProcess.id].candidates.map((candidate) => (
                    <p key={candidate.id} className="mt-1">
                      #{candidate.id} · {candidate.file_format ?? t('requestProcesses.unknown')} ·{' '}
                      {t('requestProcesses.score', { score: candidate.total_score })} ·{' '}
                      {candidate.accepted
                        ? t('requestProcesses.accepted')
                        : t('requestProcesses.rejected')}
                    </p>
                  ))}
                </div>
                <div>
                  <h3 className="font-semibold">{t('requestProcesses.attempts')}</h3>
                  {details[requestProcess.id].attempts.map((attempt) => (
                    <p key={attempt.id} className="mt-1">
                      #{attempt.attempt_number} · {attempt.status} ·{' '}
                      {t('requestProcesses.retries', { count: attempt.retry_count })}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </article>
        ))}
        {!error && requestProcesses.length === 0 && (
          <p className="rounded-xl border border-dashed border-(--border-muted) p-8 text-sm opacity-65">
            {t('requestProcesses.none')}
          </p>
        )}
      </div>
    </section>
  );
};
