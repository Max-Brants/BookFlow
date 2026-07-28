import {
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type DragEvent,
  type FormEvent,
} from 'react';
import { createPortal } from 'react-dom';

import { useLanguage } from '../contexts/LanguageContext';
import { useBodyScrollLock } from '../hooks/useBodyScrollLock';
import { useEscapeKey } from '../hooks/useEscapeKey';
import { useDependencyEffect } from '../hooks/useMountEffect';
import { submitIssueReport, V1ApiError } from '../services/v1Api';
import { createIdempotencyKey } from '../utils/idempotencyKey';

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const ACCEPTED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);

interface IssueReportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onShowToast?: (
    message: string,
    type: 'success' | 'error' | 'info' | 'warning',
    persistent?: boolean,
  ) => string;
}

export const IssueReportModal = ({ isOpen, onClose, onShowToast }: IssueReportModalProps) => {
  const { language, t } = useLanguage();
  const titleRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState('');
  const [pageUrl, setPageUrl] = useState('');
  const [description, setDescription] = useState('');
  const [image, setImage] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const retryKeyRef = useRef<string | null>(null);
  const titleId = useId();
  const pageUrlId = useId();
  const descriptionId = useId();
  const imageId = useId();
  const errorId = useId();

  useBodyScrollLock(isOpen);
  useEscapeKey(isOpen && !isSubmitting, onClose);

  useDependencyEffect(() => {
    let frame: number | null = null;
    if (isOpen) {
      setPageUrl(window.location.href);
      setSubmitError(null);
      frame = window.requestAnimationFrame(() => titleRef.current?.focus());
    }
    return () => {
      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }, [isOpen]);

  useDependencyEffect(() => {
    if (!image) {
      setImagePreviewUrl(null);
      return () => {
        // No object URL was created for this render.
      };
    }
    const nextPreviewUrl = URL.createObjectURL(image);
    setImagePreviewUrl(nextPreviewUrl);
    return () => URL.revokeObjectURL(nextPreviewUrl);
  }, [image]);

  const resetForm = () => {
    setTitle('');
    setDescription('');
    setImage(null);
    setImageError(null);
    setSubmitError(null);
    retryKeyRef.current = null;
  };

  const validateAndSetImage = (nextImage: File | null | undefined) => {
    if (!nextImage) return;
    if (!ACCEPTED_IMAGE_TYPES.has(nextImage.type)) {
      setImageError(t('issueReport.imageTypeError'));
      return;
    }
    if (nextImage.size > MAX_IMAGE_BYTES) {
      setImageError(t('issueReport.imageSizeError'));
      return;
    }
    setImageError(null);
    setImage(nextImage);
    retryKeyRef.current = null;
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    validateAndSetImage(event.currentTarget.files?.[0]);
    // Selecting the same file again should still trigger a change event.
    event.currentTarget.value = '';
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    validateAndSetImage(event.dataTransfer.files[0]);
  };

  const handlePaste = (event: ClipboardEvent<HTMLDivElement>) => {
    const pastedImage = Array.from(event.clipboardData.items).find((item) =>
      ACCEPTED_IMAGE_TYPES.has(item.type),
    );
    const pastedFile = pastedImage?.getAsFile();
    if (!pastedFile) return;
    event.preventDefault();
    validateAndSetImage(pastedFile);
  };

  const handleClose = () => {
    if (!isSubmitting) onClose();
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;

    const trimmedTitle = title.trim();
    const trimmedDescription = description.trim();
    if (!trimmedTitle || !trimmedDescription) {
      setSubmitError(t('issueReport.requiredError'));
      return;
    }

    const data = new FormData();
    data.set('title', trimmedTitle);
    data.set('page_url', pageUrl.trim());
    data.set('description', trimmedDescription);
    data.set('ui_language', language);
    if (image) data.set('image', image);

    setIsSubmitting(true);
    setSubmitError(null);
    const idempotencyKey = retryKeyRef.current ?? createIdempotencyKey();
    retryKeyRef.current = idempotencyKey;
    try {
      const result = await submitIssueReport(data, idempotencyKey);
      if (result.attachment_status === 'failed') {
        onShowToast?.(
          t('issueReport.successAttachmentFailed', { number: result.issue_number }),
          'warning',
        );
      } else {
        onShowToast?.(t('issueReport.success', { number: result.issue_number }), 'success');
      }
      resetForm();
      onClose();
    } catch (error) {
      setSubmitError(error instanceof V1ApiError ? error.message : t('issueReport.submitFailed'));
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-1000 flex items-center justify-center bg-slate-950/60 p-4"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) handleClose();
      }}
      onPaste={handlePaste}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={submitError ? errorId : undefined}
        className="max-h-[calc(100vh-2rem)] w-full max-w-xl overflow-y-auto rounded-xl border border-(--border-muted) bg-(--bg) p-5 shadow-2xl sm:p-6"
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 id={titleId} className="text-lg font-semibold">
              {t('issueReport.title')}
            </h2>
            <p className="mt-1 text-sm opacity-70">{t('issueReport.intro')}</p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            disabled={isSubmitting}
            className="hover-action rounded-full p-2 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={t('issueReport.close')}
          >
            <svg
              className="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path strokeLinecap="round" d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </div>

        <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
          <label className="block text-sm font-medium" htmlFor={`${titleId}-input`}>
            {t('issueReport.subject')}
            <input
              ref={titleRef}
              id={`${titleId}-input`}
              value={title}
              onChange={(event) => {
                setTitle(event.target.value);
                retryKeyRef.current = null;
              }}
              maxLength={200}
              required
              disabled={isSubmitting}
              className="mt-1.5 w-full rounded-lg border border-(--border-muted) bg-(--bg-soft) px-3 py-2 text-sm outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 disabled:opacity-60"
            />
          </label>

          <label className="block text-sm font-medium" htmlFor={pageUrlId}>
            {t('issueReport.pageUrl')}
            <input
              id={pageUrlId}
              type="url"
              value={pageUrl}
              onChange={(event) => {
                setPageUrl(event.target.value);
                retryKeyRef.current = null;
              }}
              required
              disabled={isSubmitting}
              className="mt-1.5 w-full rounded-lg border border-(--border-muted) bg-(--bg-soft) px-3 py-2 text-sm outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 disabled:opacity-60"
            />
          </label>

          <label className="block text-sm font-medium" htmlFor={descriptionId}>
            {t('issueReport.description')}
            <textarea
              id={descriptionId}
              value={description}
              onChange={(event) => {
                setDescription(event.target.value);
                retryKeyRef.current = null;
              }}
              maxLength={10000}
              required
              rows={7}
              disabled={isSubmitting}
              className="mt-1.5 w-full resize-y rounded-lg border border-(--border-muted) bg-(--bg-soft) px-3 py-2 text-sm outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 disabled:opacity-60"
            />
            <span className="mt-1 block text-right text-xs opacity-60">
              {t('issueReport.characterCount', { count: description.length, max: 10000 })}
            </span>
          </label>

          <div
            className="rounded-lg border border-dashed border-(--border-muted) p-3"
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleDrop}
          >
            <div className="flex flex-wrap items-center gap-3">
              <input
                ref={inputRef}
                id={imageId}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="sr-only"
                onChange={handleFileChange}
                disabled={isSubmitting}
              />
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                disabled={isSubmitting}
                className="rounded-lg border border-(--border-muted) px-3 py-2 text-sm font-medium hover:bg-(--hover-surface) disabled:cursor-not-allowed disabled:opacity-60"
              >
                {t('issueReport.chooseImage')}
              </button>
              <span className="text-xs opacity-70">{t('issueReport.imageHint')}</span>
            </div>
            {imageError && (
              <p className="mt-2 text-sm text-red-600 dark:text-red-400">{imageError}</p>
            )}
            {image && imagePreviewUrl && (
              <div className="mt-3 flex items-start gap-3">
                <img
                  src={imagePreviewUrl}
                  alt={t('issueReport.imagePreview')}
                  className="h-20 w-20 rounded-md border border-(--border-muted) object-cover"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{image.name}</p>
                  <button
                    type="button"
                    onClick={() => {
                      setImage(null);
                      setImageError(null);
                      retryKeyRef.current = null;
                    }}
                    disabled={isSubmitting}
                    className="mt-1 text-sm text-red-600 hover:underline disabled:opacity-60 dark:text-red-400"
                  >
                    {t('issueReport.removeImage')}
                  </button>
                </div>
              </div>
            )}
          </div>

          {submitError && (
            <p
              id={errorId}
              role="alert"
              className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300"
            >
              {submitError}
            </p>
          )}

          <div className="flex justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={handleClose}
              disabled={isSubmitting}
              className="rounded-lg px-3 py-2 text-sm font-medium hover:bg-(--hover-surface) disabled:cursor-not-allowed disabled:opacity-60"
            >
              {t('common.cancel')}
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSubmitting ? t('issueReport.submitting') : t('issueReport.submit')}
            </button>
          </div>
        </form>
      </section>
    </div>,
    document.body,
  );
};
