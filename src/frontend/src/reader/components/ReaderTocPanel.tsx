import type { ReaderTocItem } from '../types';

interface ReaderTocPanelProps {
  items: ReaderTocItem[];
  onSelect: (item: ReaderTocItem) => void;
  onClose: () => void;
}

const TocItems = ({ items, onSelect }: Pick<ReaderTocPanelProps, 'items' | 'onSelect'>) => (
  <ul className="space-y-1">
    {items.map((item) => (
      <li key={item.id}>
        <button
          type="button"
          className="w-full rounded px-2 py-1 text-left text-sm hover:bg-black/10 dark:hover:bg-white/10"
          onClick={() => onSelect(item)}
        >
          {item.label}
        </button>
        {item.children && item.children.length > 0 && (
          <div className="ml-3 border-l border-black/10 pl-2 dark:border-white/10">
            <TocItems items={item.children} onSelect={onSelect} />
          </div>
        )}
      </li>
    ))}
  </ul>
);

export const ReaderTocPanel = ({ items, onSelect, onClose }: ReaderTocPanelProps) => (
  <aside
    className="absolute top-14 bottom-3 left-3 z-30 w-80 max-w-[calc(100vw-1.5rem)] overflow-y-auto rounded-lg border border-black/10 bg-white p-4 text-slate-900 shadow-xl dark:border-white/10 dark:bg-slate-900 dark:text-slate-100"
    aria-label="Table of contents"
  >
    <div className="mb-3 flex items-center justify-between">
      <h2 className="font-semibold">Contents</h2>
      <button type="button" onClick={onClose} aria-label="Close contents">
        ×
      </button>
    </div>
    {items.length === 0 ? (
      <p className="text-sm opacity-70">No table of contents available.</p>
    ) : (
      <TocItems items={items} onSelect={onSelect} />
    )}
  </aside>
);
