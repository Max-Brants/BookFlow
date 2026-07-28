import { useMountEffect } from '../../../hooks/useMountEffect';
import type { AdminUser } from '../../../services/api';
import { canCreateLocalUsersForAuthMode } from './types';
import { UserListView } from './UserListView';
import { useUserForm } from './useUserForm';
import { useUserMutations } from './useUserMutations';
import { useUsersFetch } from './useUsersFetch';
import { useUsersPanelState } from './useUsersPanelState';

interface UsersManagementPanelProps {
  authMode: string;
  onShowToast?: (message: string, type: 'success' | 'error' | 'info') => void;
  onRefreshAuth?: () => Promise<void>;
}

export const UsersManagementPanel = ({
  authMode,
  onShowToast,
  onRefreshAuth,
}: UsersManagementPanelProps) => {
  const navigate = useNavigate();
  const { route, openCreate, openEdit, backToList } = useUsersPanelState();
  const { users, loading, loadError, fetchUsers } = useUsersFetch({ onShowToast });
  const form = useUserForm();
  const mutations = useUserMutations({
    onShowToast,
    fetchUsers,
    createForm: form.createForm,
    resetCreateForm: form.resetCreateForm,
    editingUser: form.editingUser,
    editPassword: form.editPassword,
    editPasswordConfirm: form.editPasswordConfirm,
    onEditSaveSuccess: form.clearEditState,
  });

  useMountEffect(() => {
    void fetchUsers();
  });

  const startEditing = (user: AdminUser) => {
    form.beginEditing(user);
    openEdit(user.id);
  };

  const finishEdit = async () => {
    if (await mutations.saveEditedUser()) {
      backToList();
    }
  };

  const finishCreate = async () => {
    if (await mutations.createUser()) {
      void onRefreshAuth?.();
      backToList();
    }
  };

  return (
    <UserListView
      authMode={authMode || 'none'}
      users={users}
      loadingUsers={loading}
      loadError={loadError}
      onRetryLoadUsers={() => void fetchUsers({ force: true })}
      needsLocalAdmin={
        !users.some((user) => user.role === 'admin' && user.auth_source === 'builtin')
      }
      onCreate={openCreate}
      showCreateForm={route.kind === 'create' && canCreateLocalUsersForAuthMode(authMode || 'none')}
      createForm={form.createForm}
      onCreateFormChange={form.setCreateForm}
      creating={mutations.creating}
      isFirstUser={users.length === 0}
      onCreateSubmit={() => void finishCreate()}
      onCancelCreate={backToList}
      showEditForm={route.kind === 'edit'}
      activeEditUserId={route.kind === 'edit' ? route.userId : null}
      editingUser={form.editingUser}
      onEditingUserChange={form.setEditingUser}
      onEditSave={() => void finishEdit()}
      saving={mutations.saving}
      onCancelEdit={() => {
        form.clearEditState();
        backToList();
      }}
      editPassword={form.editPassword}
      onEditPasswordChange={form.setEditPassword}
      editPasswordConfirm={form.editPasswordConfirm}
      onEditPasswordConfirmChange={form.setEditPasswordConfirm}
      onOpenUser={(user) => {
        void navigate(`/admin/users/${user.id}`);
      }}
      onEdit={startEditing}
      onDelete={mutations.deleteUser}
      deletingUserId={mutations.deletingUserId}
      onSyncCwa={mutations.syncCwaUsers}
      syncingCwa={mutations.syncingCwa}
    />
  );
};
import { useNavigate } from 'react-router-dom';
