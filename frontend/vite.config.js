import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to Django, so the frontend and backend share an
// origin during development and no CORS handling is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
