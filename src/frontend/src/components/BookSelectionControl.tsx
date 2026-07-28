import { useLanguage } from '../contexts/LanguageContext';

interface BookSelectionControlProps {
  active: boolean;
  inLibrary: boolean;
  selected: boolean;
  title: string;
  onToggle: () => void;
}

export const BookSelectionControl = ({
  active,
  inLibrary,
  selected,
  title,
  onToggle,
}: BookSelectionControlProps) => {
  const { t } = useLanguage();

  if (!active) {
    return inLibrary ? (
      <span className="pointer-events-none absolute top-2 right-2 z-20 rounded-full bg-emerald-600 px-2 py-1 text-[10px] font-semibold text-white shadow">
        {t('bulkLibrary.inLibrary')}
      </span>
    ) : null;
  }

  if (inLibrary) {
    return (
      <>
        <span className="absolute inset-0 z-10 cursor-not-allowed rounded-xl bg-black/10" />
        <span className="pointer-events-none absolute top-2 right-2 z-20 rounded-full bg-emerald-600 px-2 py-1 text-[10px] font-semibold text-white shadow">
          {t('bulkLibrary.inLibrary')}
        </span>
      </>
    );
  }

  return (
    <>
      <button
        type="button"
        aria-pressed={selected}
        aria-label={
          selected
            ? t('bulkLibrary.deselectBook', { title })
            : t('bulkLibrary.selectBook', { title })
        }
        onClick={onToggle}
        className={`absolute inset-0 z-10 rounded-xl transition focus-visible:ring-2 focus-visible:ring-violet-500 ${
          selected ? 'bg-violet-600/20 ring-2 ring-violet-500' : 'hover:bg-violet-600/10'
        }`}
      />
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute top-2 right-2 z-20 flex h-7 w-7 items-center justify-center rounded-full border-2 text-sm font-bold shadow ${
          selected
            ? 'border-violet-500 bg-violet-600 text-white'
            : 'border-white bg-black/55 text-white'
        }`}
      >
        {selected ? '✓' : ''}
      </span>
    </>
  );
};
