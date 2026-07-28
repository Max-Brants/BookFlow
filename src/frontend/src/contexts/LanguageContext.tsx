import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import { useDependencyEffect } from '../hooks/useMountEffect';
import { translations, type TranslationKey, type UiLanguage } from '../i18n/translations';

const STORAGE_KEY = 'bookflow-language';

const detectLanguage = (): UiLanguage => {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === 'en' || stored === 'nl') return stored;
  } catch {
    // Storage is optional.
  }
  return window.navigator.language.toLowerCase().startsWith('nl') ? 'nl' : 'en';
};

interface LanguageContextValue {
  language: UiLanguage;
  setLanguage: (language: UiLanguage) => void;
  t: (key: TranslationKey, values?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

export const LanguageProvider = ({ children }: { children: ReactNode }) => {
  const [language, setLanguageState] = useState<UiLanguage>(detectLanguage);

  const setLanguage = useCallback((nextLanguage: UiLanguage) => {
    setLanguageState(nextLanguage);
  }, []);

  useDependencyEffect(() => {
    document.documentElement.lang = language;
    try {
      window.localStorage.setItem(STORAGE_KEY, language);
    } catch {
      // Storage is optional.
    }
  }, [language]);

  const t = useCallback(
    (key: TranslationKey, values: Record<string, string | number> = {}) =>
      Object.entries(values).reduce(
        (message, [name, value]) => message.replaceAll(`{${name}}`, String(value)),
        translations[language][key] ?? translations.en[key],
      ),
    [language],
  );

  const value = useMemo(() => ({ language, setLanguage, t }), [language, setLanguage, t]);
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
};

export const useLanguage = (): LanguageContextValue => {
  const context = useContext(LanguageContext);
  if (!context) throw new Error('useLanguage must be used within LanguageProvider');
  return context;
};
