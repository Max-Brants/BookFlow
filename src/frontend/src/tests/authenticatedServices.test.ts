import { describe, expect, it } from 'vitest';

import { shouldEnableAuthenticatedServices } from '../utils/authenticatedServices';

describe('authenticated service gating', () => {
  it('keeps sockets and polling disabled while authentication is unresolved', () => {
    expect(
      shouldEnableAuthenticatedServices({
        authChecked: false,
        authRequired: true,
        isAuthenticated: false,
      }),
    ).toBe(false);
  });

  it('keeps sockets and polling disabled on the login page', () => {
    expect(
      shouldEnableAuthenticatedServices({
        authChecked: true,
        authRequired: true,
        isAuthenticated: false,
      }),
    ).toBe(false);
  });

  it('enables authenticated services after login', () => {
    expect(
      shouldEnableAuthenticatedServices({
        authChecked: true,
        authRequired: true,
        isAuthenticated: true,
      }),
    ).toBe(true);
  });

  it('enables services when authentication is not required', () => {
    expect(
      shouldEnableAuthenticatedServices({
        authChecked: true,
        authRequired: false,
        isAuthenticated: false,
      }),
    ).toBe(true);
  });
});
