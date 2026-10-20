import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

export default defineConfig({
  plugins: [react()],
  define: { __RIFT_BROWSER_MANIFEST__: JSON.stringify(JSON.parse(readFileSync(new URL('./public/browser/manifest.json', import.meta.url), 'utf8')).manifest_digest) },
  base: "/",
  server: { proxy: { "/api": "http://127.0.0.1:8770" } },
  build: { outDir: "dist", sourcemap: false, target: "es2022" },
});
