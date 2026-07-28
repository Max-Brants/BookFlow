import { describe, expect, it } from 'vitest';

import { canManageRequestProcess } from '../pages/requestsPresentation';

describe('canManageRequestProcess', () => {
  it('keeps request history read-only', () => {
    expect(canManageRequestProcess(true, 'waiting_for_release')).toBe(false);
    expect(canManageRequestProcess(true, 'cancelled')).toBe(false);
  });

  it('offers management actions only for active processes', () => {
    expect(canManageRequestProcess(false, 'waiting_for_release')).toBe(true);
    expect(canManageRequestProcess(false, 'completed')).toBe(false);
    expect(canManageRequestProcess(false, 'cancelled')).toBe(false);
    expect(canManageRequestProcess(false, 'failed')).toBe(false);
  });
});
