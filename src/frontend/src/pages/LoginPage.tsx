import bookFlowMark from '../assets/bookflow-mark-white.png';
import { LoginForm } from '../components/LoginForm';
import { useLanguage } from '../contexts/LanguageContext';
import type { LoginCredentials } from '../types';

interface LoginPageProps {
  onLogin: (credentials: LoginCredentials) => void;
  error: string | null;
  isLoading: boolean;
  authMode?: string;
  oidcButtonLabel?: string | null;
  hideLocalAuth?: boolean;
  oidcAutoRedirect?: boolean;
}

export const LoginPage = ({
  onLogin,
  error,
  isLoading,
  authMode,
  oidcButtonLabel,
  hideLocalAuth,
  oidcAutoRedirect,
}: LoginPageProps) => {
  const { t } = useLanguage();

  return (
    <div className="bookflow-hero flex min-h-screen items-center justify-center px-4 py-8 text-white">
      <div className="w-full max-w-md">
        <div
          className="rounded-3xl border border-white/10 bg-slate-950/55 p-7 shadow-2xl backdrop-blur-xl"
          style={{
            backgroundColor: 'var(--card-background)',
            borderColor: 'var(--border-color)',
            color: 'var(--text-color)',
          }}
        >
          <div className="mb-7 text-center">
            <div className="bookflow-mark mx-auto flex h-14 w-14 items-center justify-center rounded-2xl">
              <img
                src={bookFlowMark}
                alt=""
                aria-hidden="true"
                className="h-11 w-11 object-contain"
              />
            </div>
            <h1 className="mt-4 text-2xl font-bold tracking-tight">{t('login.welcome')}</h1>
            <p className="mt-2 text-sm text-slate-400">{t('login.subtitle')}</p>
          </div>
          <LoginForm
            onSubmit={onLogin}
            error={error}
            isLoading={isLoading}
            authMode={authMode}
            oidcButtonLabel={oidcButtonLabel}
            hideLocalAuth={hideLocalAuth}
            oidcAutoRedirect={oidcAutoRedirect}
          />
        </div>
      </div>
    </div>
  );
};
