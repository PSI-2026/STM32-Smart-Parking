import { afterEach, describe, expect, it, vi } from 'vitest';
import { checkBackendHealth } from './backendHealth';

const health = { status: 'healthy', service: 'smart-parking-backend', version: '0.1.0' };

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('backend health connection', () => {
  it('reads the backend contract through the same-origin proxy without caching', async () => {
    const request = vi.fn().mockResolvedValue(Response.json(health));
    vi.stubGlobal('fetch', request);
    await expect(checkBackendHealth()).resolves.toEqual(health);
    expect(request).toHaveBeenCalledWith('/api/v1/health', expect.objectContaining({
      cache: 'no-store', headers: { Accept: 'application/json' }, signal: expect.any(AbortSignal),
    }));
  });

  it('reports HTTP errors instead of accepting a JSON success body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(health, { status: 503 })));
    await expect(checkBackendHealth()).rejects.toThrow('HTTP 503');
  });

  it('rejects the HTML fallback returned by an absent API proxy', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<!doctype html><title>Frontend</title>')));
    await expect(checkBackendHealth()).rejects.toThrow('JSON valid');
  });

  it.each([
    null,
    { ...health, status: 'unhealthy' },
    { ...health, service: 'another-service' },
    { ...health, version: '' },
  ])('rejects an incompatible health response: %j', async (data) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(data)));
    await expect(checkBackendHealth()).rejects.toThrow('nu confirmă');
  });

  it('reports network failure without pretending the simulator is the backend', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(checkBackendHealth()).rejects.toThrow('Conexiunea cu backend-ul a eșuat');
  });

  it('aborts a hanging request after five seconds', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_url: string, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal!.addEventListener('abort', () => reject(options.signal!.reason), { once: true });
    })));
    const result = expect(checkBackendHealth()).rejects.toThrow('5 secunde');
    await vi.advanceTimersByTimeAsync(5_000);
    await result;
  });

  it('preserves caller cancellation when leaving the diagnostics page', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal!.addEventListener('abort', () => reject(options.signal!.reason), { once: true });
    })));
    const controller = new AbortController();
    const result = expect(checkBackendHealth(controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    controller.abort();
    await result;
  });
});
