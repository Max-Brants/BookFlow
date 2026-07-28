import type { UiLanguage } from '../../i18n/translations';
import type { SettingsField, SettingsGroup, SettingsTab } from '../../types/settings';

type LocalizedText = { en: string; nl: string };

const TAB_NAMES: Record<string, LocalizedText> = {
  general: { en: 'General', nl: 'Algemeen' },
  discovery: { en: 'Release discovery', nl: 'Releases zoeken' },
  downloads: { en: 'Downloads', nl: 'Downloads' },
  security: { en: 'Security', nl: 'Beveiliging' },
  users: { en: 'Users', nl: 'Gebruikers' },
  notifications: { en: 'Notifications', nl: 'Meldingen' },
  network: { en: 'Network', nl: 'Netwerk' },
  bestseller: { en: 'Trending books', nl: 'Trending boeken' },
  advanced: { en: 'Advanced', nl: 'Geavanceerd' },
  download_sources: { en: 'Download sources', nl: 'Downloadbronnen' },
  cloudflare_bypass: { en: 'Cloudflare bypass', nl: 'Cloudflare-omzeiling' },
  mirrors: { en: 'Mirrors', nl: 'Mirrors' },
  prowlarr_clients: { en: 'Download clients', nl: 'Downloadclients' },
  kobo: { en: 'Kobo', nl: 'Kobo' },
};

const GROUP_NAMES: Record<string, LocalizedText> = {
  direct_download: { en: 'Direct download', nl: 'Direct downloaden' },
  metadata_providers: { en: 'Metadata providers', nl: 'Metadatabronnen' },
};

const SECTION_NAMES: Record<string, LocalizedText> = {
  'Release Sources': { en: 'Release sources', nl: 'Releasebronnen' },
  'Metadata Providers': { en: 'Metadata providers', nl: 'Metadatabronnen' },
  'Download Clients': { en: 'Download clients', nl: 'Downloadclients' },
};

const FIELD_LABELS: Record<string, LocalizedText> = {
  DEFAULT_UI_LANGUAGE: { en: 'Default interface language', nl: 'Standaard interfacetaal' },
  _THEME: { en: 'Theme', nl: 'Thema' },
  DEFAULT_SEARCH_FILTERS: { en: 'Default search filters', nl: 'Standaard zoekfilters' },
  SUPPORTED_FORMATS: { en: 'Supported book formats', nl: 'Ondersteunde boekformaten' },
  BOOK_LANGUAGE: { en: 'Default book languages', nl: 'Standaard boektalen' },
  BESTSELLER_ENABLED: { en: 'Enable trending books', nl: 'Trending boeken inschakelen' },
  BESTSELLER_CHECK_INTERVAL_HOURS: {
    en: 'Check interval (hours)',
    nl: 'Controle-interval (uren)',
  },
};

const FIELD_DESCRIPTIONS: Record<string, LocalizedText> = {
  DEFAULT_UI_LANGUAGE: {
    en: 'Language assigned to new users. Existing users keep their personal preference.',
    nl: 'Taal die nieuwe gebruikers standaard krijgen. Bestaande gebruikers behouden hun persoonlijke voorkeur.',
  },
  _THEME: {
    en: 'Choose your preferred colour scheme.',
    nl: 'Kies het gewenste kleurenschema.',
  },
  SUPPORTED_FORMATS: {
    en: 'Book formats included in search results. ZIP and RAR archives are extracted automatically.',
    nl: 'Boekformaten die in zoekresultaten worden opgenomen. ZIP- en RAR-archieven worden automatisch uitgepakt.',
  },
  BOOK_LANGUAGE: {
    en: 'Default language filter for searches.',
    nl: 'Standaard taalfilter voor zoekopdrachten.',
  },
  BESTSELLER_ENABLED: {
    en: 'Automatically update the Dutch Bestseller 60 lists and show them under Trending.',
    nl: 'Werk de Nederlandse Bestseller 60-lijsten automatisch bij en toon ze onder Trending.',
  },
  BESTSELLER_CHECK_INTERVAL_HOURS: {
    en: 'How often BookFlow checks whether a new Bestseller 60 week is available.',
    nl: 'Hoe vaak BookFlow controleert of een nieuwe Bestseller 60-week beschikbaar is.',
  },
};

const textFor = (text: LocalizedText, language: UiLanguage): string => text[language];

export const localizeSettingsTabName = (
  tab: Pick<SettingsTab, 'name' | 'displayName'>,
  language: UiLanguage,
): string => textFor(TAB_NAMES[tab.name] ?? { en: tab.displayName, nl: tab.displayName }, language);

export const localizeSettingsGroupName = (
  group: Pick<SettingsGroup, 'name' | 'displayName'>,
  language: UiLanguage,
): string =>
  textFor(GROUP_NAMES[group.name] ?? { en: group.displayName, nl: group.displayName }, language);

export const localizeSettingsSection = (label: string, language: UiLanguage): string =>
  textFor(SECTION_NAMES[label] ?? { en: label, nl: label }, language);

export const localizeSettingsField = (
  field: SettingsField,
  language: UiLanguage,
): SettingsField => {
  if (field.type === 'HeadingField') {
    if (field.key === 'search_defaults_heading') {
      return {
        ...field,
        title: language === 'nl' ? 'Standaard zoekfilters' : 'Default search filters',
        description:
          language === 'nl'
            ? 'Standaardfilters voor zoekopdrachten. Deze kunnen via geavanceerd zoeken worden aangepast.'
            : 'Default filters applied to searches. These can be changed with advanced search.',
      };
    }
    return field;
  }

  const label = FIELD_LABELS[field.key]?.[language] ?? field.label;
  const description = FIELD_DESCRIPTIONS[field.key]?.[language] ?? field.description;
  if (field.type === 'SelectField' && field.key === '_THEME') {
    const themeLabels: Record<string, LocalizedText> = {
      light: { en: 'Light', nl: 'Licht' },
      dark: { en: 'Dark', nl: 'Donker' },
      auto: { en: 'Auto (system)', nl: 'Automatisch (systeem)' },
    };
    return {
      ...field,
      label,
      description,
      options: field.options.map((option) => ({
        ...option,
        label: themeLabels[option.value]?.[language] ?? option.label,
      })),
    };
  }
  if (field.type === 'MultiSelectField' && field.key === 'BOOK_LANGUAGE' && language === 'nl') {
    const commonLanguageNames: Record<string, string> = {
      en: 'Engels',
      nl: 'Nederlands',
      de: 'Duits',
      fr: 'Frans',
      es: 'Spaans',
      it: 'Italiaans',
      pt: 'Portugees',
      sv: 'Zweeds',
      da: 'Deens',
      no: 'Noors',
      fi: 'Fins',
      pl: 'Pools',
      cs: 'Tsjechisch',
      uk: 'Oekraïens',
      ru: 'Russisch',
      zh: 'Chinees',
      ja: 'Japans',
      ko: 'Koreaans',
      ar: 'Arabisch',
      tr: 'Turks',
    };
    return {
      ...field,
      label,
      description,
      options: field.options.map((option) => ({
        ...option,
        label: commonLanguageNames[option.value] ?? option.label,
      })),
    };
  }
  return { ...field, label, description };
};

export const localizeSettingsTab = (tab: SettingsTab, language: UiLanguage): SettingsTab => ({
  ...tab,
  displayName: localizeSettingsTabName(tab, language),
  fields: tab.fields.map((field) => localizeSettingsField(field, language)),
});
