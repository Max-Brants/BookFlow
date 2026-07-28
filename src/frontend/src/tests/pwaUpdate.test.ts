import { describe, expect, it } from 'vitest';

import { nextPwaControllerState } from '../utils/pwaUpdate';

describe('nextPwaControllerState', () => {
  it('does not show an update prompt after the first service-worker installation', () => {
    expect(nextPwaControllerState(false)).toEqual({ hadController: true, updateReady: false });
  });

  it('shows an update prompt when an existing controller is replaced', () => {
    expect(nextPwaControllerState(true)).toEqual({ hadController: true, updateReady: true });
  });
});
