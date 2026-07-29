import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('foliate-js/view.js', () => ({}));

import { createFoliateAdapter } from '../reader/adapters/foliateAdapter';
import type { ReaderFile } from '../reader/types';

const file: ReaderFile = {
  bookId: 7,
  fileId: 36,
  title: 'Book',
  format: 'EPUB',
  contentUrl: '/book.epub',
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Foliate adapter readiness', () => {
  it('does not finish opening before the initial renderer navigation completes', async () => {
    let finishInitialRender: (() => void) | undefined;
    const initialRender = new Promise<void>((resolve) => {
      finishInitialRender = resolve;
    });
    const transformTarget = new EventTarget();
    const view = Object.assign(new EventTarget(), {
      book: { toc: [], transformTarget },
      className: '',
      renderer: {
        next: vi.fn(() => initialRender),
      },
      open: vi.fn(async (_source: File): Promise<void> => undefined),
      close: vi.fn(),
      remove: vi.fn(),
    });
    vi.stubGlobal('document', {
      createElement: vi.fn(() => view),
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(new Blob(['epub'], { type: 'application/epub+zip' }), {
            status: 200,
            headers: { 'Content-Type': 'application/epub+zip' },
          }),
      ),
    );
    const replaceChildren = vi.fn();
    const adapter = await createFoliateAdapter('reflowable');
    let opened = false;

    const opening = adapter
      // The adapter only uses replaceChildren on this test container.
      // oxlint-disable-next-line typescript/no-unsafe-type-assertion
      .open({ replaceChildren } as unknown as HTMLElement, file)
      .then(() => {
        opened = true;
      });

    await vi.waitFor(() => expect(view.renderer.next).toHaveBeenCalledOnce());
    expect(opened).toBe(false);
    expect(replaceChildren).toHaveBeenCalledWith(view);

    finishInitialRender?.();
    await opening;

    expect(opened).toBe(true);
  });
});
