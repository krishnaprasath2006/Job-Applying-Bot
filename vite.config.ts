import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The Tauri shell pins ``devUrl`` to this port (src-tauri/tauri.conf.json),
    // so silently moving to another port would leave the desktop window
    // loading a URL nothing serves.
    strictPort: true,
    host: '127.0.0.1',
    hmr: false,
    // src-tauri/target is Cargo's build directory: tens of thousands of files
    // the frontend dev server has no reason to watch.
    watch: { ignored: ['**/src-tauri/**'] },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '/api'),
      },
    },
  },
});