const safeFileName = (title: string, format: string): string => {
  const withoutControls = Array.from(title, (character) =>
    character.charCodeAt(0) < 32 ? '_' : character,
  ).join('');
  const safeTitle = withoutControls
    .replace(/[<>:"/\\|?*]/g, '_')
    .trim()
    .slice(0, 120);
  return `${safeTitle || 'book'}.${format.toLowerCase()}`;
};

export const bookFileFromBlob = (
  blob: Blob,
  title: string,
  format: string,
  contentType?: string | null,
): File =>
  new File([blob], safeFileName(title, format), {
    type: contentType || blob.type || 'application/octet-stream',
  });

export const fetchBookFile = async (url: string, title: string, format: string): Promise<File> => {
  const response = await fetch(url, { credentials: 'include' });
  if (!response.ok)
    throw new Error(`Het boekbestand kon niet worden geladen (${response.status}).`);
  const blob = await response.blob();
  return bookFileFromBlob(blob, title, format, response.headers.get('Content-Type'));
};

export const downloadBookFile = (file: File): void => {
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = file.name;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
};
