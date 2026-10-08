import { defineConfig, devices } from '@playwright/test';

// E2E against the static export (npm run build first). No secrets and no network: every test
// mocks Firebase and the API (e2e/fixtures.ts). PW_PROJECTS picks engines (default: all three);
// PW_WEBKIT_EXECUTABLE points WebKit at a local launcher on hosts without its system libraries.
const port = Number(process.env.PORT ?? 4317);
const wanted = (process.env.PW_PROJECTS ?? 'chromium,firefox,webkit').split(',');
const webkitExe = process.env.PW_WEBKIT_EXECUTABLE;

const engines = [
  { name: 'chromium', use: devices['Desktop Chrome'] },
  { name: 'firefox', use: devices['Desktop Firefox'] },
  {
    name: 'webkit',
    use: {
      ...devices['Desktop Safari'],
      ...(webkitExe ? { launchOptions: { executablePath: webkitExe } } : {}),
    },
  },
];

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // 3, not 4: CI's 4 vCPU at 4 workers starved WebKit (#298, review 5448660102); 2 is the
  // default and leaves the E2E step seconds short of the job limit (01a11cca-c9a0).
  workers: process.env.CI ? 3 : undefined,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: { baseURL: `http://127.0.0.1:${port}`, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: engines
    .filter((e) => wanted.includes(e.name))
    .flatMap((e) => [
      { name: `${e.name}-desktop`, use: { ...e.use, viewport: { width: 1440, height: 900 } } },
      { name: `${e.name}-mobile`, use: { ...e.use, viewport: { width: 390, height: 844 } } },
    ]),
  webServer: {
    command: `node e2e/serve.mjs`,
    url: `http://127.0.0.1:${port}/app/en/`,
    env: { PORT: String(port) },
    reuseExistingServer: false,
  },
});
