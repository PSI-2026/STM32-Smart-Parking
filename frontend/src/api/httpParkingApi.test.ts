import { afterEach, describe, expect, it, vi } from 'vitest';
import unknown from '../../../backend/contracts/examples/snapshot-unknown.json';
import { ageSnapshot, createHttpParkingApi, unknownSnapshot } from './httpParkingApi';
import { getSlotState } from './selectors';

const result = (id: string, status = 'done') => ({ commandId: id, status, message: 'rezultat', createdAt: 1,
  updatedAt: 1, sessionId: null, error: null });
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const wait = () => new Promise(resolve => setTimeout(resolve, 10));
afterEach(() => { vi.useRealTimers(); });

describe('HTTP ParkingApi', () => {
  it('reads authenticated v1 diagnostics without inventing distributed capacity', async () => {
    const diagnostic = { profile: 'hybrid-v1-readonly', selected: true, enabled: true, readOnly: true,
      unitId: 1, protocolVersion: 256, connected: true, quality: 'reported', observedAt: 1800000000000,
      ageMs: 10, staleAfterMs: 2000, deviceHealth: 1, physicalSlotId: 1, deviceKnown: true,
      occupied: false, rawRegisters: [1, 256, 1, 0, 0, 1], freshnessGuarantee: 'communication-only', message: 'v1' };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json(diagnostic));
    const api = createHttpParkingApi({ fetch: fetcher });
    api.setAccessToken('readonly-token');
    expect((await api.readLegacyTelemetry()).occupied).toBe(false);
    const call = fetcher.mock.calls.find(([path]) => path === '/api/v1/diagnostics/legacy');
    expect(call).toBeDefined();
    expect(new Headers(call?.[1]?.headers).get('Authorization')).toBe('Bearer readonly-token');
    expect(api.getSnapshot().capacity?.available).toBeNull();
    for (const change of [{ ageMs: 2000 }, { rawRegisters: [1, 256, 1, 1, 1, 1] }, { deviceKnown: false }]) {
      fetcher.mockResolvedValueOnce(json({ ...diagnostic, ...change }));
      await expect(api.readLegacyTelemetry()).rejects.toThrow();
    }
    api.dispose();
  });
  it('starts unknown and uses protected HTTP snapshots instead of local demo data', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json(unknown));
    const api = createHttpParkingApi({ fetch: fetcher });
    expect(api.getSnapshot().slots.every(s => s.occupied === null)).toBe(true);
    api.setAccessToken('runtime-token');
    const unsubscribe = api.subscribe(() => {});
    await wait();
    expect(api.getSnapshot().mode).toBe('hardware');
    expect(api.getSnapshot().apiConnection).toBe('online');
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).get('Authorization')).toBe('Bearer runtime-token');
    unsubscribe(); api.dispose();
  });

  it('does not publish malformed or incomplete snapshot data', async () => {
    const api = createHttpParkingApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(json({ ...unknown, slots: [] })) });
    api.refresh(); await wait();
    expect(api.getSnapshot().apiConnection).toBe('offline');
    expect(api.getSnapshot().capacity?.available).toBeNull();
    api.dispose();
  });

  it('preserves the synchronous cache reference until publication and prevents overlapping polls', async () => {
    let resolve!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>().mockImplementation(() => new Promise(r => { resolve = r; }));
    const api = createHttpParkingApi({ fetch: fetcher });
    const before = api.getSnapshot();
    api.refresh(); api.refresh();
    expect(api.getSnapshot()).toBe(before);
    expect(fetcher).toHaveBeenCalledTimes(1);
    resolve(json(unknown)); await wait();
    expect(api.getSnapshot()).not.toBe(before);
    api.dispose();
  });

  it('expires cached samples locally, independently of browser/server wall clock skew', () => {
    const source = unknownSnapshot();
    source.mode = 'hardware';
    source.stations.forEach(s => Object.assign(s, { online: true, quality: 'valid', ageMs: 1500, updatedAt: 999999999 }));
    source.slots.forEach(s => Object.assign(s, { occupied: false, quality: 'valid', ageMs: 1500 }));
    source.capacity = { available: 4, physicalOccupied: 0, outstandingClaims: 0, reconciliationRequired: false };
    const aged = ageSnapshot(source, 600);
    expect(aged.capacity?.available).toBeNull();
    expect(aged.slots.every(s => s.occupied === null)).toBe(true);
    expect(getSlotState(aged, aged.slots[0], 0)).toBe('unknown');
  });

  it('waits through accepted/executing and correlates the final result', async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(json(result('one', 'accepted'), 202))
      .mockResolvedValueOnce(json(result('one', 'executing')))
      .mockResolvedValueOnce(json(result('one')))
      .mockResolvedValue(json(unknown));
    const api = createHttpParkingApi({ fetch: fetcher, pollMs: 1 });
    expect((await api.execute('one', { type: 'pay', sessionId: 's1' })).status).toBe('done');
    expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
    api.dispose();
  });

  it('keeps a lost POST response uncertain and permits only replay of the original ID/content', async () => {
    const fetcher = vi.fn<typeof fetch>().mockRejectedValueOnce(new TypeError('connection lost')).mockResolvedValue(json(result('same')));
    const api = createHttpParkingApi({ fetch: fetcher });
    const action = { type: 'pay' as const, sessionId: 's1' };
    expect((await api.execute('same', action)).status).toBe('unknown');
    await expect(api.execute('same', { ...action, sessionId: 'other' })).rejects.toThrow('altă comandă');
    expect((await api.execute('same', action)).status).toBe('done');
    const sent = fetcher.mock.calls.filter(([, options]) => options?.method === 'POST').map(([, options]) => JSON.parse(options!.body as string));
    expect(sent).toEqual([{ commandId: 'same', action }, { commandId: 'same', action }]);
    api.dispose();
  });

  it('never accepts a result for a different command ID', async () => {
    const api = createHttpParkingApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(json(result('other'))) });
    expect((await api.execute('one', { type: 'pay', sessionId: 's1' })).status).toBe('unknown');
    api.dispose();
  });

  it('surfaces permission errors and never silently switches to mock data', async () => {
    const api = createHttpParkingApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(json({ error: {
      code: 'FORBIDDEN', message: 'Acces refuzat', retryable: false } }, 403)) });
    const command = await api.execute('one', { type: 'pay', sessionId: 's1' });
    expect(command.status).toBe('rejected');
    expect(command.message).toBe('Acces refuzat');
    expect(() => api.reset()).toThrow('persistente');
    api.dispose();
  });

  it('cleans up polling when the last subscriber leaves', async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => json(unknown));
    const api = createHttpParkingApi({ fetch: fetcher, now: () => Date.now() });
    const unsubscribe = api.subscribe(() => {});
    await vi.advanceTimersByTimeAsync(600);
    unsubscribe(); const calls = fetcher.mock.calls.length;
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetcher.mock.calls.length).toBe(calls);
    api.dispose();
  });

  it('bounds waiting for a command and retains uncertainty on deadline expiry', async () => {
    const api = createHttpParkingApi({ fetch: vi.fn<typeof fetch>().mockImplementation(async () => json(result('one', 'accepted'))),
      pollMs: 2, commandTimeoutMs: 5 });
    expect((await api.execute('one', { type: 'pay', sessionId: 's1' })).status).toBe('unknown');
    api.dispose();
  });
});
