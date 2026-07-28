import type {
  V1CatalogBook,
  V1Page,
  V1ReadingProgress,
  V1SuggestionsResponse,
  V1UserRequest,
} from '../types/v1';

interface DashboardApi {
  recentCatalog: () => Promise<V1Page<V1CatalogBook>>;
  userRequests: () => Promise<V1Page<V1UserRequest>>;
  readingProgress: () => Promise<V1Page<V1ReadingProgress>>;
  suggestions: () => Promise<V1SuggestionsResponse>;
}

export type DashboardSectionKey = 'recent' | 'requests' | 'reading' | 'suggestions';

export interface DashboardData {
  recent: V1CatalogBook[];
  requests: V1UserRequest[];
  reading: V1ReadingProgress[];
  suggestions: V1SuggestionsResponse;
  errors: Partial<Record<DashboardSectionKey, string>>;
}

/** Show only the overall Bestseller 60 on the dashboard; genres belong on the full page. */
export const dashboardSuggestionLists = (
  suggestions: V1SuggestionsResponse,
): V1SuggestionsResponse['lists'] =>
  suggestions.lists
    .filter((list) => list.key === 'overall')
    .map((list) => Object.assign({}, list, { items: list.items.slice(0, 10) }));

export const showOptionalDashboardShelf = (
  loading: boolean,
  error: string | undefined,
  itemCount: number,
): boolean => loading || Boolean(error) || itemCount > 0;

const message = (reason: unknown, fallback: string): string =>
  reason instanceof Error && reason.message ? reason.message : fallback;

/** Keep the reading dashboard available when the independent catalog panel fails. */
export const loadDashboardData = async (api: DashboardApi): Promise<DashboardData> => {
  const [recentResult, requestsResult, progressResult, suggestionsResult] =
    await Promise.allSettled([
      api.recentCatalog(),
      api.userRequests(),
      api.readingProgress(),
      api.suggestions(),
    ]);
  return {
    recent: recentResult.status === 'fulfilled' ? recentResult.value.items : [],
    requests: requestsResult.status === 'fulfilled' ? requestsResult.value.items : [],
    reading: progressResult.status === 'fulfilled' ? progressResult.value.items : [],
    suggestions:
      suggestionsResult.status === 'fulfilled'
        ? suggestionsResult.value
        : { snapshot: null, lists: [] },
    errors: {
      ...(recentResult.status === 'rejected'
        ? { recent: message(recentResult.reason, 'Recente boeken konden niet worden geladen') }
        : {}),
      ...(requestsResult.status === 'rejected'
        ? { requests: message(requestsResult.reason, 'Aanvragen konden niet worden geladen') }
        : {}),
      ...(progressResult.status === 'rejected'
        ? { reading: message(progressResult.reason, 'Leesvoortgang kon niet worden geladen') }
        : {}),
      ...(suggestionsResult.status === 'rejected'
        ? {
            suggestions: message(
              suggestionsResult.reason,
              'Trending boeken konden niet worden geladen',
            ),
          }
        : {}),
    },
  };
};

export type RequestStatusTone = 'success' | 'progress' | 'danger' | 'neutral';
export type RequestStatusKind =
  | 'available'
  | 'processing'
  | 'rejected'
  | 'cancelled'
  | 'failed'
  | 'unknown';

export const requestStatusTone = (
  status: string,
  deliveryState: string | null,
): RequestStatusTone => {
  const normalizedStatus = status.toLowerCase();
  const normalizedDelivery = deliveryState?.toLowerCase() ?? '';
  if (
    normalizedStatus === 'fulfilled' ||
    ['available', 'complete', 'completed'].includes(normalizedDelivery)
  ) {
    return 'success';
  }
  if (
    ['rejected', 'cancelled', 'failed', 'error'].includes(normalizedStatus) ||
    ['cancelled', 'error', 'failed', 'needs_attention'].includes(normalizedDelivery)
  ) {
    return 'danger';
  }
  if (
    ['pending', 'pending_approval', 'approved'].includes(normalizedStatus) ||
    [
      'queued',
      'searching',
      'resolving',
      'locating',
      'downloading',
      'importing',
      'retry_scheduled',
      'waiting_for_release',
    ].includes(normalizedDelivery)
  ) {
    return 'progress';
  }
  return 'neutral';
};

export const requestStatusKind = (
  status: string,
  deliveryState: string | null,
): RequestStatusKind => {
  const tone = requestStatusTone(status, deliveryState);
  if (tone === 'success') return 'available';
  if (tone === 'progress') return 'processing';
  const normalizedStatus = status.toLowerCase();
  const normalizedDelivery = deliveryState?.toLowerCase() ?? '';
  if (normalizedStatus === 'rejected') return 'rejected';
  if (normalizedStatus === 'cancelled' || normalizedDelivery === 'cancelled') return 'cancelled';
  if (tone === 'danger') return 'failed';
  return 'unknown';
};
