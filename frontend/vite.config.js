import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        timeout: 660000,       // socket timeout: 11 minutes
        proxyTimeout: 660000,  // proxy connection timeout: 11 minutes
        configure: (proxy) => {
          proxy.on('error', (err, _req, res) => {
            // Return a proper JSON error instead of letting Vite serve index.html
            if (res && !res.headersSent) {
              res.writeHead(502, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ detail: 'Backend unavailable — it may be restarting. Try again in a few seconds.' }));
            }
          });
          proxy.on('proxyReq', (proxyReq) => {
            // Keep the connection alive during long scans
            proxyReq.setHeader('Connection', 'keep-alive');
          });
        },
      }
    }
  }
});
