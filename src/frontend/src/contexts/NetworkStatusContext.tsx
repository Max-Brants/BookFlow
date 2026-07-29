import type { ReactNode } from 'react';
import { createContext, useContext, useMemo, useState } from 'react';

import { useMountEffect } from '../hooks/useMountEffect';

interface NetworkStatusContextValue {
  isOnline: boolean;
}

const initialOnlineStatus = (): boolean =>
  typeof navigator === 'undefined' ? true : navigator.onLine;

const NetworkStatusContext = createContext<NetworkStatusContextValue>({ isOnline: true });

export const NetworkStatusProvider = ({ children }: { children: ReactNode }) => {
  const [isOnline, setIsOnline] = useState(initialOnlineStatus);

  useMountEffect(() => {
    const markOnline = () => setIsOnline(true);
    const markOffline = () => setIsOnline(false);
    window.addEventListener('online', markOnline);
    window.addEventListener('offline', markOffline);
    return () => {
      window.removeEventListener('online', markOnline);
      window.removeEventListener('offline', markOffline);
    };
  });

  const value = useMemo(() => ({ isOnline }), [isOnline]);
  return <NetworkStatusContext.Provider value={value}>{children}</NetworkStatusContext.Provider>;
};

export const useNetworkStatus = (): NetworkStatusContextValue => useContext(NetworkStatusContext);

export { initialOnlineStatus };
