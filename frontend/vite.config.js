import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// Ports and backend URL come from the project-root .env (see .env.example)
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '');
  const backend = env.BACKEND_URL || `http://${env.BACKEND_HOST || '127.0.0.1'}:${env.BACKEND_PORT || 8000}`;
  return {
    plugins: [react()],
    build: {
      rollupOptions: {
        output: { manualChunks: { react: ['react', 'react-dom', 'react-router-dom'], map: ['leaflet', 'react-leaflet'], charts: ['recharts'] } },
      },
    },
    envDir: '..',
    server: {
      host: env.FRONTEND_HOST || '127.0.0.1',
      port: Number(env.FRONTEND_PORT || 5173),
      proxy: {
        '/api': { target: backend, changeOrigin: true },
        '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
        '/docs': { target: backend, changeOrigin: true },
        '/openapi.json': { target: backend, changeOrigin: true },
      },
    },
    preview: { host: env.FRONTEND_HOST || '127.0.0.1', port: Number(env.FRONTEND_PORT || 5173) },
  };
});
