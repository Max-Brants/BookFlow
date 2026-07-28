import { UsersManagementPanel } from '../users';
import type { CustomSettingsFieldRendererProps } from './types';

export const UsersManagementField = ({
  authMode,
  onShowToast,
  onRefreshAuth,
}: CustomSettingsFieldRendererProps) => {
  return (
    <UsersManagementPanel
      authMode={authMode || 'none'}
      onShowToast={onShowToast}
      onRefreshAuth={onRefreshAuth}
    />
  );
};
