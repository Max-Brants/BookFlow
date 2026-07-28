import { useCallback, useState } from 'react';

import { CheckboxField, SelectField, TextField } from '../components/settings/fields';
import { KoboSettingsPanel } from '../components/settings/KoboSettingsPanel';
import { FieldWrapper } from '../components/settings/shared';
import { useLanguage } from '../contexts/LanguageContext';
import { useMountEffect } from '../hooks/useMountEffect';
import { getSelfSettings, testPersonalNotification, updateSelfSettings } from '../services/api';
import type { CheckboxFieldConfig, SelectFieldConfig, TextFieldConfig } from '../types/settings';
import { getStoredThemePreference, setThemePreference } from '../utils/themePreference';
import { ReaderSettingsPage } from './ReaderSettingsPage';

interface SelfSettingsPageProps {
  onShowToast?: (message: string, type: 'success' | 'error' | 'info') => void;
  onSettingsSaved?: () => void;
  onKoboEnabledChange?: (enabled: boolean) => void;
}

interface SelfSettingsForm {
  username: string;
  email: string;
  display_name: string;
  notifications_enabled: boolean;
  notification_destination: string;
  preferred_language: 'en' | 'nl';
}

const readOnlyField = (key: string, label: string, value: string): TextFieldConfig => ({
  type: 'TextField',
  key,
  label,
  value,
  disabled: true,
});

const textField = (
  key: string,
  label: string,
  value: string,
  description?: string,
): TextFieldConfig => ({
  type: 'TextField',
  key,
  label,
  value,
  description,
});

export const SelfSettingsPage = ({
  onShowToast,
  onSettingsSaved,
  onKoboEnabledChange,
}: SelfSettingsPageProps) => {
  const { language, setLanguage, t } = useLanguage();
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isTestingNotification, setIsTestingNotification] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [values, setValues] = useState<SelfSettingsForm>({
    username: '',
    email: '',
    display_name: '',
    notifications_enabled: false,
    notification_destination: '',
    preferred_language: language,
  });
  const [originalValues, setOriginalValues] = useState<SelfSettingsForm>(values);
  const [themeValue, setThemeValue] = useState(getStoredThemePreference());
  const [koboEnabled, setKoboEnabled] = useState(false);
  const [activeTab, setActiveTab] = useState<'account' | 'notifications' | 'kobo'>('account');
  const handleKoboEnabledChange = useCallback(
    (enabled: boolean) => {
      setKoboEnabled(enabled);
      onKoboEnabledChange?.(enabled);
    },
    [onKoboEnabledChange],
  );
  const notificationEnabledField: CheckboxFieldConfig = {
    type: 'CheckboxField',
    key: 'notifications_enabled',
    label: t('settings.enableNotifications'),
    description:
      language === 'nl'
        ? 'Gebruik Apprise als persoonlijk meldingskanaal.'
        : 'Use Apprise as a personal notification channel.',
    value: false,
  };
  const languageField: SelectFieldConfig = {
    type: 'SelectField',
    key: 'preferred_language',
    label: t('settings.language'),
    description: t('settings.languageHelp'),
    options: [
      { value: 'en', label: t('language.en') },
      { value: 'nl', label: t('language.nl') },
    ],
    value: values.preferred_language,
  };
  const themeField: SelectFieldConfig = {
    type: 'SelectField',
    key: '_THEME',
    label: t('settings.theme'),
    description: t('settings.themeHelp'),
    value: themeValue,
    options: [
      { value: 'light', label: t('settings.themeLight') },
      { value: 'dark', label: t('settings.themeDark') },
      { value: 'auto', label: t('settings.themeSystem') },
    ],
  };

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const settings = await getSelfSettings();
      const next: SelfSettingsForm = {
        username: settings.username,
        email: settings.email || '',
        display_name: settings.display_name || '',
        notifications_enabled: settings.notifications_enabled,
        notification_destination: settings.notification_destination || '',
        preferred_language: settings.preferred_language,
      };
      setValues(next);
      setOriginalValues(next);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t('settings.loadFailed'));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useMountEffect(() => {
    void load();
  });
  const hasChanges = JSON.stringify(values) !== JSON.stringify(originalValues);
  const update = (field: keyof typeof values, value: string | boolean) =>
    setValues((current) => ({ ...current, [field]: value }));
  const save = async () => {
    if (!hasChanges) return;
    setIsSaving(true);
    try {
      const saved = await updateSelfSettings({
        display_name: values.display_name || null,
        notifications_enabled: values.notifications_enabled,
        notification_transport: 'apprise',
        notification_destination: values.notification_destination || null,
        preferred_language: values.preferred_language,
      });
      setOriginalValues({
        ...values,
        display_name: saved.display_name || '',
        preferred_language: saved.preferred_language,
      });
      setLanguage(saved.preferred_language);
      onShowToast?.(t('settings.updated'), 'success');
      onSettingsSaved?.();
    } catch (saveError) {
      onShowToast?.(
        saveError instanceof Error ? saveError.message : t('settings.saveFailed'),
        'error',
      );
    } finally {
      setIsSaving(false);
    }
  };
  const testNotification = async () => {
    setIsTestingNotification(true);
    try {
      const result = await testPersonalNotification();
      onShowToast?.(result.message, result.success ? 'success' : 'error');
    } catch (testError) {
      onShowToast?.(
        testError instanceof Error ? testError.message : t('settings.testFailed'),
        'error',
      );
    } finally {
      setIsTestingNotification(false);
    }
  };

  return (
    <section className="mx-auto max-w-4xl pb-16">
      <header className="mb-7">
        <p className="text-xs font-semibold tracking-widest text-sky-600 uppercase">BookFlow</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">{t('settings.title')}</h1>
      </header>
      <nav
        className="scrollbar-hide mb-5 flex gap-2 overflow-x-auto"
        aria-label={t('settings.title')}
      >
        {(
          [
            ['account', t('settings.account')],
            ['notifications', t('settings.notifications')],
            ['kobo', 'Kobo'],
          ] as const
        ).map(([tab, label]) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            aria-current={activeTab === tab ? 'page' : undefined}
            className={`rounded-full border px-3 py-1.5 text-sm ${
              activeTab === tab
                ? 'border-sky-600 bg-sky-600 text-white'
                : 'border-(--border-muted) hover:bg-(--hover-surface)'
            }`}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="bookflow-panel rounded-2xl p-5 sm:p-8">
        <div className="space-y-5">
          {isLoading && <p className="text-sm opacity-60">{t('common.loading')}</p>}
          {!isLoading && error && (
            <div className="space-y-3">
              <p className="text-sm text-red-600">{error}</p>
              <button type="button" onClick={() => void load()} className="text-sm underline">
                {t('common.retry')}
              </button>
            </div>
          )}
          {!isLoading && !error && (
            <>
              {activeTab === 'account' && (
                <section className="space-y-4">
                  <h4 className="text-sm font-medium">{t('settings.account')}</h4>
                  <FieldWrapper
                    field={readOnlyField('username', t('settings.username'), values.username)}
                  >
                    <TextField
                      field={readOnlyField('username', t('settings.username'), values.username)}
                      value={values.username}
                      onChange={() => undefined}
                      disabled
                    />
                  </FieldWrapper>
                  <FieldWrapper field={readOnlyField('email', t('settings.email'), values.email)}>
                    <TextField
                      field={readOnlyField('email', t('settings.email'), values.email)}
                      value={values.email}
                      onChange={() => undefined}
                      disabled
                    />
                  </FieldWrapper>
                  <FieldWrapper
                    field={textField(
                      'display_name',
                      t('settings.displayName'),
                      values.display_name,
                    )}
                  >
                    <TextField
                      field={textField(
                        'display_name',
                        t('settings.displayName'),
                        values.display_name,
                      )}
                      value={values.display_name}
                      onChange={(value) => update('display_name', value)}
                    />
                  </FieldWrapper>
                  <section className="space-y-4 border-t border-(--border-muted) pt-5">
                    <FieldWrapper field={languageField}>
                      <SelectField
                        field={languageField}
                        value={values.preferred_language}
                        onChange={(value) =>
                          update('preferred_language', value === 'nl' ? 'nl' : 'en')
                        }
                      />
                    </FieldWrapper>
                    <FieldWrapper field={themeField}>
                      <SelectField
                        field={themeField}
                        value={themeValue}
                        onChange={(value) => {
                          setThemeValue(value);
                          setThemePreference(value);
                        }}
                      />
                    </FieldWrapper>
                  </section>
                </section>
              )}
              {activeTab === 'notifications' && (
                <section className="space-y-4">
                  <h4 className="text-sm font-medium">{t('settings.notifications')}</h4>
                  <p className="text-sm opacity-65">
                    {language === 'nl'
                      ? 'Kies één of beide kanalen. De meldingstypen hieronder gelden voor alle ingeschakelde kanalen.'
                      : 'Choose either or both channels. The notification types below apply to every enabled channel.'}
                  </p>
                  <div className="rounded-xl border border-(--border-muted) p-4">
                    <h5 className="mb-3 text-sm font-semibold">Apprise</h5>
                    <FieldWrapper field={notificationEnabledField}>
                      <CheckboxField
                        field={notificationEnabledField}
                        value={values.notifications_enabled}
                        onChange={(value) => update('notifications_enabled', value)}
                      />
                    </FieldWrapper>
                    <div className="mt-4">
                      <FieldWrapper
                        field={textField(
                          'notification_destination',
                          'Apprise URL',
                          values.notification_destination,
                        )}
                      >
                        <TextField
                          field={textField(
                            'notification_destination',
                            'Apprise URL',
                            values.notification_destination,
                          )}
                          value={values.notification_destination}
                          onChange={(value) => update('notification_destination', value)}
                        />
                      </FieldWrapper>
                    </div>
                    <button
                      type="button"
                      onClick={() => void testNotification()}
                      disabled={
                        !values.notifications_enabled || hasChanges || isTestingNotification
                      }
                      className="mt-4 rounded-lg border border-(--border-muted) px-3 py-2 text-sm disabled:opacity-60"
                    >
                      {isTestingNotification
                        ? t('settings.sendingTest')
                        : t('settings.testDestination')}
                    </button>
                  </div>
                  <ReaderSettingsPage embedded />
                </section>
              )}
              {activeTab === 'kobo' && (
                <section>
                  <KoboSettingsPanel
                    onShowToast={onShowToast}
                    onEnabledChange={handleKoboEnabledChange}
                  />
                </section>
              )}
              {activeTab === 'kobo' && koboEnabled && (
                <section className="border-t border-(--border-muted) pt-5">
                  <ReaderSettingsPage koboEnabled embedded showNotifications={false} />
                </section>
              )}
            </>
          )}
        </div>
        <footer className="mt-6 flex justify-end border-t border-(--border-muted) pt-5">
          <button
            type="button"
            onClick={() => void save()}
            disabled={!hasChanges || isSaving || isLoading}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-60"
          >
            {isSaving ? t('common.saving') : t('common.save')}
          </button>
        </footer>
      </div>
    </section>
  );
};
