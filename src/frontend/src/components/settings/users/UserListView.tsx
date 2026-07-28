import { Fragment, useState } from 'react';

import { useLanguage } from '../../../contexts/LanguageContext';
import type { AdminUser } from '../../../services/api';
import type { CreateUserFormState } from './types';
import { canCreateLocalUsersForAuthMode } from './types';
import {
  UserAccountCardContent,
  UserCreateCard,
  UserIdentityHeader,
  UserRoleControl,
} from './UserCard';

interface UserListViewProps {
  authMode: string;
  users: AdminUser[];
  loadingUsers: boolean;
  loadError: string | null;
  onRetryLoadUsers: () => void;
  needsLocalAdmin: boolean;
  onCreate: () => void;
  showCreateForm: boolean;
  createForm: CreateUserFormState;
  onCreateFormChange: (form: CreateUserFormState) => void;
  creating: boolean;
  isFirstUser: boolean;
  onCreateSubmit: () => void;
  onCancelCreate: () => void;
  showEditForm: boolean;
  activeEditUserId: number | null;
  editingUser: AdminUser | null;
  onEditingUserChange: (user: AdminUser) => void;
  onEditSave: () => void;
  saving: boolean;
  onCancelEdit: () => void;
  editPassword: string;
  onEditPasswordChange: (value: string) => void;
  editPasswordConfirm: string;
  onEditPasswordConfirmChange: (value: string) => void;
  onOpenUser: (user: AdminUser) => void;
  onEdit: (user: AdminUser) => void;
  onDelete: (userId: number) => Promise<boolean>;
  deletingUserId: number | null;
  onSyncCwa: () => Promise<void> | void;
  syncingCwa: boolean;
}

export const UserListView = ({
  authMode,
  users,
  loadingUsers,
  loadError,
  onRetryLoadUsers,
  needsLocalAdmin,
  onCreate,
  showCreateForm,
  createForm,
  onCreateFormChange,
  creating,
  isFirstUser,
  onCreateSubmit,
  onCancelCreate,
  showEditForm,
  activeEditUserId,
  editingUser,
  onEditingUserChange,
  onEditSave,
  saving,
  onCancelEdit,
  editPassword,
  onEditPasswordChange,
  editPasswordConfirm,
  onEditPasswordConfirmChange,
  onOpenUser,
  onEdit,
  onDelete,
  deletingUserId,
  onSyncCwa,
  syncingCwa,
}: UserListViewProps) => {
  const { t } = useLanguage();
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const canCreateLocalUsers = canCreateLocalUsersForAuthMode(authMode);
  const isCwaMode = (authMode || 'none').toLowerCase() === 'cwa';
  const normalizedSearchQuery = searchQuery.trim().toLocaleLowerCase();
  const filteredUsers = normalizedSearchQuery
    ? users.filter((user) =>
        [user.username, user.display_name, user.email, user.auth_source, user.role]
          .filter(Boolean)
          .some((value) => String(value).toLocaleLowerCase().includes(normalizedSearchQuery)),
      )
    : users;

  const handleDelete = async (userId: number) => {
    const ok = await onDelete(userId);
    if (ok) {
      setConfirmDelete(null);
    }
  };

  return (
    <div className="space-y-4">
      {(() => {
        if (loadingUsers && users.length === 0) {
          return (
            <div className="space-y-2 py-8 text-center">
              <p className="text-sm opacity-50">{t('admin.loadingUsers')}</p>
            </div>
          );
        }

        if (loadError && users.length === 0) {
          return (
            <div className="space-y-3 py-8 text-center">
              <p className="text-sm opacity-60">{loadError}</p>
              <button
                type="button"
                onClick={onRetryLoadUsers}
                className="rounded-lg border border-(--border-muted) bg-(--bg-soft) px-4 py-2 text-sm font-medium transition-colors hover:bg-(--hover-surface)"
              >
                {t('common.retry')}
              </button>
            </div>
          );
        }

        if (users.length === 0) {
          return (
            <div className="space-y-2 py-8 text-center">
              <p className="text-sm opacity-50">{t('admin.noUsers')}</p>
              <p className="text-xs opacity-40">{t('admin.noUsersHelp')}</p>
            </div>
          );
        }

        return (
          <div className="space-y-4">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="font-semibold">{t('admin.allUsers')}</h2>
                <p className="mt-1 text-xs opacity-60">
                  {t('admin.userCount', { count: users.length })}
                </p>
              </div>
              <label className="w-full sm:w-72">
                <span className="mb-1 block text-xs font-medium opacity-60">
                  {t('admin.searchUsers')}
                </span>
                <input
                  type="search"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder={t('admin.searchUsersPlaceholder')}
                  className="w-full rounded-lg border border-(--border-muted) bg-(--bg) px-3 py-2 text-sm outline-none focus:border-sky-500"
                />
              </label>
            </div>

            <div className="overflow-x-auto rounded-lg border border-(--border-muted)">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-(--bg-soft) text-xs">
                  <tr>
                    <th className="px-4 py-3 font-medium">{t('admin.userColumn')}</th>
                    <th className="px-4 py-3 font-medium">{t('admin.emailColumn')}</th>
                    <th className="px-4 py-3 font-medium">{t('admin.authColumn')}</th>
                    <th className="px-4 py-3 font-medium">{t('admin.roleColumn')}</th>
                    <th className="px-4 py-3 font-medium">{t('admin.statusColumn')}</th>
                    <th className="px-4 py-3 font-medium">{t('admin.createdColumn')}</th>
                    <th className="px-4 py-3 text-right font-medium">{t('admin.actionsColumn')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-(--border-muted)">
                  {filteredUsers.map((user) => {
                    const active = user.is_active;
                    const isEditingRow = showEditForm && activeEditUserId === user.id;
                    const hasLoadedEditUser = isEditingRow && editingUser?.id === user.id;
                    const editorPanelId = `user-editor-${user.id}`;
                    const toggleUserEditor = () => {
                      setConfirmDelete(null);
                      if (isEditingRow) {
                        onCancelEdit();
                        return;
                      }

                      onEdit(user);
                    };
                    return (
                      <Fragment key={user.id}>
                        <tr className={active ? 'hover:bg-(--hover-surface)' : 'opacity-60'}>
                          <td className="px-4 py-3">
                            <button
                              type="button"
                              onClick={() => onOpenUser(user)}
                              className="text-left hover:text-sky-600 hover:underline"
                            >
                              <UserIdentityHeader
                                user={user}
                                showAuthSource={false}
                                showInactiveState={false}
                              />
                            </button>
                          </td>
                          <td className="px-4 py-3 text-xs">{user.email || '-'}</td>
                          <td className="px-4 py-3 text-xs">{user.auth_source}</td>
                          <td className="px-4 py-3">
                            {hasLoadedEditUser && editingUser ? (
                              <UserRoleControl
                                user={editingUser}
                                onUserChange={onEditingUserChange}
                                tooltipPosition="bottom"
                              />
                            ) : (
                              <UserRoleControl user={user} />
                            )}
                          </td>
                          <td className="px-4 py-3 text-xs">
                            {active ? t('admin.activeStatus') : t('admin.inactiveStatus')}
                          </td>
                          <td className="px-4 py-3 text-xs whitespace-nowrap">
                            {new Date(
                              user.created_at.endsWith('Z')
                                ? user.created_at
                                : `${user.created_at}Z`,
                            ).toLocaleDateString()}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <button
                              type="button"
                              onClick={toggleUserEditor}
                              aria-expanded={isEditingRow}
                              aria-controls={editorPanelId}
                              className="rounded-lg border border-(--border-muted) bg-(--bg) px-3 py-1.5 text-xs font-medium transition-colors hover:bg-(--hover-surface)"
                            >
                              {isEditingRow ? t('common.cancel') : t('admin.editUser')}
                            </button>
                          </td>
                        </tr>

                        {isEditingRow && (
                          <tr>
                            <td colSpan={7} className="bg-(--bg) p-4">
                              <div id={editorPanelId}>
                                {hasLoadedEditUser && editingUser ? (
                                  <UserAccountCardContent
                                    user={editingUser}
                                    onUserChange={onEditingUserChange}
                                    onSave={onEditSave}
                                    saving={saving}
                                    onCancel={onCancelEdit}
                                    editPassword={editPassword}
                                    onEditPasswordChange={onEditPasswordChange}
                                    editPasswordConfirm={editPasswordConfirm}
                                    onEditPasswordConfirmChange={onEditPasswordConfirmChange}
                                    onDelete={() => setConfirmDelete(user.id)}
                                    onConfirmDelete={() => {
                                      void handleDelete(user.id);
                                    }}
                                    onCancelDelete={() => setConfirmDelete(null)}
                                    isDeletePending={confirmDelete === user.id}
                                    deleting={deletingUserId === user.id}
                                  />
                                ) : (
                                  <div className="text-sm opacity-60">
                                    {t('admin.loadingUserDetails')}
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {filteredUsers.length === 0 && (
              <p className="py-6 text-center text-sm opacity-60">{t('admin.noMatchingUsers')}</p>
            )}
          </div>
        );
      })()}

      {canCreateLocalUsers && (
        <div>
          {showCreateForm ? (
            <UserCreateCard
              form={createForm}
              onChange={onCreateFormChange}
              creating={creating}
              isFirstUser={isFirstUser}
              needsLocalAdmin={needsLocalAdmin}
              onSubmit={onCreateSubmit}
              onCancel={onCancelCreate}
            />
          ) : (
            <button
              type="button"
              onClick={onCreate}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-700"
            >
              {t('admin.createLocalUser')}
            </button>
          )}
        </div>
      )}

      {!canCreateLocalUsers && isCwaMode && (
        <div>
          <button
            type="button"
            onClick={() => {
              void onSyncCwa();
            }}
            disabled={syncingCwa}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {syncingCwa ? 'Syncing with CWA...' : 'Sync with CWA'}
          </button>
        </div>
      )}
    </div>
  );
};
