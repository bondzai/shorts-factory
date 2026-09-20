import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built output goes into the Python package so `factory serve` ships it and
// nothing at runtime needs node. `npm run dev` proxies the API to the server.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../factory/static/dist", emptyOutDir: true, sourcemap: false },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8765", "/login": "http://127.0.0.1:8765" } },
});
