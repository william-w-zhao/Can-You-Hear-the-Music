import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend (FastAPI) runs on :8000. /api and /data are proxied there, so the browser only talks to :5173.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/data": "http://localhost:8000",
    },
  },
});
