import { useCallback, useState } from 'react';

import { useLanguage } from '../contexts/LanguageContext';
import { useDependencyEffect } from '../hooks/useMountEffect';
import { v1Api } from '../services/v1Api';
import type { V1PatcherManifest, V1PushRule, V1PushSubscription } from '../types/v1';

const copy = async (value: string) => navigator.clipboard?.writeText(value);
const absoluteUrl = (value: string): string => new URL(value, window.location.origin).toString();
const decodeVapidKey = (value: string): Uint8Array<ArrayBuffer> => {
  const padded = value
    .replace(/-/g, '+')
    .replace(/_/g, '/')
    .padEnd(Math.ceil(value.length / 4) * 4, '=');
  const binary = window.atob(padded);
  const output = new Uint8Array(new ArrayBuffer(binary.length));
  for (let index = 0; index < binary.length; index += 1) output[index] = binary.charCodeAt(index);
  return output;
};
interface ReaderSettingsPageProps {
  koboEnabled?: boolean;
  embedded?: boolean;
  showNotifications?: boolean;
}

export const ReaderSettingsPage = ({
  koboEnabled = false,
  embedded = false,
  showNotifications = true,
}: ReaderSettingsPageProps) => {
  const { language, t } = useLanguage();
  const text = (nl: string, en: string) => (language === 'nl' ? nl : en);
  const pushLabels: Record<string, string> = {
    'monitor.discovery': t('reader.eventMonitor'),
    'request.status': t('reader.eventRequest'),
    'book.available': t('reader.eventAvailable'),
    'request.error': t('reader.eventRequestError'),
    'metadata_report.status': t('reader.eventMetadata'),
    'backup.error': t('reader.eventBackupError'),
  };
  const [code, setCode] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [subscriptions, setSubscriptions] = useState<V1PushSubscription[]>([]);
  const [rules, setRules] = useState<V1PushRule[]>([]);
  const [patcher, setPatcher] = useState<V1PatcherManifest | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [manualEndpoint, setManualEndpoint] = useState<{ tokenId: number; value: string } | null>(
    null,
  );
  const [isIssuingManualToken, setIsIssuingManualToken] = useState(false);
  const [isRevokingManualToken, setIsRevokingManualToken] = useState(false);
  const manualEndpointActionLabel = isIssuingManualToken
    ? t('common.loading')
    : text('Genereer persoonlijke endpoint', 'Generate personal endpoint');
  const load = useCallback(async () => {
    try {
      const [subscriptionPage, rulePage, patcherResult] = await Promise.allSettled([
        showNotifications ? v1Api.pushSubscriptions() : Promise.resolve({ items: [] }),
        showNotifications ? v1Api.pushRules() : Promise.resolve({ items: [] }),
        koboEnabled ? v1Api.patcherManifest() : Promise.resolve(null),
      ]);
      if (subscriptionPage.status === 'fulfilled') setSubscriptions(subscriptionPage.value.items);
      if (rulePage.status === 'fulfilled') setRules(rulePage.value.items);
      if (patcherResult.status === 'fulfilled') setPatcher(patcherResult.value);
      else if (koboEnabled) setPatcher({ available: false, protocol_version: 1 });
    } catch {
      /* Push is optional and may not be configured. */
    }
  }, [koboEnabled, showNotifications]);
  useDependencyEffect(() => {
    void load();
  }, [load]);
  const generateCode = async () => {
    try {
      const result = await v1Api.createKoboPairingCode();
      setCode(result.code);
      setExpiresAt(result.expires_at);
      setMessage(t('reader.pairingCreated'));
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : t('reader.pairingFailed'));
    }
  };
  const generateManualEndpoint = async () => {
    setIsIssuingManualToken(true);
    try {
      const issued = await v1Api.issueKoboToken();
      const endpoint = issued.api_endpoint ?? issued.sync_url.replace(/\/v1\/library\/sync$/, '');
      setManualEndpoint({ tokenId: issued.token_id, value: absoluteUrl(endpoint) });
      setMessage(t('reader.pairingCreated'));
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : t('reader.pairingFailed'));
    } finally {
      setIsIssuingManualToken(false);
    }
  };
  const revokeManualEndpoint = async () => {
    if (!manualEndpoint) return;
    setIsRevokingManualToken(true);
    try {
      await v1Api.revokeKoboToken(manualEndpoint.tokenId);
      setManualEndpoint(null);
      setMessage(t('koboPanel.revokedToast'));
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : t('koboPanel.revokeFailed'));
    } finally {
      setIsRevokingManualToken(false);
    }
  };
  const enablePush = async () => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      setMessage(t('reader.pushUnsupported'));
      return;
    }
    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        setMessage(t('reader.pushDenied'));
        return;
      }
      const vapid = await v1Api.vapidKey();
      if (!vapid.configured || !vapid.public_key) {
        setMessage(t('reader.pushUnconfigured'));
        return;
      }
      const registration = await navigator.serviceWorker.ready;
      const existing = await registration.pushManager.getSubscription();
      const subscription =
        existing ??
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: decodeVapidKey(vapid.public_key),
        }));
      await v1Api.savePushSubscription(subscription.toJSON(), navigator.userAgent.slice(0, 100));
      await load();
      setMessage(t('reader.pushEnabled'));
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : t('reader.pushFailed'));
    }
  };
  const savePushRule = async (rule: V1PushRule, enabled = rule.enabled) => {
    try {
      await v1Api.setPushRule(rule.event_type, enabled, rule.filters ?? {});
      await load();
      setMessage(t('reader.ruleSaved'));
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : t('reader.ruleSaveFailed'));
    }
  };
  return (
    <section className={embedded ? '' : 'max-w-3xl pb-16'}>
      {!embedded && (
        <div className="mb-7">
          <p className="text-xs font-semibold tracking-widest text-violet-600 uppercase dark:text-violet-300">
            {t('reader.eyebrow')}
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">Kobo</h1>
          <p className="mt-2 text-sm opacity-65">{t('reader.subtitle')}</p>
        </div>
      )}
      {message && (
        <div className="mb-5 rounded-lg border border-(--border-muted) bg-(--bg-soft) px-4 py-3 text-sm">
          {message}
        </div>
      )}
      {koboEnabled && (
        <section className="bookflow-panel rounded-2xl p-5">
          <h2 className="font-semibold">{t('reader.patcherTitle')}</h2>
          <p className="mt-2 text-sm leading-6 opacity-65">{t('reader.patcherHelp')}</p>
          <div className="mt-4 flex flex-wrap gap-3">
            {patcher?.available ? (
              <a
                href={v1Api.patcherDownloadUrl()}
                className="rounded-md bg-violet-700 px-3 py-2 text-sm font-medium text-white"
              >
                {t('reader.downloadPatcher')}
              </a>
            ) : (
              <span className="rounded-md border border-amber-500/40 px-3 py-2 text-sm text-amber-700">
                {t('reader.patcherUnavailable')}
              </span>
            )}
            <button
              type="button"
              className="rounded-md border border-(--border-muted) px-3 py-2 text-sm font-medium"
              onClick={() => void generateCode()}
            >
              {t('reader.generateCode')}
            </button>
          </div>
          {code && (
            <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
              <p className="text-sm font-medium">{t('reader.oneTimeCode')}</p>
              <div className="mt-2 flex gap-2">
                <code className="min-w-0 flex-1 overflow-x-auto rounded bg-(--bg) px-3 py-2 text-sm">
                  {code}
                </code>
                <button
                  type="button"
                  className="rounded border border-(--border-muted) px-3 text-sm"
                  onClick={() => void copy(code)}
                >
                  {t('reader.copy')}
                </button>
              </div>
              <p className="mt-2 text-xs opacity-65">
                {t('reader.codeValidUntil', {
                  expiresAt: expiresAt ? new Date(expiresAt).toLocaleString() : t('reader.soon'),
                })}
              </p>
            </div>
          )}
          {patcher?.available && (
            <p className="mt-3 text-xs opacity-65">
              {t('reader.version', { version: patcher.protocol_version })}
            </p>
          )}
          <p className="mt-4 text-xs opacity-60">{t('reader.patcherNote')}</p>

          <section className="mt-6 border-t border-(--border-muted) pt-5">
            <h3 className="font-medium">{t('reader.manualConfiguration')}</h3>
            <p className="mt-2 text-sm opacity-65">
              {t('reader.manualConfigurationHelp', {
                suffix: patcher?.manual_endpoint_suffix ?? '/api/kobo/&lt;persoonlijk-token&gt;',
              })}
            </p>
            <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm leading-6">
              <li>
                {language === 'nl'
                  ? 'Sluit je Kobo met USB aan en maak eerst een reservekopie van het configuratiebestand.'
                  : 'Connect your Kobo over USB and first make a backup of its configuration file.'}
              </li>
              <li>
                <code className="rounded bg-(--bg-soft) px-1">.kobo/Kobo/Kobo eReader.conf</code>{' '}
                {language === 'nl' ? 'openen in een teksteditor.' : 'open it in a text editor.'}
              </li>
              <li>
                {language === 'nl' ? 'Zoek of maak de sectie ' : 'Find or create the section '}
                <code className="rounded bg-(--bg-soft) px-1">[OneStoreServices]</code>{' '}
                {language === 'nl'
                  ? 'en vervang of voeg daar de regel '
                  : 'and replace or add the line '}
                <code className="rounded bg-(--bg-soft) px-1">
                  api_endpoint=&lt;
                  {language === 'nl' ? 'jouw persoonlijke URL' : 'your personal URL'}&gt;
                </code>{' '}
                {language === 'nl' ? 'toe.' : 'there.'}
              </li>
              <li>
                {language === 'nl'
                  ? 'Sla het bestand op en werp de Kobo veilig uit.'
                  : 'Save the file and safely eject the Kobo.'}
              </li>
              <li>
                {language === 'nl'
                  ? 'Start de Kobo opnieuw op en kies daarna Synchroniseren.'
                  : 'Restart the Kobo, then choose Sync.'}
              </li>
              <li>
                {language === 'nl'
                  ? 'Herstel de reservekopie, of zet api_endpoint=https://storeapi.kobo.com, om de officiële Kobo Store/OverDrive-sync terug te zetten.'
                  : 'Restore the backup, or set api_endpoint=https://storeapi.kobo.com, to return to official Kobo Store/OverDrive sync.'}
              </li>
            </ol>
            <div className="mt-4 flex flex-wrap gap-3">
              {!manualEndpoint ? (
                <button
                  type="button"
                  onClick={() => void generateManualEndpoint()}
                  disabled={isIssuingManualToken}
                  className="rounded-md border border-(--border-muted) px-3 py-2 text-sm font-medium disabled:opacity-60"
                >
                  {manualEndpointActionLabel}
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => void copy(manualEndpoint.value)}
                    className="rounded-md border border-(--border-muted) px-3 py-2 text-sm font-medium"
                  >
                    {t('reader.copy')}
                  </button>
                  <button
                    type="button"
                    onClick={() => void revokeManualEndpoint()}
                    disabled={isRevokingManualToken}
                    className="rounded-md border border-red-500/30 px-3 py-2 text-sm font-medium text-red-600 disabled:opacity-60"
                  >
                    {isRevokingManualToken ? t('koboPanel.revoking') : t('koboPanel.revoke')}
                  </button>
                </>
              )}
            </div>
            {manualEndpoint && (
              <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
                <p className="text-sm font-medium">
                  {language === 'nl'
                    ? 'Je persoonlijke endpoint (wordt slechts eenmaal getoond)'
                    : 'Your personal endpoint (shown only once)'}
                </p>
                <code className="mt-2 block overflow-x-auto rounded bg-(--bg) px-3 py-2 text-sm">
                  api_endpoint={manualEndpoint.value}
                </code>
                <p className="mt-2 text-xs opacity-70">
                  {language === 'nl'
                    ? 'Deze URL is een geheim: deel hem niet. Intrekken maakt hem direct ongeldig.'
                    : 'This URL is a secret: do not share it. Revoking it invalidates it immediately.'}
                </p>
                {new URL(manualEndpoint.value).protocol !== 'https:' && (
                  <p className="mt-2 text-xs font-medium text-amber-800 dark:text-amber-200">
                    {language === 'nl'
                      ? 'Kobo-sync in productie vereist HTTPS. Gebruik een reverse proxy met een geldig certificaat voordat je dit buiten je lokale netwerk gebruikt.'
                      : 'Production Kobo sync requires HTTPS. Use a reverse proxy with a valid certificate before using this outside your local network.'}
                  </p>
                )}
              </div>
            )}
          </section>
        </section>
      )}
      {showNotifications && (
        <section className={`bookflow-panel rounded-2xl p-5 ${koboEnabled ? 'mt-6' : ''}`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold">{t('reader.webPush')}</h2>
              <p className="mt-2 text-sm opacity-65">{t('reader.webPushHelp')}</p>
            </div>
            <button
              type="button"
              className="rounded-md border border-(--border-muted) px-3 py-2 text-sm font-medium"
              onClick={() => void enablePush()}
            >
              {t('reader.enablePush')}
            </button>
          </div>
          {subscriptions.length ? (
            <ul className="mt-4 divide-y divide-(--border-muted)">
              {subscriptions.map((subscription) => (
                <li
                  key={subscription.id}
                  className="flex items-center justify-between gap-3 py-3 text-sm"
                >
                  <span>{subscription.device_label || t('reader.browserDevice')}</span>
                  <button
                    className="text-rose-700"
                    type="button"
                    onClick={() => void v1Api.deletePushSubscription(subscription.id).then(load)}
                  >
                    {t('common.delete')}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-4 text-sm opacity-65">{t('reader.noDevices')}</p>
          )}
          <div className="mt-5 border-t border-(--border-muted) pt-4">
            <h3 className="text-sm font-medium">{t('reader.notificationTypes')}</h3>
            <p className="mt-1 text-sm opacity-65">{t('reader.notificationTypesHelp')}</p>
            <div className="mt-2 space-y-2">
              {rules.map((rule) => (
                <label
                  key={rule.event_type}
                  className="flex items-center justify-between gap-4 text-sm"
                >
                  <span>{pushLabels[rule.event_type] ?? rule.event_type}</span>
                  <span className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      aria-label={pushLabels[rule.event_type] ?? rule.event_type}
                      checked={rule.enabled}
                      onChange={(event) => void savePushRule(rule, event.target.checked)}
                    />
                  </span>
                </label>
              ))}
            </div>
            <button
              type="button"
              className="mt-4 rounded border border-(--border-muted) px-3 py-1.5 text-sm"
              onClick={() =>
                void v1Api
                  .testPush()
                  .then((result) => setMessage(t('reader.testSent', { count: result.sent })))
                  .catch((caught: unknown) =>
                    setMessage(caught instanceof Error ? caught.message : t('reader.testFailed')),
                  )
              }
            >
              {t('reader.sendTest')}
            </button>
          </div>
        </section>
      )}
    </section>
  );
};
