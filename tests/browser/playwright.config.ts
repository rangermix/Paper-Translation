import { defineConfig } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';
export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.ts',
  timeout: 30000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: outputDirectory('browser-results.json') }]],
  outputDir: outputDirectory('test-results'),
  use: { baseURL: process.env.LIBRARY_BROWSER_URL ?? 'http://127.0.0.1:5173', viewport: { width: 1440, height: 1060 }, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
});
