import { NavLink } from 'react-router-dom';

import { useLanguage } from '../contexts/LanguageContext';

const tabClassName = ({ isActive }: { isActive: boolean }) =>
  `shrink-0 rounded-full border px-3 py-1.5 text-sm font-medium transition ${
    isActive
      ? 'border-violet-500 bg-violet-600 text-white'
      : 'border-(--border-muted) bg-(--bg-soft) hover:border-violet-500/60'
  }`;

export const DiscoverNavigation = () => {
  const { t } = useLanguage();

  return (
    <nav
      className="scrollbar-hide mb-7 flex gap-2 overflow-x-auto pb-1"
      aria-label={t('nav.catalog')}
    >
      <NavLink to="/catalog" end className={tabClassName}>
        {t('catalog.books')}
      </NavLink>
      <NavLink to="/catalog/authors" className={tabClassName}>
        {t('catalog.browseAuthors')}
      </NavLink>
      <NavLink to="/catalog/series" className={tabClassName}>
        {t('catalog.browseSeries')}
      </NavLink>
    </nav>
  );
};
