import { describe, expect, it, vi } from 'vitest';

import { initializeReaderAdapter, restoreReaderLocator } from '../reader/readerInitialization';
import type { ReaderAdapter, ReaderFile, ReaderLocator, ReaderPreferences } from '../reader/types';

const file: ReaderFile = {
  bookId: 7,
  fileId: 36,
  title: 'Book',
  format: 'EPUB',
  contentUrl: '/book.epub',
};

const preferences: ReaderPreferences = {
  theme: 'light',
  fontFamily: 'serif',
  fontSize: 100,
  lineHeight: 1.6,
  flow: 'paginated',
  spread: 'single',
};

const adapterWithLocator = (
  initial: ReaderLocator,
  onGoTo: (value: string) => void,
): ReaderAdapter => {
  let current = initial;
  return {
    kind: 'reflowable',
    open: vi.fn(async () => undefined),
    close: vi.fn(),
    next: vi.fn(),
    previous: vi.fn(),
    goTo: vi.fn(async (value: string) => {
      onGoTo(value);
      current = value.startsWith('fraction:')
        ? { value, progression: Number(value.slice('fraction:'.length)) }
        : { value, progression: 0.36 };
    }),
    setPreferences: vi.fn(async () => undefined),
    getLocator: vi.fn(() => current),
    getToc: vi.fn(() => []),
    subscribe: vi.fn(() => () => undefined),
  };
};

describe('reader initialization', () => {
  it('opens, applies preferences, restores and confirms before subscribing', async () => {
    const calls: string[] = [];
    const adapter = adapterWithLocator({ value: 'epubcfi(/6/2)', progression: 0 }, (value) =>
      calls.push(`goTo:${value}`),
    );
    vi.spyOn(adapter, 'open').mockImplementation(async () => {
      calls.push('open');
    });
    vi.spyOn(adapter, 'setPreferences').mockImplementation(async () => {
      calls.push('preferences');
    });
    vi.spyOn(adapter, 'getLocator').mockImplementation(() => {
      calls.push('confirm');
      return { value: 'epubcfi(/6/4)', progression: 0.36 };
    });
    vi.spyOn(adapter, 'subscribe').mockImplementation(() => {
      calls.push('subscribe');
      return () => undefined;
    });

    await initializeReaderAdapter({
      adapter,
      // The mock adapter does not inspect its container.
      // oxlint-disable-next-line typescript/no-unsafe-type-assertion
      container: {} as HTMLElement,
      file,
      initialLocator: { value: 'epubcfi(/6/4)', progression: 0.36 },
      preferences,
      isDisposed: () => false,
      onLocator: () => calls.push('publish'),
    });

    expect(calls).toEqual([
      'open',
      'preferences',
      'goTo:epubcfi(/6/4)',
      'confirm',
      'confirm',
      'publish',
      'subscribe',
    ]);
  });

  it('falls back to the saved percentage when an exact locator is not confirmed', async () => {
    const goTo = vi.fn(async (_value: string): Promise<void> => undefined);
    let current: ReaderLocator = { value: 'epubcfi(/6/2)', progression: 0 };
    const adapter = {
      kind: 'reflowable' as const,
      open: vi.fn(async () => undefined),
      close: vi.fn(),
      next: vi.fn(),
      previous: vi.fn(),
      goTo: goTo.mockImplementation(async (value: string) => {
        if (value.startsWith('fraction:')) {
          current = { value, progression: Number(value.slice('fraction:'.length)) };
        }
      }),
      setPreferences: vi.fn(async () => undefined),
      getLocator: vi.fn(() => current),
      getToc: vi.fn(() => []),
      subscribe: vi.fn(() => () => undefined),
    } satisfies ReaderAdapter;

    await restoreReaderLocator(adapter, {
      value: 'epubcfi(/6/999)',
      progression: 0.72,
    });

    expect(goTo).toHaveBeenNthCalledWith(1, 'epubcfi(/6/999)');
    expect(goTo).toHaveBeenNthCalledWith(2, 'fraction:0.72');
    expect(current).toEqual({ value: 'fraction:0.72', progression: 0.72 });
  });

  it('restores a PDF page without replacing it with the percentage fallback', async () => {
    let current: ReaderLocator = { value: 'page:1', progression: 0 };
    const goTo = vi.fn(async (value: string) => {
      current = { value, progression: 0.5 };
    });
    const adapter = {
      kind: 'fixed' as const,
      open: vi.fn(async () => undefined),
      close: vi.fn(),
      next: vi.fn(),
      previous: vi.fn(),
      goTo,
      setPreferences: vi.fn(async () => undefined),
      getLocator: vi.fn(() => current),
      getToc: vi.fn(() => []),
      subscribe: vi.fn(() => () => undefined),
    } satisfies ReaderAdapter;

    await restoreReaderLocator(adapter, { value: 'page:36', progression: 0.5 });

    expect(goTo).toHaveBeenCalledTimes(1);
    expect(goTo).toHaveBeenCalledWith('page:36');
  });
});
