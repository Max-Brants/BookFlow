import { describe, expect, it } from 'vitest';

import { formatBytes, sortInteractiveCandidates } from '../pages/interactiveSearchModel';
import type { V1Candidate } from '../types/v1';

const candidate = (id: number, values: Partial<V1Candidate>): V1Candidate => ({
  id,
  request_process_id: 1,
  accepted: 1,
  total_score: 0,
  file_format: 'epub',
  ...values,
});

describe('interactive search result presentation', () => {
  it('sorts all candidates including rejected candidates by profile score', () => {
    const rejected = candidate(1, { total_score: -20, accepted: 0 });
    const eligible = candidate(2, { total_score: 30 });
    expect(sortInteractiveCandidates([rejected, eligible], 'score').map((item) => item.id)).toEqual(
      [2, 1],
    );
  });

  it('formats known and unknown sizes for scanable result rows', () => {
    expect(formatBytes(1024 * 1024 * 2)).toBe('2.0 MB');
    expect(formatBytes(null)).toBe('Unknown');
  });
});
