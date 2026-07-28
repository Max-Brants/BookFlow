import type { ReaderKind } from './types';

export interface ReaderCapability {
  kind: ReaderKind;
  adapter: 'foliate' | 'pdfjs';
}

const CAPABILITIES: Record<string, ReaderCapability> = {
  epub: { kind: 'reflowable', adapter: 'foliate' },
  kepub: { kind: 'reflowable', adapter: 'foliate' },
  mobi: { kind: 'reflowable', adapter: 'foliate' },
  azw: { kind: 'reflowable', adapter: 'foliate' },
  azw3: { kind: 'reflowable', adapter: 'foliate' },
  fb2: { kind: 'reflowable', adapter: 'foliate' },
  cbz: { kind: 'fixed', adapter: 'foliate' },
  pdf: { kind: 'fixed', adapter: 'pdfjs' },
};

export const normalizeBookFormat = (format: string | null | undefined): string =>
  (format ?? '').trim().toLowerCase().replace(/^\./, '');

export const readerCapabilityForFormat = (
  format: string | null | undefined,
): ReaderCapability | null => CAPABILITIES[normalizeBookFormat(format)] ?? null;

export const canReadInBrowser = (format: string | null | undefined): boolean =>
  readerCapabilityForFormat(format) !== null;

export const readerKindForFormat = (format: string | null | undefined): ReaderKind | null =>
  readerCapabilityForFormat(format)?.kind ?? null;
