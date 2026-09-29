import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Development: the Vite dev server (5173) proxies /api and /docs to FastAPI (8000).
// Production: `npm run build` writes dist/, which FastAPI serves on one port.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/docs": "http://127.0.0.1:8000",
      "/openapi.json": "http://127.0.0.1:8000",
    },
  },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
});
