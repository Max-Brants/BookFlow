import { UsersManagementPanel } from '../components/settings/users';
import { useLanguage } from '../contexts/LanguageContext';

interface AdminUsersPageProps {
  authMode: string;
  onShowToast: (message: string, type: 'success' | 'error' | 'info') => void;
  onRefreshAuth: () => Promise<void>;
}

export const AdminUsersPage = ({ authMode, onShowToast, onRefreshAuth }: AdminUsersPageProps) => {
  const { t } = useLanguage();

  return (
    <section className="space-y-6">
      <header>
        <p className="text-xs font-semibold tracking-[0.18em] text-sky-600 uppercase">
          {t('admin.usersEyebrow')}
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">{t('admin.usersTitle')}</h1>
        <p className="mt-2 max-w-3xl text-sm opacity-65">{t('admin.usersSubtitle')}</p>
      </header>

      <div className="rounded-2xl border border-(--border-muted) bg-(--bg) p-4 shadow-sm sm:p-6">
        <UsersManagementPanel
          authMode={authMode}
          onShowToast={onShowToast}
          onRefreshAuth={onRefreshAuth}
        />
      </div>
    </section>
  );
};
