import { defineConfig } from 'vite';
import cesium from 'vite-plugin-cesium';

export default defineConfig({
  base: process.env.BASE_PATH ?? '/',
  plugins: [cesium()],
  build: {
    chunkSizeWarningLimit: 6000,
    rollupOptions: { input: { main: 'index.html', metode: 'metode.html' } },
  },
  server: { port: 5173 },
});
