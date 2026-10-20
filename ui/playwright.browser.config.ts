import { defineConfig } from '@playwright/test';
import { isolatedFirefox } from './test-support/firefox-isolated';
export default defineConfig({
  testDir: './browser-tests', outputDir: './browser-test-results', timeout: 180_000, workers: 1, fullyParallel: false,
  reporter: [['list'], ['json', { outputFile: 'test-results/browser-results.json' }]],
  use: { baseURL: 'http://127.0.0.1:8780', headless: true, reducedMotion: 'reduce' },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium', channel: 'chrome' } },
    { name: 'firefox', use: { browserName: 'firefox', launchOptions: isolatedFirefox() } },
    { name: 'webkit', use: { browserName: 'webkit' } },
  ],
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 8780 --strictPort', url: 'http://127.0.0.1:8780', reuseExistingServer: true },
});
