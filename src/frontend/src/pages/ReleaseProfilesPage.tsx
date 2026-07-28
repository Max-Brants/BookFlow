import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';

import { useDependencyEffect } from '../hooks/useMountEffect';
import { v1Api } from '../services/v1Api';
import type {
  V1ReleaseProfile,
  V1ReleaseProfileConfig,
  V1ReleaseProfilePreview,
} from '../types/v1';

type ProfileDraft = Pick<V1ReleaseProfile, 'name' | 'is_default' | 'is_active' | 'config'> & {
  id?: number;
};

const csv = (value: string): string[] =>
  value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
const scoreMap = (value: string): Record<string, number> =>
  Object.fromEntries(
    value
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const [key, raw] = part.split(':');
        return [key.trim(), Number(raw) || 0];
      }),
  );
const scoreText = (value: Record<string, number>): string =>
  Object.entries(value)
    .map(([key, score]) => `${key}:${score}`)
    .join(', ');

const blankConfig = (): V1ReleaseProfileConfig => ({
  allowed_formats: ['epub'],
  allowed_languages: [],
  allowed_protocols: [],
  allowed_indexers: [],
  min_seeders: 0,
  max_size_bytes: null,
  allow_bundles: false,
  allow_archives: false,
  minimum_automatic_score: 0,
  score_weights: {},
  term_scores: {},
  indexer_priorities: {},
});
const blankProfile = (): ProfileDraft => ({
  name: 'New profile',
  is_default: false,
  is_active: true,
  config: blankConfig(),
});
const messageFor = (caught: unknown, fallback: string): string =>
  caught instanceof Error ? caught.message : fallback;

export const ReleaseProfilesPage = ({
  onShowToast,
}: {
  onShowToast: (message: string, type: 'success' | 'error' | 'info') => void;
}) => {
  const [profiles, setProfiles] = useState<V1ReleaseProfile[]>([]);
  const [editing, setEditing] = useState<ProfileDraft | null>(null);
  const [preview, setPreview] = useState<V1ReleaseProfilePreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setProfiles((await v1Api.adminReleaseProfiles()).items);
      setError(null);
    } catch (caught) {
      setError(messageFor(caught, 'Could not load release profiles.'));
    }
  }, []);
  useDependencyEffect(() => {
    void load();
  }, [load]);

  const setConfig = (update: Partial<V1ReleaseProfileConfig>) =>
    setEditing((current) =>
      current ? { ...current, config: { ...current.config, ...update } } : current,
    );
  const save = async () => {
    if (!editing) return;
    const body = {
      name: editing.name,
      is_default: editing.is_default,
      is_active: editing.is_active,
      config: editing.config,
    };
    try {
      if (editing.id) await v1Api.updateReleaseProfile(editing.id, body);
      else await v1Api.createReleaseProfile(body);
      setEditing(null);
      setPreview(null);
      await load();
      onShowToast('Release profile saved', 'success');
    } catch (caught) {
      setError(messageFor(caught, 'Could not save release profile.'));
    }
  };
  const deleteProfile = (profile: V1ReleaseProfile) => {
    // oxlint-disable-next-line no-alert -- deleting a profile is destructive
    if (!window.confirm(`Delete ${profile.name}?`)) return;
    void v1Api
      .deleteReleaseProfile(profile.id)
      .then(load)
      .catch((caught: unknown) => setError(messageFor(caught, 'Could not delete profile.')));
  };

  return (
    <section className="mx-auto max-w-5xl pb-16">
      <Link to="/admin/settings" className="text-sm text-violet-700 dark:text-violet-300">
        ← Administration settings
      </Link>
      <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Release profiles</h1>
          <p className="mt-2 text-sm opacity-65">
            Automatic Search only chooses releases that pass the filters and minimum score.
            Interactive Search can be force-selected with an audit trail.
          </p>
        </div>
        <button
          type="button"
          className="rounded-md bg-violet-600 px-3 py-2 text-sm font-medium text-white"
          onClick={() => setEditing(blankProfile())}
        >
          New profile
        </button>
      </div>
      {error && (
        <p className="mt-5 rounded border border-red-400/35 bg-red-500/10 p-3 text-sm text-red-700">
          {error}
        </p>
      )}
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {profiles.map((profile) => (
          <article key={profile.id} className="rounded-xl border border-(--border-muted) p-4">
            <div className="flex justify-between gap-3">
              <h2 className="font-semibold">{profile.name}</h2>
              {profile.is_default && (
                <span className="text-xs text-violet-700 dark:text-violet-200">Default</span>
              )}
            </div>
            <p className="mt-2 text-sm opacity-65">
              Formats: {profile.config.allowed_formats.join(', ') || 'any'} · automatic minimum:{' '}
              {profile.config.minimum_automatic_score}
            </p>
            <div className="mt-4 flex gap-3 text-sm">
              <button
                type="button"
                className="underline"
                onClick={() =>
                  setEditing({
                    id: profile.id,
                    name: profile.name,
                    is_default: profile.is_default,
                    is_active: profile.is_active,
                    config: profile.config,
                  })
                }
              >
                Edit
              </button>
              <button
                type="button"
                className="text-red-700 underline"
                onClick={() => deleteProfile(profile)}
              >
                Delete
              </button>
            </div>
          </article>
        ))}
      </div>
      {profiles.length === 0 && (
        <p className="mt-6 rounded-xl border border-dashed border-(--border-muted) p-6 text-sm opacity-65">
          Create a profile before users request books.
        </p>
      )}
      {editing && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-black/50 p-4">
          <form
            className="mx-auto mt-12 max-w-2xl rounded-xl bg-(--bg) p-5 shadow-2xl"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <div className="flex items-center justify-between gap-4">
              <h2 className="text-xl font-semibold">
                {editing.id ? 'Edit profile' : 'New profile'}
              </h2>
              <button type="button" onClick={() => setEditing(null)}>
                ×
              </button>
            </div>
            <label className="mt-5 block text-sm">
              Name
              <input
                className="mt-1 w-full rounded border border-(--border-muted) bg-transparent px-3 py-2"
                value={editing.name}
                onChange={(event) => setEditing({ ...editing, name: event.target.value })}
              />
            </label>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="text-sm">
                Formats (comma separated)
                <input
                  className="mt-1 w-full rounded border border-(--border-muted) bg-transparent px-3 py-2"
                  value={editing.config.allowed_formats.join(', ')}
                  onChange={(event) => setConfig({ allowed_formats: csv(event.target.value) })}
                />
              </label>
              <label className="text-sm">
                Languages (comma separated)
                <input
                  className="mt-1 w-full rounded border border-(--border-muted) bg-transparent px-3 py-2"
                  value={editing.config.allowed_languages.join(', ')}
                  onChange={(event) => setConfig({ allowed_languages: csv(event.target.value) })}
                />
              </label>
              <label className="text-sm">
                Protocols (comma separated)
                <input
                  className="mt-1 w-full rounded border border-(--border-muted) bg-transparent px-3 py-2"
                  value={editing.config.allowed_protocols.join(', ')}
                  onChange={(event) => setConfig({ allowed_protocols: csv(event.target.value) })}
                />
              </label>
              <label className="text-sm">
                Allowed indexers (comma separated)
                <input
                  className="mt-1 w-full rounded border border-(--border-muted) bg-transparent px-3 py-2"
                  value={editing.config.allowed_indexers.join(', ')}
                  onChange={(event) => setConfig({ allowed_indexers: csv(event.target.value) })}
                />
              </label>
              <label className="text-sm">
                Minimum automatic score
                <input
                  type="number"
                  className="mt-1 w-full rounded border border-(--border-muted) bg-transparent px-3 py-2"
                  value={editing.config.minimum_automatic_score}
                  onChange={(event) =>
                    setConfig({ minimum_automatic_score: Number(event.target.value) })
                  }
                />
              </label>
              <label className="text-sm">
                Minimum seeders
                <input
                  type="number"
                  min="0"
                  className="mt-1 w-full rounded border border-(--border-muted) bg-transparent px-3 py-2"
                  value={editing.config.min_seeders}
                  onChange={(event) =>
                    setConfig({
                      min_seeders: Number(event.target.value) || 0,
                    })
                  }
                />
              </label>
              <label className="text-sm">
                Maximum size (bytes)
                <input
                  type="number"
                  className="mt-1 w-full rounded border border-(--border-muted) bg-transparent px-3 py-2"
                  value={editing.config.max_size_bytes ?? ''}
                  onChange={(event) =>
                    setConfig({
                      max_size_bytes: event.target.value ? Number(event.target.value) : null,
                    })
                  }
                />
              </label>
              <label className="text-sm">
                Term scores (term:score)
                <input
                  className="mt-1 w-full rounded border border-(--border-muted) bg-transparent px-3 py-2"
                  value={scoreText(editing.config.term_scores)}
                  onChange={(event) => setConfig({ term_scores: scoreMap(event.target.value) })}
                />
              </label>
              <label className="text-sm">
                Score weights (name:weight)
                <input
                  className="mt-1 w-full rounded border border-(--border-muted) bg-transparent px-3 py-2"
                  value={scoreText(editing.config.score_weights)}
                  onChange={(event) => setConfig({ score_weights: scoreMap(event.target.value) })}
                />
              </label>
              <label className="text-sm">
                Indexer priorities (name:priority)
                <input
                  className="mt-1 w-full rounded border border-(--border-muted) bg-transparent px-3 py-2"
                  value={scoreText(editing.config.indexer_priorities)}
                  onChange={(event) =>
                    setConfig({ indexer_priorities: scoreMap(event.target.value) })
                  }
                />
              </label>
            </div>
            <label className="mt-4 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={editing.is_default}
                onChange={(event) => setEditing({ ...editing, is_default: event.target.checked })}
              />{' '}
              Default profile
            </label>
            <label className="mt-2 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={editing.is_active}
                onChange={(event) => setEditing({ ...editing, is_active: event.target.checked })}
              />{' '}
              Active
            </label>
            <label className="mt-2 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={editing.config.allow_bundles}
                onChange={(event) => setConfig({ allow_bundles: event.target.checked })}
              />{' '}
              Allow bundles
            </label>
            <label className="mt-2 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={editing.config.allow_archives}
                onChange={(event) => setConfig({ allow_archives: event.target.checked })}
              />{' '}
              Allow archives
            </label>
            <div className="mt-5 flex flex-wrap gap-3">
              <button
                type="submit"
                className="rounded bg-violet-600 px-4 py-2 text-sm font-medium text-white"
              >
                Save profile
              </button>
              <button
                type="button"
                className="rounded border border-(--border-muted) px-4 py-2 text-sm"
                onClick={() =>
                  void v1Api
                    .previewReleaseProfile(editing.config, {
                      source: 'profile-preview',
                      title: 'Preview release',
                      format: editing.config.allowed_formats[0] ?? 'epub',
                      protocol: editing.config.allowed_protocols[0] ?? 'direct',
                      language: editing.config.allowed_languages[0],
                      seeders: editing.config.min_seeders,
                    })
                    .then(setPreview)
                    .catch((caught: unknown) => setError(messageFor(caught, 'Preview failed.')))
                }
              >
                Preview score
              </button>
            </div>
            {preview && (
              <p className="mt-4 rounded bg-(--bg-soft) p-3 text-sm">
                Score {preview.evaluation.total_score} ·{' '}
                {preview.evaluation.automatic_eligible
                  ? 'accepted automatically'
                  : `skipped: ${preview.evaluation.reject_reasons.join(', ')}`}
              </p>
            )}
          </form>
        </div>
      )}
    </section>
  );
};
