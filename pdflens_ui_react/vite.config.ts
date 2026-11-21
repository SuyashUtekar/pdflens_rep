import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'UI_');
  return {
    base: '/ui/',
    plugins: [react()],
    server: {
      proxy: {
        '/ui-api': {
          target: env.UI_BACKEND_ORIGIN || 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  };
});
