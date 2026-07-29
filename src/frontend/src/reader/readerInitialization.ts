import type { ReaderAdapter, ReaderFile, ReaderLocator, ReaderPreferences } from './types';

const clampProgression = (progression: number): number => Math.max(0, Math.min(1, progression));

const fractionFromLocator = (value: string): number | null => {
  if (!value.startsWith('fraction:')) return null;
  const fraction = Number(value.slice('fraction:'.length));
  return Number.isFinite(fraction) ? clampProgression(fraction) : null;
};

const locatorMatches = (requested: ReaderLocator, current: ReaderLocator | null): boolean => {
  if (!current) return false;
  const requestedFraction = fractionFromLocator(requested.value);
  if (requestedFraction !== null) {
    return Math.abs(current.progression - requestedFraction) < 0.01;
  }
  return Boolean(requested.value) && current.value === requested.value;
};

/**
 * Restore an exact locator and verify the adapter published that location.
 * A failed or stale locator falls back to the persisted percentage so the
 * reader remains usable when a file was replaced or its structure changed.
 */
export const restoreReaderLocator = async (
  adapter: ReaderAdapter,
  initialLocator: ReaderLocator | null | undefined,
): Promise<ReaderLocator | null> => {
  if (!initialLocator) return adapter.getLocator();

  if (initialLocator.value) {
    try {
      await adapter.goTo(initialLocator.value);
    } catch (caught: unknown) {
      console.warn(
        'Failed to restore the saved reader locator; using percentage fallback.',
        caught,
      );
    }
    const restored = adapter.getLocator();
    if (locatorMatches(initialLocator, restored)) return restored;
    console.warn(
      'Saved reader locator was not confirmed; using percentage fallback.',
      initialLocator.value,
    );
  }

  try {
    await adapter.goTo(`fraction:${clampProgression(initialLocator.progression)}`);
  } catch (caught: unknown) {
    console.warn('Failed to restore the reader percentage fallback.', caught);
  }
  return adapter.getLocator();
};

export interface ReaderAdapterInitializationOptions {
  adapter: ReaderAdapter;
  container: HTMLElement;
  file: ReaderFile;
  initialLocator: ReaderLocator | null | undefined;
  preferences: ReaderPreferences;
  isDisposed: () => boolean;
  onLocator: (locator: ReaderLocator) => void;
}

/** Run the one-time open sequence before subscribing to reader progress. */
export const initializeReaderAdapter = async ({
  adapter,
  container,
  file,
  initialLocator,
  preferences,
  isDisposed,
  onLocator,
}: ReaderAdapterInitializationOptions): Promise<(() => void) | null> => {
  await adapter.open(container, file);
  if (isDisposed()) return null;
  await adapter.setPreferences(preferences);
  if (isDisposed()) return null;
  await restoreReaderLocator(adapter, initialLocator);
  if (isDisposed()) return null;
  const current = adapter.getLocator();
  if (current) onLocator(current);
  return adapter.subscribe(onLocator);
};
