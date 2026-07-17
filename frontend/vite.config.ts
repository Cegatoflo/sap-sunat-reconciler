import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 18451,
    // El backend corre en :18450. El proxy evita problemas de CORS y de cookies
    // cross-origin: para el navegador, API y frontend son el mismo origen.
    proxy: {
      "/api": { target: "http://localhost:18450", changeOrigin: true },
      "/health": { target: "http://localhost:18450", changeOrigin: true },
    },
  },
  build: { outDir: "dist" },
});
