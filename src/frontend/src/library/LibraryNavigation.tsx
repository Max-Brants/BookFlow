import { NavLink } from 'react-router-dom';

import bookFlowMark from '../assets/bookflow-mark-white.png';
import { useLanguage } from '../contexts/LanguageContext';

interface LibraryNavigationProps {
  isOpen: boolean;
  onClose: () => void;
  isAdmin: boolean;
  koboEnabled?: boolean;
}

const NavGlyph = ({ children }: { children: string }) => (
  <span
    aria-hidden="true"
    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/5 text-base text-slate-300 transition-colors group-hover:bg-white/10 group-hover:text-white"
  >
    {children}
  </span>
);

const itemClassName = ({ isActive }: { isActive: boolean }) =>
  `group flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-sm font-medium transition-all ${
    isActive
      ? 'bg-white/10 text-white shadow-sm ring-1 ring-white/10'
      : 'text-slate-400 hover:bg-white/5 hover:text-white'
  }`;

export const LibraryNavigation = ({
  isOpen,
  onClose,
  isAdmin,
  koboEnabled = false,
}: LibraryNavigationProps) => {
  const { t } = useLanguage();
  return (
    <>
      <button
        type="button"
        aria-label={t('nav.close')}
        className={`fixed inset-0 z-35 bg-slate-950/70 backdrop-blur-sm transition-opacity lg:hidden ${
          isOpen ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
        onClick={onClose}
        tabIndex={-1}
      />
      <aside
        className={`bookflow-sidebar fixed top-0 bottom-0 left-0 z-40 flex w-64 flex-col border-r border-white/8 px-3 pb-4 text-white shadow-2xl transition-transform lg:translate-x-0 lg:shadow-none ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
        aria-label={t('nav.primary')}
      >
        <div className="flex h-20 items-center gap-3 px-2">
          <div className="bookflow-mark flex h-10 w-10 items-center justify-center rounded-xl shadow-lg">
            <img src={bookFlowMark} alt="" aria-hidden="true" className="h-8 w-8 object-contain" />
          </div>
          <div className="text-lg font-bold tracking-tight">BookFlow</div>
        </div>

        <nav className="scrollbar-hide flex-1 space-y-1 overflow-y-auto pt-3">
          <p className="px-3 pb-2 text-[10px] font-semibold tracking-[0.18em] text-slate-600 uppercase">
            {t('nav.discover')}
          </p>
          <NavLink to="/" end className={itemClassName} onClick={onClose}>
            <NavGlyph>⌂</NavGlyph>
            {t('nav.dashboard')}
          </NavLink>
          <NavLink to="/library" className={itemClassName} onClick={onClose}>
            <NavGlyph>▥</NavGlyph>
            {t('nav.library')}
          </NavLink>
          {koboEnabled && (
            <NavLink to="/kobo" className={itemClassName} onClick={onClose}>
              <NavGlyph>◈</NavGlyph>
              {t('nav.koboSync')}
            </NavLink>
          )}
          <NavLink to="/catalog" className={itemClassName} onClick={onClose}>
            <NavGlyph>◫</NavGlyph>
            {t('nav.catalog')}
          </NavLink>
          <NavLink to="/monitors" className={itemClassName} onClick={onClose}>
            <NavGlyph>◇</NavGlyph>
            {t('nav.following')}
          </NavLink>
          <div className="pt-6">
            <p className="px-3 pb-2 text-[10px] font-semibold tracking-[0.18em] text-slate-600 uppercase">
              {t('nav.manage')}
            </p>
            <NavLink to="/requests" className={itemClassName} onClick={onClose}>
              <NavGlyph>⇣</NavGlyph>
              {t('activity.requests')}
            </NavLink>
            {isAdmin && (
              <>
                <NavLink to="/admin/downloads" className={itemClassName} onClick={onClose}>
                  <NavGlyph>⇣</NavGlyph>
                  {t('nav.downloads')}
                </NavLink>
                <NavLink to="/admin/users" className={itemClassName} onClick={onClose}>
                  <NavGlyph>♟</NavGlyph>
                  {t('nav.users')}
                </NavLink>
              </>
            )}
          </div>
        </nav>

        <div className="space-y-1 border-t border-white/8 pt-3">
          <NavLink to="/settings" className={itemClassName} onClick={onClose}>
            <NavGlyph>♙</NavGlyph>
            {t('header.mySettings')}
          </NavLink>
          {isAdmin && (
            <>
              <NavLink to="/admin/settings" className={itemClassName} onClick={onClose}>
                <NavGlyph>⚙</NavGlyph>
                {t('header.adminSettings')}
              </NavLink>
              <NavLink to="/admin/settings/profiles" className={itemClassName} onClick={onClose}>
                <NavGlyph>≋</NavGlyph>
                {t('nav.releaseProfiles')}
              </NavLink>
            </>
          )}
        </div>
      </aside>
    </>
  );
};
