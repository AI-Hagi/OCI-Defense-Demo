import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import cesium from 'vite-plugin-cesium';

export default defineConfig({
  plugins: [react(), tailwindcss(), cesium()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      // Local-dev: forward UC4 Maritime WebSocket traffic to the
      // ais-multiplexer running on :8001. In prod the OKE Ingress
      // routes /ws/maritime to the multiplexer service directly,
      // so the same frontend code path works in both environments.
      '/ws/maritime': {
        target: 'ws://localhost:8001',
        ws: true,
        changeOrigin: true,
      },
      // UC4 chat — streams tool_call / tool_result / answer events from
      // the uc4-chat FastAPI service (default :8013). Production routing
      // is identical via OKE Ingress (path /ws/uc4-chat).
      '/ws/uc4-chat': {
        target: 'ws://localhost:8013',
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
