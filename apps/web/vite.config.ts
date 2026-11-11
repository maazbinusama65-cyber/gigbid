import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const api = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: api, changeOrigin: true } } },
  preview: { port: 4173, proxy: { "/api": { target: api, changeOrigin: true } } },
  build: { sourcemap: false, chunkSizeWarningLimit: 400 },
});
