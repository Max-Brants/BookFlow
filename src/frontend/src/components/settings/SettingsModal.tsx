import { useState, useCallback, useRef, useMemo, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { useLanguage } from '../../contexts/LanguageContext';
import { useBodyScrollLock } from '../../hooks/useBodyScrollLock';
import { useEscapeKey } from '../../hooks/useEscapeKey';
import { useMediaQuery } from '../../hooks/useMediaQuery';
import { useDependencyEffect, useMountEffect } from '../../hooks/useMountEffect';
import { useSettings } from '../../hooks/useSettings';
import { AdminOperationsPage } from '../../pages/AdminOperationsPage';
import { getSettingsTab } from '../../services/api';
import { SettingsContent } from './SettingsContent';
import { SettingsHeader } from './SettingsHeader';
import { localizeSettingsTab } from './settingsLocalization';
import { SettingsSidebar } from './SettingsSidebar';

interface SettingsModalProps {
  isOpen: boolean;
  authMode: string;
  onClose: () => void;
  presentation?: 'modal' | 'page';
  onShowToast?: (message: string, type: 'success' | 'error' | 'info') => void;
  onSettingsSaved?: () => void;
  onRefreshAuth?: () => Promise<void>;
}

function getStringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function getStringArrayValue(value: unknown): string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === 'string') ? value : [];
}

function getBooleanValue(value: unknown): boolean {
  return typeof value === 'boolean' ? value : false;
}

export const SettingsModal = ({
  isOpen,
  authMode,
  onClose,
  onShowToast,
  onSettingsSaved,
  onRefreshAuth,
  presentation = 'modal',
}: SettingsModalProps) => {
  const isMobile = useMediaQuery('(max-width: 767px)');
  const [isClosing, setIsClosing] = useState(false);
  const [sessionVersion, setSessionVersion] = useState(0);
  const mobileDetailStateRef = useRef<{
    isOpen: boolean;
    closeDetail: (() => void) | null;
  }>({
    isOpen: false,
    closeDetail: null,
  });

  const registerMobileDetailState = useCallback(
    (detailOpen: boolean, closeDetail: (() => void) | null) => {
      mobileDetailStateRef.current = { isOpen: detailOpen, closeDetail };
    },
    [],
  );

  const handleClose = useCallback(() => {
    setIsClosing(true);
    setTimeout(() => {
      onClose();
      setIsClosing(false);
      setSessionVersion((current) => current + 1);
    }, 150);
  }, [onClose]);

  const handleEscape = useCallback(() => {
    if (isMobile && mobileDetailStateRef.current.isOpen) {
      mobileDetailStateRef.current.closeDetail?.();
      return;
    }

    handleClose();
  }, [handleClose, isMobile]);

  useBodyScrollLock(isOpen && presentation === 'modal');
  useEscapeKey(isOpen && presentation === 'modal', handleEscape);

  if (!isOpen && !isClosing) return null;

  return (
    <SettingsModalSession
      key={sessionVersion}
      isOpen={isOpen}
      isClosing={isClosing}
      isMobile={isMobile}
      authMode={authMode}
      onClose={handleClose}
      onShowToast={onShowToast}
      onSettingsSaved={onSettingsSaved}
      onRefreshAuth={onRefreshAuth}
      onMobileDetailChange={registerMobileDetailState}
      presentation={presentation}
    />
  );
};

interface SettingsModalSessionProps {
  isOpen: boolean;
  isClosing: boolean;
  isMobile: boolean;
  authMode: string;
  onClose: () => void;
  onShowToast?: (message: string, type: 'success' | 'error' | 'info') => void;
  onSettingsSaved?: () => void;
  onRefreshAuth?: () => Promise<void>;
  onMobileDetailChange: (isOpen: boolean, closeDetail: (() => void) | null) => void;
  presentation: 'modal' | 'page';
}

interface SettingsModalTabSyncProps {
  selectedTab: string;
  setSecurityAccessError: (message: string | null) => void;
  failedToLoadSecurity: string;
}

const SettingsModalTabSync = ({
  selectedTab,
  setSecurityAccessError,
  failedToLoadSecurity,
}: SettingsModalTabSyncProps) => {
  useMountEffect(() => {
    let cancelled = false;

    if (selectedTab !== 'security') {
      setSecurityAccessError(null);
    } else {
      void getSettingsTab('security')
        .then(() => {
          if (!cancelled) {
            setSecurityAccessError(null);
          }
        })
        .catch((err) => {
          if (cancelled) {
            return;
          }

          const message = err instanceof Error ? err.message : failedToLoadSecurity;
          if (message.toLowerCase().includes('admin access required')) {
            setSecurityAccessError(message);
            return;
          }

          setSecurityAccessError(null);
        });
    }

    return () => {
      cancelled = true;
    };
  });

  return null;
};

const SettingsModalSession = ({
  isOpen,
  isClosing,
  isMobile,
  authMode,
  onClose,
  onShowToast,
  onSettingsSaved,
  onRefreshAuth,
  onMobileDetailChange,
  presentation,
}: SettingsModalSessionProps) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { language, t } = useLanguage();
  const {
    tabs,
    groups,
    isLoading,
    error,
    selectedTab,
    setSelectedTab,
    values,
    updateValue,
    hasChanges,
    saveTab,
    executeAction,
    isSaving,
  } = useSettings();

  const isUniversalMode = true;

  const [showMobileDetail, setShowMobileDetail] = useState(false);
  const [securityAccessError, setSecurityAccessError] = useState<string | null>(null);

  useDependencyEffect(() => {
    const requestedTab = new URLSearchParams(location.search).get('tab');
    if (requestedTab === 'system-operations' || requestedTab === 'system_operations') {
      setSelectedTab('system_operations');
    }
  }, [location.search, setSelectedTab]);

  const handleClose = useCallback(() => {
    setShowMobileDetail(false);
    onMobileDetailChange(false, null);
    onClose();
  }, [onClose, onMobileDetailChange]);

  const handleBack = useCallback(() => {
    setShowMobileDetail(false);
    onMobileDetailChange(false, null);
  }, [onMobileDetailChange]);

  const handleSelectTab = useCallback(
    (tabName: string) => {
      setSelectedTab(tabName);
      if (isMobile) {
        setShowMobileDetail(true);
        onMobileDetailChange(true, handleBack);
      }
    },
    [handleBack, isMobile, onMobileDetailChange, setSelectedTab],
  );

  const handleSave = useCallback(async () => {
    if (!selectedTab) return;
    const result = await saveTab(selectedTab);
    if (result.success) {
      onShowToast?.(result.message, 'success');
      onSettingsSaved?.();
      if (result.requiresRestart) {
        setTimeout(() => {
          onShowToast?.(t('settings.restartRequired'), 'info');
        }, 500);
      }
    } else {
      onShowToast?.(result.message, 'error');
    }
  }, [selectedTab, saveTab, onShowToast, onSettingsSaved, t]);

  const handleAction = useCallback(
    async (actionKey: string) => {
      if (!selectedTab) {
        return { success: false, message: t('settings.noTabSelected') };
      }

      if (selectedTab === 'security' && actionKey === 'open_users_tab') {
        void navigate('/admin/users');
        return { success: true, message: t('settings.openingUsers') };
      }
      return executeAction(selectedTab, actionKey);
    },
    [executeAction, navigate, selectedTab, t],
  );

  const handleFieldChange = useCallback(
    (key: string, value: unknown) => {
      if (!selectedTab) return;
      updateValue(selectedTab, key, value);

      if (selectedTab === 'security') {
        const tabValues = values[selectedTab] || {};
        const currentScopes = getStringArrayValue(tabValues['OIDC_SCOPES']);

        if (key === 'OIDC_USE_ADMIN_GROUP') {
          const groupClaim = getStringValue(tabValues['OIDC_GROUP_CLAIM'], 'groups');
          if (value === true && !currentScopes.includes(groupClaim)) {
            updateValue(selectedTab, 'OIDC_SCOPES', [...currentScopes, groupClaim]);
          } else if (value === false && currentScopes.includes(groupClaim)) {
            updateValue(
              selectedTab,
              'OIDC_SCOPES',
              currentScopes.filter((s) => s !== groupClaim),
            );
          }
        }

        if (key === 'OIDC_GROUP_CLAIM' && typeof value === 'string') {
          const useAdminGroup = getBooleanValue(tabValues['OIDC_USE_ADMIN_GROUP']);
          if (useAdminGroup) {
            const oldClaim = getStringValue(tabValues['OIDC_GROUP_CLAIM'], 'groups');
            const newScopes = currentScopes.filter((s) => s !== oldClaim);
            if (value && !newScopes.includes(value)) {
              newScopes.push(value);
            }
            updateValue(selectedTab, 'OIDC_SCOPES', newScopes);
          }
        }
      }
    },
    [selectedTab, updateValue, values],
  );

  const currentTabHasChanges = useMemo(
    () => (selectedTab ? hasChanges(selectedTab) : false),
    [selectedTab, hasChanges],
  );

  if (!isOpen && !isClosing) return null;

  const settingsTabs = [
    ...tabs
      .filter((tab) => tab.name !== 'users')
      .map((tab) => {
        const localized = localizeSettingsTab(tab, language);
        if (localized.name !== 'bestseller') return localized;
        return Object.assign({}, localized, {
          fields: [
            ...localized.fields,
            {
              key: 'BESTSELLER_ADMIN_STATUS',
              label: '',
              type: 'CustomComponentField' as const,
              component: 'bestseller_admin_status',
              wrapInFieldWrapper: false,
            },
          ],
        });
      }),
    {
      name: 'system_operations',
      displayName: language === 'nl' ? 'Systeembeheer' : 'System operations',
      icon: 'settings',
      order: 10_000,
      fields: [],
    },
  ];
  const currentTab = settingsTabs.find((tab) => tab.name === selectedTab);
  const currentTabDisplayName = currentTab?.displayName || t('nav.settings');
  const selectedTabSyncKey = isOpen && selectedTab ? selectedTab : null;
  const tabSync = selectedTabSyncKey ? (
    <SettingsModalTabSync
      key={selectedTabSyncKey}
      selectedTab={selectedTabSyncKey}
      setSecurityAccessError={setSecurityAccessError}
      failedToLoadSecurity={t('settings.securityLoadFailed')}
    />
  ) : null;
  const selectedAuthMethod = values.security?.AUTH_METHOD;
  const usersAuthMode = typeof selectedAuthMethod === 'string' ? selectedAuthMethod : authMode;
  let standardTabContent: ReactNode = null;
  if (currentTab) {
    standardTabContent =
      selectedTab === 'security' && securityAccessError ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8">
          <p className="text-sm opacity-60">{securityAccessError}</p>
        </div>
      ) : (
        <SettingsContent
          tab={currentTab}
          values={values[currentTab.name] || {}}
          onChange={handleFieldChange}
          onSave={handleSave}
          onAction={handleAction}
          isSaving={isSaving}
          hasChanges={currentTabHasChanges}
          isUniversalMode={isUniversalMode}
          customFieldContext={{
            authMode: usersAuthMode,
            onShowToast,
            onRefreshAuth,
            onSettingsSaved,
          }}
        />
      );
  }
  const currentTabContent =
    selectedTab === 'system_operations' ? <AdminOperationsPage embedded /> : standardTabContent;

  if (isLoading) {
    if (presentation === 'page') {
      return (
        <div className="flex min-h-[55vh] items-center justify-center">
          {tabSync}
          <div className="flex items-center gap-3 text-sm text-(--text-muted)">
            <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24">
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
                fill="none"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            <span>{t('common.loading')}</span>
          </div>
        </div>
      );
    }
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        {tabSync}
        <button
          type="button"
          className="absolute inset-0 bg-black/60"
          style={{ willChange: 'opacity', contain: 'strict' }}
          onClick={handleClose}
          tabIndex={-1}
          aria-label={t('settings.close')}
        />
        <div
          className="relative rounded-xl bg-(--bg) p-8 shadow-2xl"
          style={{ background: 'var(--bg)' }}
        >
          <div className="flex items-center gap-3">
            <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24">
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
                fill="none"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            <span>{t('common.loading')}</span>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    if (presentation === 'page') {
      return (
        <div className="flex min-h-[55vh] items-center justify-center">
          {tabSync}
          <div className="max-w-md rounded-2xl border border-red-500/20 bg-red-500/5 p-6 text-center">
            <p className="text-sm text-red-300">{error}</p>
          </div>
        </div>
      );
    }
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        {tabSync}
        <button
          type="button"
          className="absolute inset-0 bg-black/60"
          style={{ willChange: 'opacity', contain: 'strict' }}
          onClick={handleClose}
          tabIndex={-1}
          aria-label={t('settings.close')}
        />
        <div
          className="relative max-w-md rounded-xl bg-(--bg) p-8 shadow-2xl"
          style={{ background: 'var(--bg)' }}
        >
          <div className="space-y-4 text-center">
            <div className="text-red-500">
              <svg
                className="mx-auto h-12 w-12"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
                />
              </svg>
            </div>
            <p className="text-sm">{error}</p>
            <button
              type="button"
              onClick={handleClose}
              className="rounded-lg border border-(--border-muted) bg-(--bg-soft) px-4 py-2 text-sm font-medium transition-colors hover:bg-(--hover-surface)"
            >
              {t('common.close')}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (isMobile && presentation === 'page') {
    return (
      <section className="overflow-hidden rounded-2xl border border-white/10 bg-(--bg) shadow-xl">
        {tabSync}
        {!showMobileDetail ? (
          <>
            <div className="border-b border-(--border-muted) px-5 py-5">
              <p className="text-xs font-semibold tracking-[0.16em] text-sky-400 uppercase">
                {language === 'nl' ? 'Beheer' : 'Administration'}
              </p>
              <h1 className="mt-1 text-2xl font-semibold">
                {language === 'nl' ? 'Beheerinstellingen' : 'Admin settings'}
              </h1>
              <p className="mt-1 text-sm text-(--text-muted)">
                {language === 'nl'
                  ? 'Kies een onderdeel om de configuratie te beheren.'
                  : 'Choose a section to manage its configuration.'}
              </p>
            </div>
            <SettingsSidebar
              tabs={settingsTabs}
              groups={groups}
              selectedTab={selectedTab}
              onSelectTab={handleSelectTab}
              mode="list"
            />
          </>
        ) : (
          <>
            <header className="flex items-center gap-3 border-b border-(--border-muted) px-4 py-3">
              <button
                type="button"
                onClick={handleBack}
                className="hover-action rounded-full p-2"
                aria-label={t('common.back')}
              >
                ←
              </button>
              <h1 className="text-lg font-semibold">{currentTabDisplayName}</h1>
            </header>
            {currentTabContent}
          </>
        )}
      </section>
    );
  }

  if (isMobile && presentation === 'modal') {
    return (
      <>
        {tabSync}
        <div
          className={`fixed inset-0 z-50 flex flex-col ${isClosing ? 'animate-fade-out' : 'animate-fade-in'}`}
          style={{ background: 'var(--bg)' }}
        >
          {!showMobileDetail ? (
            <>
              <SettingsHeader title={t('nav.settings')} onClose={handleClose} />
              <SettingsSidebar
                tabs={settingsTabs}
                groups={groups}
                selectedTab={selectedTab}
                onSelectTab={handleSelectTab}
                mode="list"
              />
            </>
          ) : (
            <>
              <SettingsHeader
                title={currentTabDisplayName}
                showBack
                onBack={handleBack}
                onClose={handleClose}
              />
              {currentTabContent}
            </>
          )}
        </div>
      </>
    );
  }

  if (presentation === 'page') {
    return (
      <section className="overflow-hidden rounded-2xl border border-white/10 bg-(--bg) shadow-xl">
        {tabSync}
        <div className="border-b border-(--border-muted) px-5 py-5 sm:px-6">
          <p className="text-xs font-semibold tracking-[0.16em] text-sky-400 uppercase">
            {language === 'nl' ? 'Beheer' : 'Administration'}
          </p>
          <h1 className="mt-1 text-2xl font-semibold">
            {language === 'nl' ? 'Beheerinstellingen' : 'Admin settings'}
          </h1>
          <p className="mt-1 text-sm text-(--text-muted)">
            {language === 'nl'
              ? 'Beheer BookFlow, integraties en automatische processen.'
              : 'Manage BookFlow, integrations and automated processes.'}
          </p>
        </div>
        <div className="flex min-h-[min(72vh,760px)]">
          <SettingsSidebar
            tabs={settingsTabs}
            groups={groups}
            selectedTab={selectedTab}
            onSelectTab={handleSelectTab}
            mode="sidebar"
          />
          {currentTabContent ?? (
            <div className="flex flex-1 items-center justify-center text-sm opacity-60">
              {t('settings.selectCategory')}
            </div>
          )}
        </div>
      </section>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {tabSync}
      <button
        type="button"
        className={`absolute inset-0 bg-black/60 transition-opacity duration-150 ${isClosing ? 'opacity-0' : 'opacity-100'}`}
        style={{ willChange: 'opacity', contain: 'strict' }}
        onClick={handleClose}
        tabIndex={-1}
        aria-label={t('settings.close')}
      />

      <div
        className={`relative flex h-[88vh] max-h-[820px] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-(--border-muted) shadow-2xl ${isClosing ? 'settings-modal-exit' : 'settings-modal-enter'}`}
        style={{ background: 'var(--bg)' }}
        role="dialog"
        aria-modal="true"
        aria-label={t('nav.settings')}
      >
        <SettingsHeader title={t('nav.settings')} onClose={handleClose} />

        <div className="flex min-h-0 flex-1">
          <SettingsSidebar
            tabs={settingsTabs}
            groups={groups}
            selectedTab={selectedTab}
            onSelectTab={handleSelectTab}
            mode="sidebar"
          />

          {currentTabContent ?? (
            <div className="flex flex-1 items-center justify-center text-sm opacity-60">
              {t('settings.selectCategory')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
