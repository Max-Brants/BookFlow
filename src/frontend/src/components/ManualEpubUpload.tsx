import { useRef, useState } from 'react';

import { useLanguage } from '../contexts/LanguageContext';
import { v1Api } from '../services/v1Api';

interface ManualEpubUploadProps {
  bookId: number;
  onUploaded: () => void | Promise<void>;
  onError: (message: string) => void;
}

export const ManualEpubUpload = ({ bookId, onUploaded, onError }: ManualEpubUploadProps) => {
  const { t } = useLanguage();
  const inputRef = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  if (selected) {
    return (
      <span className="flex max-w-full items-center gap-2 rounded border border-violet-400/40 px-3 py-1.5 text-xs">
        <span className="max-w-56 truncate" title={selected.name}>
          {selected.name}
        </span>
        <button
          type="button"
          disabled={uploading}
          className="font-semibold text-violet-600 underline disabled:opacity-50 dark:text-violet-300"
          onClick={() => {
            setUploading(true);
            void v1Api
              .uploadCatalogEpub(bookId, selected)
              .then(async () => {
                setSelected(null);
                if (inputRef.current) inputRef.current.value = '';
                await onUploaded();
              })
              .catch((caught: unknown) =>
                onError(caught instanceof Error ? caught.message : t('manualUpload.failed')),
              )
              .finally(() => setUploading(false));
          }}
        >
          {uploading ? t('manualUpload.uploading') : t('manualUpload.confirm')}
        </button>
        <button
          type="button"
          disabled={uploading}
          className="underline disabled:opacity-50"
          onClick={() => {
            setSelected(null);
            if (inputRef.current) inputRef.current.value = '';
          }}
        >
          {t('common.cancel')}
        </button>
      </span>
    );
  }

  return (
    <label className="cursor-pointer rounded border border-violet-400/40 px-3 py-1.5 text-xs font-medium">
      {t('manualUpload.choose')}
      <input
        ref={inputRef}
        type="file"
        accept=".epub,application/epub+zip"
        className="sr-only"
        onChange={(event) => setSelected(event.target.files?.[0] ?? null)}
      />
    </label>
  );
};
