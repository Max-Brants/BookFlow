import { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { UserAuditPanel, type AuditTab } from '../components/settings/users/UserAuditPanel';
import { useLanguage } from '../contexts/LanguageContext';
import { useDependencyEffect } from '../hooks/useMountEffect';
import { getAdminUser, type AdminUser } from '../services/api';

export const AdminUserDetailPage = () => {
  const { userId, section } = useParams();
  const navigate = useNavigate();
  const { t } = useLanguage();
  const normalizedUserId = Number(userId);
  const [user, setUser] = useState<AdminUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const sectionTabs: Record<string, AuditTab> = {
    profile: 'profile',
    history: 'history',
    downloads: 'downloads',
    'ip-addresses': 'ips',
    logins: 'logins',
    kobo: 'kobo',
  };
  const tabPaths: Record<AuditTab, string> = {
    profile: '',
    history: 'history',
    downloads: 'downloads',
    ips: 'ip-addresses',
    logins: 'logins',
    kobo: 'kobo',
  };
  const activeTab = section ? (sectionTabs[section] ?? 'profile') : 'profile';

  const loadUser = useCallback(async () => {
    if (!Number.isInteger(normalizedUserId) || normalizedUserId <= 0) {
      setError(t('admin.userNotFound'));
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setUser(await getAdminUser(normalizedUserId));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : t('admin.userLoadFailed'));
    } finally {
      setLoading(false);
    }
  }, [normalizedUserId, t]);

  useDependencyEffect(() => {
    void loadUser();
  }, [loadUser]);

  if (loading) {
    return <p className="py-10 text-center text-sm opacity-60">{t('admin.userLoading')}</p>;
  }

  if (error || !user) {
    return (
      <section className="space-y-4">
        <Link to="/admin/users" className="text-sm text-sky-600 hover:underline">
          ← {t('admin.backToUsers')}
        </Link>
        <p className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-700 dark:text-red-300">
          {error || t('admin.userNotFound')}
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <Link
        to="/admin/users"
        className="inline-flex items-center gap-2 text-sm text-sky-600 hover:underline"
      >
        ← {t('admin.backToUsers')}
      </Link>

      <header className="flex flex-wrap items-center gap-4">
        <div
          className={`flex h-16 w-16 items-center justify-center rounded-2xl text-2xl font-semibold ${
            user.role === 'admin'
              ? 'bg-sky-500/20 text-sky-700 dark:text-sky-300'
              : 'bg-zinc-500/15'
          }`}
        >
          {user.username.charAt(0).toUpperCase()}
        </div>
        <div>
          <p className="text-xs font-semibold tracking-[0.18em] text-sky-600 uppercase">
            {t('admin.userProfileEyebrow')}
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">
            {user.display_name || user.username}
          </h1>
          {user.display_name && <p className="mt-1 text-sm opacity-60">@{user.username}</p>}
        </div>
      </header>

      <div className="rounded-2xl border border-(--border-muted) bg-(--bg) p-4 shadow-sm sm:p-6">
        <UserAuditPanel
          userId={user.id}
          user={user}
          activeTab={activeTab}
          onTabChange={(nextTab) => {
            const suffix = tabPaths[nextTab];
            void navigate(`/admin/users/${user.id}${suffix ? `/${suffix}` : ''}`);
          }}
        />
      </div>
    </section>
  );
};
