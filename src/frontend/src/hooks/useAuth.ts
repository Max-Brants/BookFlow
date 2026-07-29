import { useState, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { useSocket } from '../contexts/SocketContext';
import {
  clearOfflinePwaBootstrap,
  offlineReadingLibrary,
  readOfflinePwaBootstrap,
} from '../library/offline';
import { login, logout, checkAuth } from '../services/api';
import type { LibraryCapability, LoginCredentials } from '../types';
import { shouldEnableAuthenticatedServices } from '../utils/authenticatedServices';
import { getReturnToFromSearch } from '../utils/authRedirect';
import { useDependencyEffect } from './useMountEffect';

interface UseAuthOptions {
  isOnline?: boolean;
  onLogoutSuccess?: () => void;
  showToast?: (message: string, type: 'info' | 'success' | 'error') => void;
}

interface UseAuthReturn {
  isAuthenticated: boolean;
  authRequired: boolean;
  authChecked: boolean;
  isAdmin: boolean;
  libraryCapability: LibraryCapability | null;
  authMode: string;
  username: string | null;
  displayName: string | null;
  oidcButtonLabel: string | null;
  hideLocalAuth: boolean;
  oidcAutoRedirect: boolean;
  loginError: string | null;
  isLoggingIn: boolean;
  authenticatedServicesEnabled: boolean;
  setIsAuthenticated: (value: boolean) => void;
  refreshAuth: () => Promise<void>;
  handleLogin: (credentials: LoginCredentials) => Promise<void>;
  handleLogout: () => Promise<void>;
}

export function useAuth(options: UseAuthOptions = {}): UseAuthReturn {
  const { isOnline = true, onLogoutSuccess, showToast } = options;
  const location = useLocation();
  const navigate = useNavigate();
  const { socket } = useSocket();
  const postLoginPath = getReturnToFromSearch(location.search);

  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authRequired, setAuthRequired] = useState(true);
  const [authChecked, setAuthChecked] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [libraryCapability, setLibraryCapability] = useState<LibraryCapability | null>(null);
  const [authMode, setAuthMode] = useState('none');
  const [username, setUsername] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [oidcButtonLabel, setOidcButtonLabel] = useState<string | null>(null);
  const [hideLocalAuth, setHideLocalAuth] = useState(false);
  const [oidcAutoRedirect, setOidcAutoRedirect] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const authenticatedServicesEnabled =
    isOnline &&
    shouldEnableAuthenticatedServices({
      authChecked,
      authRequired,
      isAuthenticated,
    });

  const applyAuthResponse = useCallback((response: Awaited<ReturnType<typeof checkAuth>>) => {
    setAuthRequired(response.auth_required !== false);
    setIsAuthenticated(response.authenticated || false);
    setIsAdmin(response.is_admin || false);
    setLibraryCapability(response.library_capability);
    setAuthMode(response.auth_mode || 'none');
    setUsername(response.username || null);
    setDisplayName(response.display_name || null);
    setOidcButtonLabel(response.oidc_button_label || null);
    setHideLocalAuth(response.hide_local_auth || false);
    setOidcAutoRedirect(response.oidc_auto_redirect || false);
  }, []);

  const applyCachedAuth = useCallback(async () => {
    const cached = await readOfflinePwaBootstrap().catch(() => null);
    if (cached) {
      const capability =
        cached.profile.libraryCapability === 'download-capable' ||
        cached.profile.libraryCapability === 'request-only'
          ? cached.profile.libraryCapability
          : null;
      setAuthRequired(true);
      setIsAuthenticated(true);
      setIsAdmin(cached.profile.isAdmin);
      setLibraryCapability(capability);
      setUsername(cached.profile.username);
      setDisplayName(cached.profile.displayName);
      return;
    }
    setAuthRequired(true);
    setIsAuthenticated(false);
    setIsAdmin(false);
    setLibraryCapability(null);
  }, []);

  const verifyAuth = useCallback(async () => {
    try {
      if (isOnline) {
        applyAuthResponse(await checkAuth());
      } else {
        await applyCachedAuth();
      }
    } catch (error) {
      console.error('Auth check failed:', error);
      await applyCachedAuth();
    } finally {
      setAuthChecked(true);
    }
  }, [applyAuthResponse, applyCachedAuth, isOnline]);

  // Do not consume network connections until authentication has been checked.
  // Connecting here also ensures the handshake sees the current session cookie.
  useDependencyEffect(() => {
    if (!socket) return;

    if (authenticatedServicesEnabled) {
      if (!socket.connected) {
        socket.connect();
      }
      return;
    }

    socket.disconnect();
  }, [authenticatedServicesEnabled, socket]);

  // Check on mount, switch to the cached profile offline, and re-check when
  // connectivity returns.
  useDependencyEffect(() => {
    void verifyAuth();
  }, [verifyAuth]);

  // Re-sync auth when returning to the tab, so role/session changes in
  // another tab/profile don't leave stale local auth state.
  useDependencyEffect(() => {
    const verifyAuthOnFocus = async () => {
      try {
        applyAuthResponse(await checkAuth());
      } catch (error) {
        console.error('Auth re-check failed:', error);
      }
    };

    const handleFocus = () => {
      if (isOnline) void verifyAuthOnFocus();
    };

    const handleVisibilityChange = () => {
      if (isOnline && document.visibilityState === 'visible') {
        void verifyAuthOnFocus();
      }
    };

    window.addEventListener('focus', handleFocus);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      window.removeEventListener('focus', handleFocus);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [isOnline]);

  const refreshAuth = useCallback(async () => {
    if (!isOnline) return;
    try {
      applyAuthResponse(await checkAuth());
    } catch (error) {
      console.error('Auth refresh failed:', error);
    }
  }, [applyAuthResponse, isOnline]);

  const handleLogin = useCallback(
    async (credentials: LoginCredentials) => {
      setIsLoggingIn(true);
      setLoginError(null);
      try {
        const response = await login(credentials);
        if (response.success) {
          // Re-check auth to get updated session state
          applyAuthResponse(await checkAuth());
          setLoginError(null);
          void navigate(postLoginPath, { replace: true });
        } else {
          setLoginError(response.error || 'Login failed');
        }
      } catch (error) {
        if (error instanceof Error) {
          setLoginError(error.message || 'Login failed');
        } else {
          setLoginError('Login failed');
        }
      } finally {
        setIsLoggingIn(false);
      }
    },
    [navigate, applyAuthResponse, postLoginPath],
  );

  const handleLogout = useCallback(async () => {
    try {
      const accountId = username ?? 'local';
      const { logout_url } = await logout();
      await Promise.all([
        offlineReadingLibrary.clearAccount(accountId),
        clearOfflinePwaBootstrap(accountId),
      ]);
      if (logout_url?.startsWith('https://') || logout_url?.startsWith('http://')) {
        window.location.href = logout_url;
        return;
      }
      try {
        // Reload auth settings after session clear so /login has current auth-mode UI config.
        applyAuthResponse(await checkAuth());
      } catch (error) {
        console.error('Post-logout auth refresh failed:', error);
        setIsAuthenticated(false);
        setIsAdmin(false);
        setLibraryCapability(null);
        setUsername(null);
        setDisplayName(null);
      }
      onLogoutSuccess?.();
      void navigate('/login', { replace: true });
    } catch (error) {
      console.error('Logout failed:', error);
      showToast?.('Logout failed', 'error');
    }
  }, [navigate, onLogoutSuccess, showToast, applyAuthResponse, username]);

  return {
    isAuthenticated,
    authRequired,
    authChecked,
    isAdmin,
    libraryCapability,
    authMode,
    username,
    displayName,
    oidcButtonLabel,
    hideLocalAuth,
    oidcAutoRedirect,
    loginError,
    isLoggingIn,
    authenticatedServicesEnabled,
    setIsAuthenticated,
    refreshAuth,
    handleLogin,
    handleLogout,
  };
}
