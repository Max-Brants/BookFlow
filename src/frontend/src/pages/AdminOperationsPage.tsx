import { useCallback, useState } from 'react';

import { useLanguage } from '../contexts/LanguageContext';
import { useDependencyEffect } from '../hooks/useMountEffect';
import { v1Api } from '../services/v1Api';
import type {
  V1Backup,
  V1MaintenanceStatus,
  V1MetadataPreview,
  V1MetadataReport,
  V1MetadataRevision,
} from '../types/v1';

const size = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(1)} MB`;
const metadataValue = (value: unknown) => {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
};
const draftValue = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
};
const isCoverField = (field: string): boolean => field === 'cover_url';
const parseRevisionValues = (value: string): Record<string, unknown> => {
  try {
    const parsed: unknown = JSON.parse(value);
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
      ? Object.fromEntries(Object.entries(parsed))
      : {};
  } catch {
    return {};
  }
};
const valuesDiffer = (before: unknown, after: unknown): boolean =>
  JSON.stringify(before) !== JSON.stringify(after);

interface AdminOperationsPageProps {
  embedded?: boolean;
}

export const AdminOperationsPage = ({ embedded = false }: AdminOperationsPageProps) => {
  const { t } = useLanguage();
  const metadataFieldLabel = (field: string) => {
    if (field === 'author') return t('metadata.field.author');
    if (field === 'series_name') return t('metadata.field.series');
    if (field === 'description') return t('metadata.field.description');
    if (field === 'cover_url') return t('metadata.field.cover');
    if (field === 'title') return t('metadata.field.title');
    return field;
  };
  const [reports, setReports] = useState<V1MetadataReport[]>([]);
  const [backups, setBackups] = useState<V1Backup[]>([]);
  const [drafts, setDrafts] = useState<Record<number, Record<string, string>>>({});
  const [previews, setPreviews] = useState<Record<number, V1MetadataPreview>>({});
  const [history, setHistory] = useState<Record<number, V1MetadataRevision[]>>({});
  const [historyBookIdInput, setHistoryBookIdInput] = useState('');
  const [historyBookId, setHistoryBookId] = useState<number | null>(null);
  const [pendingRestore, setPendingRestore] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [maintenance, setMaintenance] = useState<V1MaintenanceStatus | null>(null);
  const load = useCallback(async () => {
    try {
      const [reportPage, backupPage, maintenanceStatus] = await Promise.all([
        v1Api.adminMetadataReports(),
        v1Api.backups(),
        v1Api.maintenance(),
      ]);
      setReports(reportPage.items);
      setBackups(backupPage.items);
      setMaintenance(maintenanceStatus);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : t('common.loadFailed'));
    }
  }, [t]);
  useDependencyEffect(() => {
    void load();
  }, [load]);
  const loadHistory = useCallback(
    async (bookId: number) => {
      try {
        const page = await v1Api.metadataHistory(bookId);
        setHistory((current) => ({ ...current, [bookId]: page.items }));
        setHistoryBookId(bookId);
        setHistoryBookIdInput(String(bookId));
      } catch (caught) {
        setMessage(caught instanceof Error ? caught.message : t('admin.historyLoadFailed'));
      }
    },
    [t],
  );
  const revertRevision = async (bookId: number, revisionId: number) => {
    try {
      await v1Api.revertMetadata(
        bookId,
        revisionId,
        t('admin.revertReason', { number: revisionId }),
      );
      await Promise.all([load(), loadHistory(bookId)]);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : t('admin.revertFailed'));
    }
  };
  const activeHistory = historyBookId === null ? undefined : history[historyBookId];

  return (
    <section className={embedded ? 'flex-1 overflow-y-auto p-5 sm:p-6' : 'max-w-5xl pb-16'}>
      {!embedded && (
        <div className="mb-7">
          <p className="text-xs font-semibold tracking-widest text-violet-600 uppercase dark:text-violet-300">
            {t('admin.operationsEyebrow')}
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">
            {t('admin.operationsTitle')}
          </h1>
        </div>
      )}
      {message && <p className="mb-4 text-sm text-red-600">{message}</p>}
      {maintenance && (
        <section className="mb-6 rounded-xl border border-(--border-muted) p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold">{t('requestProcesses.maintenance')}</h2>
              <p className="mt-1 text-xs opacity-65">
                {t('requestProcesses.database', {
                  status:
                    maintenance.database_integrity === 'ok'
                      ? t('requestProcesses.healthy')
                      : t('requestProcesses.needsAttention'),
                })}{' '}
                · {t('requestProcesses.migrations', { count: maintenance.migrations.length })} ·{' '}
                {t('requestProcesses.pendingJobs', { count: maintenance.pending_jobs })}
              </p>
            </div>
            <span
              className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                maintenance.database_integrity === 'ok' &&
                maintenance.migrations.every((migration) => migration.status === 'completed')
                  ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                  : 'bg-red-500/15 text-red-700 dark:text-red-300'
              }`}
            >
              {maintenance.database_integrity === 'ok' &&
              maintenance.migrations.every((migration) => migration.status === 'completed')
                ? t('requestProcesses.ready')
                : t('requestProcesses.attention')}
            </span>
          </div>
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer font-medium">
              {t('requestProcesses.migrationHistory')}
            </summary>
            <ol className="mt-2 space-y-1">
              {maintenance.migrations.map((migration) => (
                <li key={migration.version}>
                  v{migration.version} · {migration.name} · {migration.status}
                  {migration.error_message ? ` · ${migration.error_message}` : ''}
                </li>
              ))}
            </ol>
          </details>
        </section>
      )}

      <section className="rounded-xl border border-(--border-muted) p-5">
        <div>
          <h2 className="font-semibold">{t('admin.historyLookupTitle')}</h2>
          <p className="mt-1 text-sm opacity-65">{t('admin.historyLookupHelp')}</p>
        </div>
        <form
          className="mt-4 flex flex-wrap gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            const nextBookId = Number(historyBookIdInput);
            if (!Number.isInteger(nextBookId) || nextBookId < 1) {
              setMessage(t('admin.historyInvalidBookId'));
              return;
            }
            void loadHistory(nextBookId);
          }}
        >
          <label className="sr-only" htmlFor="metadata-history-book-id">
            {t('admin.historyBookId')}
          </label>
          <input
            id="metadata-history-book-id"
            type="number"
            min="1"
            value={historyBookIdInput}
            onChange={(event) => setHistoryBookIdInput(event.target.value)}
            placeholder={t('admin.historyBookId')}
            className="w-40 rounded border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
          />
          <button
            type="submit"
            className="rounded border border-(--border-muted) px-3 py-2 text-sm"
          >
            {t('admin.loadHistory')}
          </button>
        </form>
        {historyBookId !== null && activeHistory && (
          <div className="mt-5 divide-y divide-(--border-muted) border-t border-(--border-muted)">
            {activeHistory.length ? (
              activeHistory.map((revision) => {
                const before = parseRevisionValues(revision.before_json);
                const after = parseRevisionValues(revision.after_json);
                const fields = Array.from(
                  new Set([...Object.keys(before), ...Object.keys(after)]),
                ).filter((field) => valuesDiffer(before[field], after[field]));
                return (
                  <article key={revision.id} className="py-4">
                    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                      <div className="text-sm">
                        <p className="font-medium">
                          {t('admin.revision', { number: revision.id })}
                        </p>
                        <dl className="mt-2 grid gap-x-5 gap-y-1 text-xs opacity-70 sm:grid-cols-2">
                          <div>
                            <dt className="inline font-medium">{t('admin.actor')}: </dt>
                            <dd className="inline">
                              {revision.actor_user_id === null
                                ? t('admin.systemActor')
                                : revision.actor_user_id}
                            </dd>
                          </div>
                          <div>
                            <dt className="inline font-medium">{t('admin.source')}: </dt>
                            <dd className="inline">{revision.source}</dd>
                          </div>
                          <div>
                            <dt className="inline font-medium">{t('admin.appliedAt')}: </dt>
                            <dd className="inline">
                              {new Date(revision.created_at).toLocaleString()}
                            </dd>
                          </div>
                          <div>
                            <dt className="inline font-medium">{t('admin.reason')}: </dt>
                            <dd className="inline">
                              {revision.reason || t('admin.noExplanation')}
                            </dd>
                          </div>
                        </dl>
                      </div>
                      <button
                        type="button"
                        className="self-start rounded border border-amber-500/40 px-3 py-1.5 text-sm text-amber-800 dark:text-amber-300"
                        onClick={() => void revertRevision(historyBookId, revision.id)}
                      >
                        {t('admin.revert')}
                      </button>
                    </div>
                    {fields.length ? (
                      <div className="mt-3 overflow-x-auto rounded border border-(--border-muted)">
                        <table className="w-full text-left text-xs">
                          <thead className="bg-(--bg-soft) opacity-70">
                            <tr>
                              <th className="px-3 py-2 font-medium">{t('metadata.field.title')}</th>
                              <th className="px-3 py-2 font-medium">{t('admin.before')}</th>
                              <th className="px-3 py-2 font-medium">{t('admin.after')}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {fields.map((field) => (
                              <tr key={field} className="border-t border-(--border-muted)">
                                <th className="px-3 py-2 align-top font-medium">
                                  {metadataFieldLabel(field)}
                                </th>
                                <td className="max-w-xs px-3 py-2 align-top break-all opacity-70">
                                  {metadataValue(before[field])}
                                </td>
                                <td className="max-w-xs px-3 py-2 align-top break-all">
                                  {metadataValue(after[field])}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="mt-3 text-xs opacity-60">{t('admin.noFieldChanges')}</p>
                    )}
                  </article>
                );
              })
            ) : (
              <p className="py-4 text-sm opacity-65">{t('admin.historyEmpty')}</p>
            )}
          </div>
        )}
      </section>

      <section className="mt-6 rounded-xl border border-(--border-muted) p-5">
        <div className="flex items-baseline justify-between gap-3">
          <div>
            <h2 className="font-semibold">{t('admin.reportsTitle')}</h2>
            <p className="mt-1 text-sm opacity-65">{t('admin.reportsHelp')}</p>
          </div>
          <span className="text-sm opacity-65">
            {t('admin.openReports', { count: reports.length })}
          </span>
        </div>
        <div className="mt-4 divide-y divide-(--border-muted)">
          {reports.length ? (
            reports.map((report) => (
              <article key={report.id} className="py-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:justify-between">
                  <div>
                    <p className="text-sm font-medium">
                      {t('admin.bookNumber', { number: report.book_id })} ·{' '}
                      {report.fields.map(metadataFieldLabel).join(', ')}
                    </p>
                    <p className="mt-1 text-sm opacity-65">
                      {report.explanation || t('admin.noExplanation')}
                    </p>
                    <p className="mt-1 text-xs opacity-50">
                      {new Date(report.created_at).toLocaleString()}
                    </p>
                  </div>
                  <span className="text-sm opacity-65">{report.status}</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <div className="grid w-full gap-2 sm:grid-cols-2">
                    {report.fields.map((field) => (
                      <div
                        key={field}
                        className="rounded-lg border border-(--border-muted) p-3 text-xs"
                      >
                        <span className="mb-1 block font-medium opacity-65">
                          {metadataFieldLabel(field)}
                        </span>
                        <div className="mb-2 grid gap-2 sm:grid-cols-2">
                          <button
                            type="button"
                            className="rounded border border-(--border-muted) p-2 text-left hover:bg-(--hover-surface)"
                            onClick={() =>
                              setDrafts((current) => ({
                                ...current,
                                [report.id]: {
                                  ...current[report.id],
                                  [field]: draftValue(report.current_values[field]),
                                },
                              }))
                            }
                          >
                            <span className="block font-medium">{t('admin.current')}</span>
                            <span className="block break-all opacity-65">
                              {metadataValue(report.current_values[field])}
                            </span>
                            {isCoverField(field) &&
                              typeof report.current_values[field] === 'string' && (
                                <img
                                  className="mt-2 h-20 w-14 rounded object-cover"
                                  src={report.current_values[field]}
                                  alt={t('admin.currentCover')}
                                />
                              )}
                          </button>
                          {report.provider_values.map((candidate, index) =>
                            candidate.values[field] === undefined ? null : (
                              <button
                                key={`${candidate.source}-${candidate.source_identifier ?? index}`}
                                type="button"
                                className="rounded border border-violet-500/30 p-2 text-left hover:bg-violet-500/10"
                                onClick={() =>
                                  setDrafts((current) => ({
                                    ...current,
                                    [report.id]: {
                                      ...current[report.id],
                                      [field]: draftValue(candidate.values[field]),
                                    },
                                  }))
                                }
                              >
                                <span className="block font-medium">
                                  {candidate.source}
                                  {candidate.source_identifier
                                    ? ` · ${candidate.source_identifier}`
                                    : ''}
                                </span>
                                <span className="block break-all opacity-65">
                                  {metadataValue(candidate.values[field])}
                                </span>
                                {isCoverField(field) &&
                                  typeof candidate.values[field] === 'string' && (
                                    <img
                                      className="mt-2 h-20 w-14 rounded object-cover"
                                      src={candidate.values[field]}
                                      alt={t('admin.providerCover', { source: candidate.source })}
                                    />
                                  )}
                              </button>
                            ),
                          )}
                        </div>
                        <input
                          value={drafts[report.id]?.[field] ?? ''}
                          onChange={(event) =>
                            setDrafts((current) => ({
                              ...current,
                              [report.id]: { ...current[report.id], [field]: event.target.value },
                            }))
                          }
                          placeholder={t('admin.newValue', { field: metadataFieldLabel(field) })}
                          className="w-full rounded border border-(--border-muted) bg-transparent px-3 py-1.5 text-sm"
                        />
                        <span className="mt-1 block opacity-60">{t('admin.manualValue')}</span>
                      </div>
                    ))}
                  </div>
                  <button
                    type="button"
                    className="rounded border border-(--border-muted) px-3 py-1.5 text-sm"
                    onClick={() => {
                      const changes = Object.fromEntries(
                        Object.entries(drafts[report.id] ?? {}).filter(([, value]) => value.trim()),
                      );
                      if (!Object.keys(changes).length) return;
                      void v1Api
                        .previewMetadata(report.book_id, changes)
                        .then((result) =>
                          setPreviews((current) => ({ ...current, [report.id]: result })),
                        )
                        .catch((caught: unknown) =>
                          setMessage(
                            caught instanceof Error ? caught.message : t('admin.previewFailed'),
                          ),
                        );
                    }}
                  >
                    {t('admin.preview')}
                  </button>
                  <button
                    type="button"
                    disabled={!previews[report.id]?.changes.length}
                    className="rounded bg-violet-700 px-3 py-1.5 text-sm text-white disabled:opacity-50"
                    onClick={() => {
                      const changes = Object.fromEntries(
                        Object.entries(drafts[report.id] ?? {}).filter(([, value]) => value.trim()),
                      );
                      if (!Object.keys(changes).length) return;
                      void v1Api
                        .applyMetadata(report.book_id, changes, report.explanation, report.id)
                        .then(load)
                        .catch((caught: unknown) =>
                          setMessage(
                            caught instanceof Error ? caught.message : t('admin.applyFailed'),
                          ),
                        );
                    }}
                  >
                    {t('admin.apply')}
                  </button>
                  <button
                    type="button"
                    className="rounded px-3 py-1.5 text-sm text-rose-700"
                    onClick={() =>
                      void v1Api
                        .rejectMetadataReport(report.id, t('admin.reject'))
                        .then(load)
                        .catch((caught: unknown) =>
                          setMessage(
                            caught instanceof Error ? caught.message : t('common.loadFailed'),
                          ),
                        )
                    }
                  >
                    {t('admin.reject')}
                  </button>
                  <button
                    type="button"
                    className="rounded px-3 py-1.5 text-sm"
                    onClick={() => void loadHistory(report.book_id)}
                  >
                    {t('admin.history')}
                  </button>
                </div>
                {previews[report.id]?.changes.map((change) => (
                  <p key={change.field} className="mt-2 rounded bg-(--bg-soft) px-3 py-2 text-xs">
                    {change.field}: {metadataValue(change.before)} → {metadataValue(change.after)}
                  </p>
                ))}
              </article>
            ))
          ) : (
            <p className="py-4 text-sm opacity-65">{t('admin.noReports')}</p>
          )}
        </div>
      </section>

      <section className="mt-6 rounded-xl border border-(--border-muted) p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold">{t('admin.backupsTitle')}</h2>
            <p className="mt-1 text-sm opacity-65">{t('admin.backupHelp')}</p>
          </div>
          <button
            className="rounded-md bg-violet-700 px-3 py-2 text-sm font-medium text-white"
            type="button"
            onClick={() =>
              void v1Api
                .createBackup()
                .then(load)
                .catch((caught: unknown) =>
                  setMessage(caught instanceof Error ? caught.message : t('admin.backupFailed')),
                )
            }
          >
            {t('admin.createBackup')}
          </button>
        </div>
        <div className="mt-4 divide-y divide-(--border-muted)">
          {backups.length ? (
            backups.map((backup) => (
              <article
                key={backup.id}
                className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="text-sm">
                  <p className="font-medium">{new Date(backup.created_at).toLocaleString()}</p>
                  <p className="mt-1 text-xs opacity-60">
                    {size(backup.size_bytes)} ·{' '}
                    {backup.encrypted ? t('admin.encrypted') : t('admin.unencrypted')} ·{' '}
                    {backup.verified_at ? t('admin.verified') : t('admin.unverified')}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <a
                    href={v1Api.backupDownloadUrl(backup.id)}
                    className="rounded border border-(--border-muted) px-3 py-1.5 text-sm"
                  >
                    {t('admin.download')}
                  </a>
                  <button
                    type="button"
                    className="rounded border border-amber-500/40 px-3 py-1.5 text-sm text-amber-700"
                    onClick={() => {
                      if (pendingRestore !== backup.id) {
                        setPendingRestore(backup.id);
                        return;
                      }
                      void v1Api
                        .stageRestore(backup.id)
                        .then(() => {
                          setPendingRestore(null);
                          setMessage(t('admin.restoreStaged'));
                        })
                        .catch((caught: unknown) =>
                          setMessage(
                            caught instanceof Error ? caught.message : t('admin.restoreFailed'),
                          ),
                        );
                    }}
                  >
                    {pendingRestore === backup.id ? t('admin.confirmRestore') : t('admin.restore')}
                  </button>
                  <button
                    type="button"
                    className="rounded border border-(--border-muted) px-3 py-1.5 text-sm"
                    onClick={() =>
                      void v1Api
                        .verifyBackup(backup.id)
                        .then(load)
                        .catch((caught: unknown) =>
                          setMessage(
                            caught instanceof Error ? caught.message : t('admin.backupFailed'),
                          ),
                        )
                    }
                  >
                    {t('admin.verify')}
                  </button>
                  <button
                    type="button"
                    className="rounded px-3 py-1.5 text-sm text-rose-700"
                    onClick={() =>
                      void v1Api
                        .deleteBackup(backup.id)
                        .then(load)
                        .catch((caught: unknown) =>
                          setMessage(
                            caught instanceof Error ? caught.message : t('admin.backupFailed'),
                          ),
                        )
                    }
                  >
                    {t('common.delete')}
                  </button>
                </div>
              </article>
            ))
          ) : (
            <p className="py-4 text-sm opacity-65">{t('admin.noBackups')}</p>
          )}
        </div>
      </section>
    </section>
  );
};
