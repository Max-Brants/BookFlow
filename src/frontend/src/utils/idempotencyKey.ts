type CryptoLike = {
  randomUUID?: () => string;
  getRandomValues?: (array: Uint8Array) => Uint8Array;
};

const toUuid = (bytes: Uint8Array): string => {
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(
    16,
    20,
  )}-${hex.slice(20)}`;
};

/**
 * Create an idempotency key in secure and non-secure browser contexts.
 *
 * `crypto.randomUUID()` is unavailable in some browsers when BookFlow is
 * served over plain HTTP on a LAN address. `getRandomValues()` is the preferred
 * fallback; the final Math.random fallback is sufficient because this key
 * prevents duplicate mutations and is not a security credential.
 */
export const createIdempotencyKey = (cryptoSource?: CryptoLike): string => {
  if (typeof cryptoSource?.randomUUID === 'function') {
    return cryptoSource.randomUUID();
  }
  if (!cryptoSource && typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }

  const bytes = new Uint8Array(16);
  if (typeof cryptoSource?.getRandomValues === 'function') {
    cryptoSource.getRandomValues(bytes);
  } else if (!cryptoSource && typeof globalThis.crypto?.getRandomValues === 'function') {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  return toUuid(bytes);
};
