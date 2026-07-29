import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { App } from './App';
import { LanguageProvider } from './contexts/LanguageContext';
import { NetworkStatusProvider } from './contexts/NetworkStatusContext';
import { SocketProvider } from './contexts/SocketContext';
import { getBasePath, withBasePath } from './utils/basePath';

const root = document.getElementById('root');
if (!root) throw new Error('Root element not found');

const basePath = getBasePath();
const routerBase = basePath === '/' ? undefined : basePath;

createRoot(root).render(
  <StrictMode>
    <BrowserRouter basename={routerBase}>
      <NetworkStatusProvider>
        <LanguageProvider>
          <SocketProvider>
            <App />
          </SocketProvider>
        </LanguageProvider>
      </NetworkStatusProvider>
    </BrowserRouter>
  </StrictMode>,
);

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener(
    'load',
    () => void navigator.serviceWorker.register(withBasePath('/service-worker.js')),
  );
}
