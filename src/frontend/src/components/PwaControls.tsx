import { useState } from 'react';

import { useLanguage } from '../contexts/LanguageContext';
import { useMountEffect } from '../hooks/useMountEffect';
import { nextPwaControllerState } from '../utils/pwaUpdate';

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
}

const isInstallPromptEvent = (event: Event): event is InstallPromptEvent =>
  'prompt' in event && typeof event.prompt === 'function';

export const PwaControls = () => {
  const { t } = useLanguage();
  const [installEvent, setInstallEvent] = useState<InstallPromptEvent | null>(null);
  const [updateReady, setUpdateReady] = useState(false);
  useMountEffect(() => {
    let hadController = Boolean(navigator.serviceWorker?.controller);
    const onBeforeInstall = (event: Event) => {
      if (!isInstallPromptEvent(event)) return;
      event.preventDefault();
      setInstallEvent(event);
    };
    const onControllerChange = () => {
      // clients.claim() also fires on the very first installation. Only an
      // already-controlled page represents an actual application update.
      const next = nextPwaControllerState(hadController);
      if (next.updateReady) setUpdateReady(true);
      hadController = next.hadController;
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    navigator.serviceWorker?.addEventListener('controllerchange', onControllerChange);
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      navigator.serviceWorker?.removeEventListener('controllerchange', onControllerChange);
    };
  });
  const install = () => {
    if (updateReady) {
      window.location.reload();
      return;
    }
    if (!installEvent) return;
    void installEvent.prompt().finally(() => setInstallEvent(null));
  };
  if (!installEvent && !updateReady) return null;
  return (
    <div className="fixed right-4 bottom-4 z-50 max-w-sm rounded-xl border border-(--border-muted) bg-(--bg) p-4 shadow-xl">
      <p className="text-sm font-medium">
        {updateReady ? t('pwa.updateAvailable') : t('pwa.installPrompt')}
      </p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          className="rounded-md bg-violet-700 px-3 py-2 text-sm font-medium text-white"
          onClick={install}
        >
          {updateReady ? t('pwa.refresh') : t('pwa.install')}
        </button>
        <button
          type="button"
          className="rounded-md px-3 py-2 text-sm"
          onClick={() => {
            setInstallEvent(null);
            setUpdateReady(false);
          }}
        >
          {t('pwa.later')}
        </button>
      </div>
    </div>
  );
};
