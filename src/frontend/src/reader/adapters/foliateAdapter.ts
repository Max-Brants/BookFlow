// oxlint-disable-next-line import/no-unassigned-import
import 'foliate-js/view.js';
import type {
  ReaderAdapter,
  ReaderFile,
  ReaderLocator,
  ReaderPreferences,
  ReaderTocItem,
} from '../types';

type FoliateLocation = {
  cfi?: string;
  fraction?: number;
};

type FoliateTocItem = {
  id?: string | number;
  label?: string;
  href?: string;
  subitems?: FoliateTocItem[];
};

type FoliateTransformDetail = {
  data: unknown;
  name?: string;
};

type FoliateView = HTMLElement & {
  book?: {
    toc?: FoliateTocItem[];
    transformTarget?: EventTarget;
  };
  renderer?: HTMLElement & {
    next?: () => Promise<void>;
    setStyles?: (css: string) => void;
  };
  open: (file: File) => Promise<void>;
  init: (options: {
    lastLocation?: string | { fraction: number };
    showTextStart?: boolean;
  }) => Promise<void>;
  close: () => void;
  next: () => Promise<void>;
  prev: () => Promise<void>;
  goTo: (target: string | { fraction: number }) => Promise<unknown>;
  lastLocation?: FoliateLocation;
};

const fileName = (file: ReaderFile): string => {
  const withoutControls = Array.from(file.title, (character) =>
    character.charCodeAt(0) < 32 ? '_' : character,
  ).join('');
  const safeTitle = withoutControls.replace(/[<>:"/\\|?*]/g, '_').slice(0, 120);
  return `${safeTitle || 'book'}.${file.format.toLowerCase()}`;
};

const tocItems = (items: FoliateTocItem[] | undefined, prefix = 'toc'): ReaderTocItem[] =>
  (items ?? []).map((item, index) => ({
    id: String(item.id ?? `${prefix}-${index}`),
    label: item.label?.trim() || `Section ${index + 1}`,
    href: item.href,
    children: tocItems(item.subitems, `${prefix}-${index}`),
  }));

const locatorFromLocation = (location: FoliateLocation | undefined): ReaderLocator | null => {
  if (!location) return null;
  const progression = Math.max(0, Math.min(1, Number(location.fraction) || 0));
  return {
    value: location.cfi || `fraction:${progression}`,
    progression,
  };
};

const readerCss = (preferences: ReaderPreferences): string => {
  let family = 'Georgia, "Times New Roman", serif';
  if (preferences.fontFamily === 'sans-serif') {
    family = 'system-ui, sans-serif';
  } else if (preferences.fontFamily === 'opendyslexic') {
    family = 'OpenDyslexic, system-ui, sans-serif';
  }
  let colors = 'color: #111827 !important; background: #ffffff !important;';
  if (preferences.theme === 'dark') {
    colors = 'color: #e5e7eb !important; background: #020617 !important;';
  } else if (preferences.theme === 'sepia') {
    colors = 'color: #433422 !important; background: #f4ecd8 !important;';
  }
  return `
    :root {
      font-family: ${family} !important;
      font-size: ${preferences.fontSize}% !important;
      line-height: ${preferences.lineHeight} !important;
      ${colors}
    }
    body { font-family: inherit !important; line-height: inherit !important; ${colors} }
    img, svg, video { max-width: 100% !important; height: auto !important; }
  `;
};

class FoliateAdapter implements ReaderAdapter {
  readonly kind;
  private view: FoliateView | null = null;
  private locator: ReaderLocator | null = null;
  private listeners = new Set<(locator: ReaderLocator) => void>();
  private relocateHandler: EventListener | null = null;
  private transformHandler: EventListener | null = null;

  constructor(kind: ReaderAdapter['kind']) {
    this.kind = kind;
  }

  async open(container: HTMLElement, file: ReaderFile): Promise<void> {
    const response = await fetch(file.contentUrl, { credentials: 'include' });
    if (!response.ok) {
      throw new Error(`The book file could not be loaded (${response.status}).`);
    }
    const blob = await response.blob();
    const source = new File([blob], fileName(file), {
      type: response.headers.get('Content-Type') || blob.type,
    });
    // The custom element is registered by foliate-js above.
    // oxlint-disable-next-line typescript/no-unsafe-type-assertion
    const view = document.createElement('foliate-view') as FoliateView;
    view.className = 'block h-full w-full';
    // CustomEvent.detail is part of foliate's public relocate event contract.
    // oxlint-disable-next-line typescript/no-unsafe-type-assertion
    this.relocateHandler = ((event: CustomEvent<FoliateLocation>) => {
      const locator = locatorFromLocation(event.detail);
      if (!locator) return;
      this.locator = locator;
      for (const listener of this.listeners) listener(locator);
    }) as EventListener;
    view.addEventListener('relocate', this.relocateHandler);
    container.replaceChildren(view);
    this.view = view;
    await view.open(source);

    // EPUB resources are transformed lazily. A single malformed optional
    // asset must not prevent the whole section from becoming readable.
    // This mirrors foliate-js' own reader integration.
    // CustomEvent.detail is part of foliate's public transform event contract.
    // oxlint-disable-next-line typescript/no-unsafe-type-assertion
    this.transformHandler = ((event: CustomEvent<FoliateTransformDetail>) => {
      const detail = event.detail;
      detail.data = Promise.resolve(detail.data).catch((caught: unknown) => {
        console.warn(`Failed to load EPUB resource ${detail.name ?? 'unknown'}`, caught);
        return '';
      });
    }) as EventListener;
    view.book?.transformTarget?.addEventListener('data', this.transformHandler);

    // Foliate's reference reader starts the first section without awaiting
    // the iframe load. Awaiting View.init() can hang the complete React reader
    // when Chromium delivers a ResizeObserver callback during iframe navigation.
    const firstRender = view.renderer?.next?.();
    if (firstRender) {
      await firstRender.catch((caught: unknown) => {
        console.warn('Failed to render the first EPUB section', caught);
      });
    }
  }

  close(): void {
    if (this.view && this.relocateHandler) {
      this.view.removeEventListener('relocate', this.relocateHandler);
    }
    if (this.view?.book?.transformTarget && this.transformHandler) {
      this.view.book.transformTarget.removeEventListener('data', this.transformHandler);
    }
    this.view?.close();
    this.view?.remove();
    this.view = null;
    this.relocateHandler = null;
    this.transformHandler = null;
    this.listeners.clear();
  }

  next(): Promise<void> | void {
    return this.view?.next();
  }

  previous(): Promise<void> | void {
    return this.view?.prev();
  }

  async goTo(locator: string): Promise<void> {
    if (!this.view) return;
    if (locator.startsWith('fraction:')) {
      const fraction = Number(locator.slice('fraction:'.length));
      if (Number.isFinite(fraction)) {
        await this.view.goTo({ fraction });
        return;
      }
    }
    await this.view.goTo(locator);
  }

  setPreferences(preferences: ReaderPreferences): void {
    const renderer = this.view?.renderer;
    if (!renderer) return;
    renderer.setAttribute('flow', preferences.flow);
    renderer.setAttribute('max-column-count', preferences.spread === 'double' ? '2' : '1');
    renderer.setStyles?.(readerCss(preferences));
  }

  getLocator(): ReaderLocator | null {
    return this.locator ?? locatorFromLocation(this.view?.lastLocation);
  }

  getToc(): ReaderTocItem[] {
    return tocItems(this.view?.book?.toc);
  }

  subscribe(listener: (locator: ReaderLocator) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

export const createFoliateAdapter = (kind: ReaderAdapter['kind']): Promise<ReaderAdapter> =>
  Promise.resolve(new FoliateAdapter(kind));
