import type { ReaderPreferences } from '../types';

const readerTheme = (value: string): ReaderPreferences['theme'] => {
  if (value === 'dark' || value === 'sepia') return value;
  return 'light';
};

const readerFlow = (value: string): ReaderPreferences['flow'] =>
  value === 'scrolled' ? 'scrolled' : 'paginated';

const readerSpread = (value: string): ReaderPreferences['spread'] =>
  value === 'double' ? 'double' : 'single';

interface ReaderSettingsPanelProps {
  preferences: ReaderPreferences;
  onChange: (next: ReaderPreferences) => void;
  onClose: () => void;
}

export const ReaderSettingsPanel = ({
  preferences,
  onChange,
  onClose,
}: ReaderSettingsPanelProps) => (
  <aside
    className="absolute top-14 right-3 z-30 w-72 rounded-lg border border-black/10 bg-white p-4 text-slate-900 shadow-xl dark:border-white/10 dark:bg-slate-900 dark:text-slate-100"
    aria-label="Reading settings"
  >
    <div className="mb-3 flex items-center justify-between">
      <h2 className="font-semibold">Display</h2>
      <button type="button" onClick={onClose} aria-label="Close settings">
        ×
      </button>
    </div>
    <label className="mb-3 block text-sm">
      Theme
      <select
        className="mt-1 block w-full rounded border p-1.5"
        value={preferences.theme}
        onChange={(event) => onChange({ ...preferences, theme: readerTheme(event.target.value) })}
      >
        <option value="light">Light</option>
        <option value="sepia">Sepia</option>
        <option value="dark">Dark</option>
      </select>
    </label>
    <label className="mb-3 block text-sm">
      Font size ({preferences.fontSize}%)
      <input
        className="mt-1 w-full"
        type="range"
        min="75"
        max="200"
        value={preferences.fontSize}
        onChange={(event) => onChange({ ...preferences, fontSize: Number(event.target.value) })}
      />
    </label>
    <label className="mb-3 block text-sm">
      Line height ({preferences.lineHeight.toFixed(1)})
      <input
        className="mt-1 w-full"
        type="range"
        min="1.1"
        max="2.5"
        step="0.1"
        value={preferences.lineHeight}
        onChange={(event) => onChange({ ...preferences, lineHeight: Number(event.target.value) })}
      />
    </label>
    <label className="mb-3 block text-sm">
      Layout
      <select
        className="mt-1 block w-full rounded border p-1.5"
        value={preferences.flow}
        onChange={(event) => onChange({ ...preferences, flow: readerFlow(event.target.value) })}
      >
        <option value="paginated">Pages</option>
        <option value="scrolled">Scroll</option>
      </select>
    </label>
    <label className="block text-sm">
      Page spread
      <select
        className="mt-1 block w-full rounded border p-1.5"
        value={preferences.spread}
        onChange={(event) => onChange({ ...preferences, spread: readerSpread(event.target.value) })}
      >
        <option value="single">Single page</option>
        <option value="double">Two pages</option>
      </select>
    </label>
  </aside>
);
