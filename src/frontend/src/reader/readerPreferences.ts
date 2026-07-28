import { defaultReaderPreferences, type ReaderPreferences } from './types';

const PREFERENCES_KEY = 'bookflow-reader-preferences-v1';

const isTheme = (value: unknown): value is ReaderPreferences['theme'] =>
  value === 'light' || value === 'dark' || value === 'sepia';
const isFont = (value: unknown): value is ReaderPreferences['fontFamily'] =>
  value === 'serif' || value === 'sans-serif' || value === 'opendyslexic';
const isFlow = (value: unknown): value is ReaderPreferences['flow'] =>
  value === 'paginated' || value === 'scrolled';
const isSpread = (value: unknown): value is ReaderPreferences['spread'] =>
  value === 'single' || value === 'double';
const clamp = (value: unknown, minimum: number, maximum: number, fallback: number): number =>
  typeof value === 'number' && Number.isFinite(value)
    ? Math.max(minimum, Math.min(maximum, value))
    : fallback;

export const sanitizeReaderPreferences = (value: unknown): ReaderPreferences => {
  if (!value || typeof value !== 'object') return defaultReaderPreferences;
  const candidate = value as Partial<ReaderPreferences>;
  return {
    theme: isTheme(candidate.theme) ? candidate.theme : defaultReaderPreferences.theme,
    fontFamily: isFont(candidate.fontFamily)
      ? candidate.fontFamily
      : defaultReaderPreferences.fontFamily,
    fontSize: clamp(candidate.fontSize, 75, 200, defaultReaderPreferences.fontSize),
    lineHeight: clamp(candidate.lineHeight, 1.1, 2.5, defaultReaderPreferences.lineHeight),
    flow: isFlow(candidate.flow) ? candidate.flow : defaultReaderPreferences.flow,
    spread: isSpread(candidate.spread) ? candidate.spread : defaultReaderPreferences.spread,
  };
};

export const loadReaderPreferences = (): ReaderPreferences => {
  try {
    const stored = window.localStorage.getItem(PREFERENCES_KEY);
    return sanitizeReaderPreferences(stored ? JSON.parse(stored) : null);
  } catch {
    return defaultReaderPreferences;
  }
};

export const saveReaderPreferences = (preferences: ReaderPreferences): void => {
  try {
    window.localStorage.setItem(
      PREFERENCES_KEY,
      JSON.stringify(sanitizeReaderPreferences(preferences)),
    );
  } catch {
    // A private browser context can deny local storage. Reading remains usable.
  }
};
