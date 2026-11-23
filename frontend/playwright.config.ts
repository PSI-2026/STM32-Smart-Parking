import { defineConfig } from '@playwright/test';
import { randomBytes } from 'node:crypto';
import { resolve } from 'node:path';

process.env.PARKING_E2E_TOKEN ??= randomBytes(32).toString('hex');
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve('node_modules/.cache/ms-playwright');
const python = resolve('../backend/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python').replaceAll('\\', '/');

export default defineConfig({
  testDir: './e2e', workers: 1, timeout: 30000, reporter: 'list',
  use: { headless: true, screenshot: 'only-on-failure' },
  webServer: [
    { command: `"${python}" -B ../backend/scripts/e2e_server.py --port 18000`, url: 'http://127.0.0.1:18000/api/v1/health', reuseExistingServer: false },
    { command: `"${python}" -B ../backend/scripts/e2e_server.py --port 18001 --mode hardware`, url: 'http://127.0.0.1:18001/api/v1/health', reuseExistingServer: false },
    { command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 15173', url: 'http://127.0.0.1:15173', env: { BACKEND_URL: 'http://127.0.0.1:18000' }, reuseExistingServer: false },
    { command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 15174', url: 'http://127.0.0.1:15174', env: { BACKEND_URL: 'http://127.0.0.1:18001' }, reuseExistingServer: false },
  ],
});
