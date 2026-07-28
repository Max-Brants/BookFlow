import { useState } from 'react';

import type { ReaderPreferences } from '../types';

interface ReaderToolbarProps {
  title: string;
  controlsVisible: boolean;
  progress: number;
  preferences: ReaderPreferences;
  onBack: () => void;
  onToggleToc: () => void;
  onToggleSettings: () => void;
  onToggleFullscreen: () => void;
  onDownload: () => Promise<void>;
  onShare: () => Promise<void>;
}

const iconButtonClass =
  'rounded-md px-2 py-1.5 text-sm hover:bg-black/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:hover:bg-white/10';

export const ReaderToolbar = ({
  title,
  controlsVisible,
  progress,
  preferences,
  onBack,
  onToggleToc,
  onToggleSettings,
  onToggleFullscreen,
  onDownload,
  onShare,
}: ReaderToolbarProps) => {
  const [busyAction, setBusyAction] = useState<'download' | 'share' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const runAction = (kind: 'download' | 'share', action: () => Promise<void>) => {
    setBusyAction(kind);
    setActionError(null);
    void action()
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === 'AbortError') return;
        setActionError(caught instanceof Error ? caught.message : 'De actie is mislukt.');
      })
      .finally(() => setBusyAction(null));
  };

  return (
    <>
      <header
        className={`absolute inset-x-0 top-0 z-20 flex items-center gap-2 border-b border-black/10 px-3 py-2 transition-transform dark:border-white/10 ${
          controlsVisible ? 'translate-y-0' : '-translate-y-full'
        } ${preferences.theme === 'dark' ? 'bg-slate-950 text-slate-100' : 'bg-white/95 text-slate-900'}`}
      >
        <button
          type="button"
          className={iconButtonClass}
          onClick={onBack}
          aria-label="Close reader"
        >
          Close
        </button>
        <p className="min-w-0 flex-1 truncate text-sm font-medium" title={title}>
          {title}
        </p>
        <span className="hidden text-xs opacity-65 sm:inline">{Math.round(progress * 100)}%</span>
        <button
          type="button"
          className={iconButtonClass}
          disabled={busyAction !== null}
          onClick={() => runAction('download', onDownload)}
        >
          {busyAction === 'download' ? 'Downloaden…' : 'Download'}
        </button>
        <button
          type="button"
          className={iconButtonClass}
          disabled={busyAction !== null}
          onClick={() => runAction('share', onShare)}
        >
          {busyAction === 'share' ? 'Openen…' : 'Open in andere app'}
        </button>
        <button type="button" className={iconButtonClass} onClick={onToggleToc}>
          Contents
        </button>
        <button type="button" className={iconButtonClass} onClick={onToggleSettings}>
          Display
        </button>
        <button type="button" className={iconButtonClass} onClick={onToggleFullscreen}>
          Fullscreen
        </button>
      </header>
      {actionError && (
        <p
          role="alert"
          className="absolute top-14 right-3 z-30 max-w-sm rounded-md bg-red-700 px-3 py-2 text-sm text-white shadow-lg"
        >
          {actionError}
        </p>
      )}
    </>
  );
};
