import { useNavigate } from 'react-router-dom';

import { SettingsModal } from '../components/settings';

interface AdminSettingsPageProps {
  authMode: string;
  onShowToast: (message: string, type: 'success' | 'error' | 'info') => void;
  onSettingsSaved: () => void;
  onRefreshAuth: () => Promise<void>;
}

export const AdminSettingsPage = ({
  authMode,
  onShowToast,
  onSettingsSaved,
  onRefreshAuth,
}: AdminSettingsPageProps) => {
  const navigate = useNavigate();
  return (
    <SettingsModal
      isOpen
      presentation="page"
      authMode={authMode}
      onClose={() => {
        void navigate('/');
      }}
      onShowToast={onShowToast}
      onSettingsSaved={onSettingsSaved}
      onRefreshAuth={onRefreshAuth}
    />
  );
};
