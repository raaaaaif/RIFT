import { defineConfig } from '@playwright/test';
import { isolatedFirefox } from './test-support/firefox-isolated';
const remote=process.env.RIFT_TEST_URL;
export default defineConfig({
  testDir:'./lab-tests',outputDir:'./lab-test-results',timeout:60_000,workers:1,
  reporter:[['list'],['json',{outputFile:'lab-test-results/results.json'}]],
  use:{baseURL:remote ?? 'http://127.0.0.1:8790',headless:true,reducedMotion:'reduce'},
  projects:[{name:'chromium',use:{browserName:'chromium',channel:'chrome'}},{name:'firefox',use:{browserName:'firefox',launchOptions:isolatedFirefox()}},{name:'webkit',use:{browserName:'webkit'}}],
  webServer:remote?undefined:{command:'python3 -m http.server 8790 --bind 127.0.0.1 --directory dist',url:'http://127.0.0.1:8790',reuseExistingServer:true},
});
