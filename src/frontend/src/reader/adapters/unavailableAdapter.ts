import { readerCapabilityForFormat } from '../formatCapabilities';
import type { ReaderAdapter, ReaderFile } from '../types';

export type ReaderAdapterFactory = (file: ReaderFile) => Promise<ReaderAdapter>;

/**
 * Keeps the application buildable before the two optional reader engines are
 * installed. Production wiring replaces this factory with adapters backed by
 * foliate-js and PDF.js; no reader file is ever rendered as arbitrary HTML.
 */
export const unavailableAdapterFactory: ReaderAdapterFactory = async (file) => {
  const capability = readerCapabilityForFormat(file.format);
  const packageName = capability?.adapter === 'pdfjs' ? 'pdfjs-dist' : 'foliate-js';
  throw new Error(
    `The ${file.format.toUpperCase()} reader needs the ${packageName} adapter to be installed.`,
  );
};
