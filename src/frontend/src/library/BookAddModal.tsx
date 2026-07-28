import { useState } from 'react';

import { useLanguage } from '../contexts/LanguageContext';
import { searchMetadata } from '../services/api';
import type { Book } from '../types';

interface BookAddModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (book: Book) => Promise<void>;
}

export const BookAddModal = ({ isOpen, onClose, onSelect }: BookAddModalProps) => {
  const { t } = useLanguage();
  const [query, setQuery] = useState('');
  const [books, setBooks] = useState<Book[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const search = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    setIsSearching(true);
    setError(null);
    try {
      setBooks((await searchMetadata(query.trim(), 40, 'relevance', {}, 1, 'ebook')).books);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('bookAdd.searchFailed'));
    } finally {
      setIsSearching(false);
    }
  };

  const open = async (book: Book) => {
    setOpeningId(book.id);
    setError(null);
    try {
      await onSelect(book);
      onClose();
    } catch {
      setError(t('bookAdd.openFailed'));
    } finally {
      setOpeningId(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[max(4rem,env(safe-area-inset-top))]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-book-title"
    >
      <div
        className="w-full max-w-2xl rounded-xl bg-(--bg) p-5 shadow-2xl"
        style={{ borderColor: 'var(--border-muted)' }}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold tracking-widest text-violet-600 uppercase dark:text-violet-300">
              {t('library.eyebrow')}
            </p>
            <h2 id="add-book-title" className="mt-1 text-xl font-semibold">
              {t('bookAdd.title')}
            </h2>
          </div>
          <button
            type="button"
            className="hover-action rounded-full p-2"
            onClick={onClose}
            aria-label={t('bookAdd.close')}
          >
            &#215;
          </button>
        </div>
        <form className="mt-5 flex gap-2" onSubmit={(event) => void search(event)}>
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('bookAdd.search')}
            className="min-w-0 flex-1 rounded-md border border-(--border-muted) bg-transparent px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={isSearching}
            className="rounded-md bg-violet-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            {isSearching ? t('bookAdd.searching') : t('catalog.search')}
          </button>
        </form>
        {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
        <div
          className="mt-4 max-h-[55vh] divide-y overflow-y-auto"
          style={{ borderColor: 'var(--border-muted)' }}
        >
          {books.map((book) => (
            <button
              key={book.id}
              type="button"
              disabled={openingId === book.id}
              className="hover-action flex w-full items-center gap-3 rounded-lg px-2 py-3 text-left disabled:opacity-60"
              onClick={() => void open(book)}
            >
              {book.preview && (
                <img src={book.preview} alt="" className="h-14 w-10 rounded object-cover" />
              )}
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{book.title || t('library.untitled')}</p>
                <p className="truncate text-sm opacity-65">
                  {book.author || t('common.unknownAuthor')}
                  {book.year ? ` · ${book.year}` : ''}
                </p>
              </div>
              <span className="rounded-md border border-violet-500 px-3 py-1.5 text-sm font-semibold text-violet-700 dark:text-violet-300">
                {openingId === book.id ? t('bookAdd.opening') : t('bookAdd.view')}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
