import { describe, expect, it } from 'vitest';

import { createIdempotencyKey } from '../utils/idempotencyKey';

describe('createIdempotencyKey', () => {
  it('uses randomUUID when the browser provides it', () => {
    expect(
      createIdempotencyKey({
        randomUUID: () => 'native-uuid',
      }),
    ).toBe('native-uuid');
  });

  it('creates an RFC 4122 v4-shaped key when randomUUID is unavailable', () => {
    const key = createIdempotencyKey({
      getRandomValues: (bytes) => {
        bytes.fill(0xab);
        return bytes;
      },
    });

    expect(key).toBe('abababab-abab-4bab-abab-abababababab');
  });

  it('still creates a valid key when the HTTP browser exposes no crypto methods', () => {
    expect(createIdempotencyKey({})).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });
});
