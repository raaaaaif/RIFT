import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: "test-results/results.json" }]],
  use: { channel: "chrome", headless: true, reducedMotion: "reduce", baseURL: "http://127.0.0.1:8771" },
  webServer: [
    { command: "cd .. && python3.12 -m rift serve --port 8771", url: "http://127.0.0.1:8771/api/cases", reuseExistingServer: false, timeout: 60_000 },
    { command: "cd .. && python3.12 -m rift serve --port 8772 --allow-run", url: "http://127.0.0.1:8772/api/cases", reuseExistingServer: false, timeout: 60_000 },
    // Static deployment rehearsal: plain file server over ui/dist, no API (as on Cloudflare Pages).
    { command: "python3 -m http.server 8773 --bind 127.0.0.1 --directory dist", url: "http://127.0.0.1:8773/data/cases.json", reuseExistingServer: false, timeout: 30_000 },
  ],
});
