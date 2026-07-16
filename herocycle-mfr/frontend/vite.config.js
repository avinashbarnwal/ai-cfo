import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-server proxy: the UI calls /api/* and Vite forwards to the
// FastAPI backend on :8000, so no CORS issues in development.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
