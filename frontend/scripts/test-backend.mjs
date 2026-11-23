import assert from 'node:assert/strict';

// Both Vite and the real backend must already be running. This test does not use mocks.
const baseUrl = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
const url = new URL('/api/v1/health', baseUrl);
try {
  const response = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(5_000) });
  assert.equal(response.status, 200, `Expected HTTP 200 through the frontend proxy, received ${response.status}`);
  assert.match(response.headers.get('content-type') || '', /application\/json/i, 'Expected JSON, not the frontend HTML fallback');
  const health = await response.json();
  assert.equal(health.status, 'healthy');
  assert.equal(health.service, 'smart-parking-backend');
  assert.equal(typeof health.version, 'string');
  assert.ok(health.version.trim(), 'Expected a backend version');
  console.log(`PASS: frontend → backend: ${url} → HTTP 200, ${health.service} v${health.version}`);
} catch (error) {
  console.error(`FAIL: frontend → backend: ${url}\n${error.message}`);
  process.exitCode = 1;
}
