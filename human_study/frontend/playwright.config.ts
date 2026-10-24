import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './e2e', use: { baseURL: process.env.DTAG_TEST_BROWSER_URL || 'http://127.0.0.1:8080' },
  workers: 1, timeout: 90000, reporter: 'list' });
