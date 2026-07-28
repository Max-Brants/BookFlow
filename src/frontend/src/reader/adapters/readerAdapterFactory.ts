import { readerCapabilityForFormat } from '../formatCapabilities';
import type { ReaderAdapter, ReaderFile } from '../types';

export const readerAdapterFactory = async (file: ReaderFile): Promise<ReaderAdapter> => {
  const capability = readerCapabilityForFormat(file.format);
  if (!capability) throw new Error(`${file.format.toUpperCase()} is not supported in the reader.`);
  if (capability.adapter === 'pdfjs') {
    const { createPdfAdapter } = await import('./pdfAdapter');
    return createPdfAdapter();
  }
  const { createFoliateAdapter } = await import('./foliateAdapter');
  return createFoliateAdapter(capability.kind);
};
