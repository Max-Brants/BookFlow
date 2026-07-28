import type { V1Candidate } from '../types/v1';

export type InteractiveSearchSort = 'score' | 'title' | 'seeders' | 'size';

export const sortInteractiveCandidates = (
  candidates: V1Candidate[],
  sort: InteractiveSearchSort,
): V1Candidate[] =>
  candidates.toSorted((left, right) => {
    if (sort === 'title') return (left.title ?? '').localeCompare(right.title ?? '');
    if (sort === 'seeders') return (right.seeders ?? 0) - (left.seeders ?? 0);
    if (sort === 'size') return (right.size_bytes ?? 0) - (left.size_bytes ?? 0);
    return right.total_score - left.total_score;
  });

export const formatBytes = (bytes: number | null | undefined): string => {
  if (!bytes || bytes < 1) return 'Unknown';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index < 2 ? 0 : 1)} ${units[index]}`;
};
