import { readFile, writeFile } from 'node:fs/promises';
import path from 'path';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

const backendTarget = 'http://localhost:8084';

const precacheBuildAssets = (): Plugin => ({
  name: 'bookflow-precache-build-assets',
  apply: 'build',
  async writeBundle(outputOptions, bundle) {
    const assets = Object.values(bundle)
      .filter((entry) => entry.type === 'chunk' || entry.type === 'asset')
      .map((entry) => entry.fileName)
      .filter(
        (fileName) =>
          fileName.startsWith('assets/') && (fileName.endsWith('.js') || fileName.endsWith('.css')),
      );
    const outputDirectory = outputOptions.dir ?? path.dirname(outputOptions.file ?? 'dist');
    const workerPath = path.join(outputDirectory, 'service-worker.js');
    const worker = await readFile(workerPath, 'utf8');
    await writeFile(
      workerPath,
      worker.replace('__BOOKFLOW_PRECACHE__', JSON.stringify(assets)),
      'utf8',
    );
  },
});

export default defineConfig(({ command }) => ({
  base: command === 'build' ? './' : '/',
  plugins: [tailwindcss(), react(), precacheBuildAssets()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    strictPort: true,
    cors: true,
    proxy: {
      // Proxy API requests to the Docker backend
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        headers: {
          Origin: backendTarget,
        },
        secure: false,
      },
      // Proxy Socket.IO so websocket polling/upgrades share the same origin/cookies as /api.
      '/socket.io': {
        target: backendTarget,
        changeOrigin: true,
        headers: {
          Origin: backendTarget,
        },
        secure: false,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
}));
