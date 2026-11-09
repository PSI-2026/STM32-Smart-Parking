import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createMockParkingApi, simulatedFee } from './mockParkingApi';
import { getBarrierState, getOccupancy, getSlotState } from './selectors';
import type { ParkingAction, ParkingApi } from './types';

describe('simulated backend contract', () => {
  let api: ParkingApi;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-09T10:00:00Z'));
    api = createMockParkingApi({ delayMs: 30 });
  });
  afterEach(() => { api.reset(); vi.useRealTimers(); });

  async function execute(action: ParkingAction, id = crypto.randomUUID()) {
    const result = api.execute(id, action);
    await vi.advanceTimersByTimeAsync(35);
    return result;
  }

  it('starts with four places, six nodes, and two distinct sessions', () => {
    const state = api.getSnapshot();
    expect(state.mode).toBe('simulation');
    expect(state.stations).toHaveLength(6);
    expect(getOccupancy(state)).toEqual({ free: 2, occupied: 2, unknown: 0 });
    expect(state.sessions.filter((session) => session.status !== 'completed')).toHaveLength(2);
  });

  it('marks both places of a disconnected station unknown and preserves sensor observations', async () => {
    await execute({ type: 'set-node-online', nodeId: 'S1', online: false });
    expect(getOccupancy(api.getSnapshot())).toEqual({ free: 1, occupied: 1, unknown: 2 });
    expect(getSlotState(api.getSnapshot(), api.getSnapshot().slots[0])).toBe('unknown');
    await execute({ type: 'set-node-online', nodeId: 'S1', online: true });
    expect(getSlotState(api.getSnapshot(), api.getSnapshot().slots[0])).toBe('occupied');
    expect(api.getSnapshot().sessions).toHaveLength(2);
  });

  it('does not display old data as current when heartbeats stop', async () => {
    await vi.advanceTimersByTimeAsync(2_001);
    expect(getOccupancy(api.getSnapshot())).toEqual({ free: 0, occupied: 0, unknown: 4 });
    expect(getBarrierState(api.getSnapshot(), api.getSnapshot().barriers[0])).toBe('UNKNOWN');
  });

  it('updates a manual sensor and the journal without inventing a session or operating barriers', async () => {
    const before = api.getSnapshot();
    const result = await execute({ type: 'set-slot-sensor', slotId: 2, occupied: true });
    const state = api.getSnapshot();
    expect(result.status).toBe('done');
    expect(getOccupancy(state)).toEqual({ free: 1, occupied: 3, unknown: 0 });
    expect(state.slots[1].sessionId).toBeNull();
    expect(state.sessions).toEqual(before.sessions);
    expect(state.barriers).toEqual(before.barriers);
    expect(state.events[0].message).toContain('P02 · senzor ocupare activat manual');
  });

  it('keeps an active session associated after its sensor is released and allocates another place', async () => {
    const sessions = api.getSnapshot().sessions;
    await execute({ type: 'set-slot-sensor', slotId: 1, occupied: false });
    expect(api.getSnapshot().sessions).toEqual(sessions);
    expect(api.getSnapshot().slots[0].sessionId).toBe('demo-1');
    expect(getSlotState(api.getSnapshot(), api.getSnapshot().slots[0])).toBe('free');
    await execute({ type: 'enter', plate: 'B 123 DEM' });
    expect(api.getSnapshot().sessions[0].slotId).toBe(2);
    expect(api.getSnapshot().slots[0].sessionId).toBe('demo-1');
  });

  it('sets all sensors without changing payments and avoids duplicate events for unchanged inputs', async () => {
    const sessions = api.getSnapshot().sessions;
    await execute({ type: 'set-all-slot-sensors', occupied: false });
    expect(getOccupancy(api.getSnapshot())).toEqual({ free: 4, occupied: 0, unknown: 0 });
    expect(api.getSnapshot().sessions).toEqual(sessions);
    await execute({ type: 'set-all-slot-sensors', occupied: true });
    expect(getOccupancy(api.getSnapshot())).toEqual({ free: 0, occupied: 4, unknown: 0 });
    expect(api.getSnapshot().sessions).toEqual(sessions);
    const eventCount = api.getSnapshot().events.length;
    await execute({ type: 'set-all-slot-sensors', occupied: true });
    expect(api.getSnapshot().events).toHaveLength(eventCount);
    expect((await execute({ type: 'enter', plate: 'B 123 DEM' })).status).toBe('rejected');
  });

  it('keeps a manually changed offline sensor unknown until its station reconnects', async () => {
    await execute({ type: 'set-node-online', nodeId: 'S1', online: false });
    await execute({ type: 'set-slot-sensor', slotId: 2, occupied: true });
    expect(api.getSnapshot().slots[1].occupied).toBe(true);
    expect(getSlotState(api.getSnapshot(), api.getSnapshot().slots[1])).toBe('unknown');
    expect(getOccupancy(api.getSnapshot())).toEqual({ free: 1, occupied: 1, unknown: 2 });
    await execute({ type: 'set-node-online', nodeId: 'S1', online: true });
    expect(getSlotState(api.getSnapshot(), api.getSnapshot().slots[1])).toBe('occupied');
    expect(getOccupancy(api.getSnapshot())).toEqual({ free: 1, occupied: 3, unknown: 0 });
  });

  it('allows local sensor injection with the gateway offline without making observations valid', async () => {
    await execute({ type: 'set-node-online', nodeId: 'G', online: false });
    expect((await execute({ type: 'set-all-slot-sensors', occupied: true })).status).toBe('done');
    expect(api.getSnapshot().slots.every((slot) => slot.occupied)).toBe(true);
    expect(getOccupancy(api.getSnapshot())).toEqual({ free: 0, occupied: 0, unknown: 4 });
    await execute({ type: 'set-node-online', nodeId: 'G', online: true });
    api.refresh();
    expect(getOccupancy(api.getSnapshot())).toEqual({ free: 0, occupied: 4, unknown: 0 });
  });

  it('rejects an unknown sensor without changing any inputs or sessions', async () => {
    const before = api.getSnapshot();
    expect((await execute({ type: 'set-slot-sensor', slotId: 99, occupied: true })).status).toBe('rejected');
    expect(api.getSnapshot().slots).toEqual(before.slots);
    expect(api.getSnapshot().sessions).toEqual(before.sessions);
  });

  it('does not overwrite active sessions when all sensors are manually released', async () => {
    await execute({ type: 'set-all-slot-sensors', occupied: false });
    await execute({ type: 'enter', plate: 'B 123 DEM' });
    await vi.advanceTimersByTimeAsync(1_240);
    api.refresh();
    await execute({ type: 'enter', plate: 'B 456 DEM' });
    await vi.advanceTimersByTimeAsync(1_240);
    api.refresh();
    const result = await execute({ type: 'enter', plate: 'B 789 DEM' });
    expect(result.status).toBe('rejected');
    expect(result.message).toContain('sesiuni asociate');
    expect(api.getSnapshot().sessions).toHaveLength(4);
    expect(api.getSnapshot().slots[0].sessionId).toBe('demo-1');
    expect(api.getSnapshot().slots[2].sessionId).toBe('demo-2');
  });

  it('does not assign a place whose sensor is activated while entry is executing', async () => {
    const entry = api.execute('entry-with-sensor-change', { type: 'enter', plate: 'B 123 DEM' });
    await api.execute('sensor-change', { type: 'set-slot-sensor', slotId: 2, occupied: true });
    await vi.advanceTimersByTimeAsync(35);
    expect((await entry).status).toBe('rejected');
    expect(api.getSnapshot().sessions).toHaveLength(2);
    expect(api.getSnapshot().slots[1].occupied).toBe(true);
    expect(api.getSnapshot().slots[1].sessionId).toBeNull();
  });

  it('blocks access and payment when the gateway is disconnected', async () => {
    await execute({ type: 'set-node-online', nodeId: 'G', online: false });
    expect(getOccupancy(api.getSnapshot()).unknown).toBe(4);
    expect((await execute({ type: 'enter', plate: 'B 123 DEM' })).status).toBe('rejected');
    expect((await execute({ type: 'pay', sessionId: 'demo-1' })).status).toBe('rejected');
    expect(api.getSnapshot().sessions).toHaveLength(2);
  });

  it('does not authorize an unpaid exit', async () => {
    const result = await execute({ type: 'exit', sessionId: 'demo-1' });
    expect(result.status).toBe('rejected');
    expect(api.getSnapshot().barriers[1].state).toBe('CLOSED');
    expect(getOccupancy(api.getSnapshot()).occupied).toBe(2);
  });

  it('records a payment once even when requested with two command IDs', async () => {
    await execute({ type: 'pay', sessionId: 'demo-1' });
    await execute({ type: 'pay', sessionId: 'demo-1' });
    const state = api.getSnapshot();
    expect(state.sessions.find((session) => session.id === 'demo-1')?.paidBani).toBe(1_000);
    expect(state.events.filter((event) => event.message === 'Plată simulată confirmată · B 101 DEM')).toHaveLength(1);
    expect(state.slots[0].occupied).toBe(true);
    expect(state.barriers[1].state).toBe('CLOSED');
  });

  it('keeps the paid quote stable when time advances', async () => {
    await execute({ type: 'pay', sessionId: 'demo-1' });
    await vi.advanceTimersByTimeAsync(3_600_000);
    api.refresh();
    expect(api.getSnapshot().sessions.find((session) => session.id === 'demo-1')?.amountDueBani).toBe(1_000);
  });

  it('tracks execution separately from acceptance, then closes the barrier automatically', async () => {
    const result = api.execute('entry-command', { type: 'enter', plate: 'b 123 dem' });
    expect(api.getSnapshot().commands[0].status).toBe('executing');
    expect(api.getSnapshot().sessions).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(35);
    expect((await result).status).toBe('done');
    expect(api.getSnapshot().sessions[0].plate).toBe('B 123 DEM');
    expect(api.getSnapshot().slots[1].occupied).toBe(true);
    expect(api.getSnapshot().barriers[0].state).toBe('OPEN');
    await vi.advanceTimersByTimeAsync(1_240);
    expect(api.getSnapshot().barriers[0].state).toBe('CLOSED');
  });

  it('reuses the same command result without creating a second session', async () => {
    const action: ParkingAction = { type: 'enter', plate: 'B 123 DEM' };
    const first = api.execute('same-id', action);
    const repeated = api.execute('same-id', action);
    expect(first).toBe(repeated);
    await vi.advanceTimersByTimeAsync(35);
    expect((await first).status).toBe('done');
    expect(api.getSnapshot().sessions).toHaveLength(3);
    expect((await api.execute('same-id', { type: 'enter', plate: 'B 999 DEM' })).status).toBe('rejected');
  });

  it('rejects invalid plates and duplicate active vehicles', async () => {
    for (const plate of ['???', 'AB', '---', '12345', 'DEMO', 'B 101 DEM']) {
      expect((await execute({ type: 'enter', plate })).status).toBe('rejected');
    }
    expect(api.getSnapshot().sessions).toHaveLength(2);
  });

  it('refuses entry when full and preserves existing sessions', async () => {
    await execute({ type: 'enter', plate: 'B 123 DEM' });
    await vi.advanceTimersByTimeAsync(1_240);
    api.refresh();
    await execute({ type: 'enter', plate: 'B 456 DEM' });
    await vi.advanceTimersByTimeAsync(1_240);
    api.refresh();
    expect(getOccupancy(api.getSnapshot()).free).toBe(0);
    expect((await execute({ type: 'enter', plate: 'B 789 DEM' })).status).toBe('rejected');
    expect(api.getSnapshot().sessions).toHaveLength(4);
  });

  it('completes an authorized exit and releases only that session’s place', async () => {
    expect((await execute({ type: 'exit', sessionId: 'demo-2' })).status).toBe('done');
    const state = api.getSnapshot();
    expect(state.sessions.find((session) => session.id === 'demo-2')?.status).toBe('completed');
    expect(state.slots[2].occupied).toBe(false);
    expect(state.slots[0].occupied).toBe(true);
    expect((await execute({ type: 'pay', sessionId: 'demo-2' })).status).toBe('rejected');
  });

  it('blocks an exit when an obstacle is present', async () => {
    await execute({ type: 'set-obstacle', barrierId: 'exit', active: true });
    expect((await execute({ type: 'exit', sessionId: 'demo-2' })).status).toBe('rejected');
    expect(api.getSnapshot().slots[2].occupied).toBe(true);
    expect(api.getSnapshot().barriers[1].state).toBe('FAULT');
  });

  it('reports an unknown result if communication is lost during execution', async () => {
    const operation = api.execute('lost-link', { type: 'enter', plate: 'B 123 DEM' });
    await api.execute('disconnect', { type: 'set-node-online', nodeId: 'S3', online: false });
    await vi.advanceTimersByTimeAsync(35);
    expect((await operation).status).toBe('unknown');
    expect(api.getSnapshot().sessions).toHaveLength(2);
    expect(api.getSnapshot().slots[1].occupied).toBe(false);
  });

  it('prevents an in-flight command from repopulating a reset demo', async () => {
    const operation = api.execute('old-generation', { type: 'enter', plate: 'B 123 DEM' });
    api.reset();
    await vi.advanceTimersByTimeAsync(35);
    expect((await operation).status).toBe('unknown');
    expect(api.getSnapshot().sessions).toHaveLength(2);
    expect(api.getSnapshot().commands).toHaveLength(0);
  });

  it('keeps a barrier interlocked if an obstacle appears before automatic closing', async () => {
    await execute({ type: 'enter', plate: 'B 123 DEM' });
    await execute({ type: 'set-obstacle', barrierId: 'entry', active: true });
    await vi.advanceTimersByTimeAsync(1_240);
    expect(api.getSnapshot().barriers[0].state).toBe('FAULT');
    expect(api.getSnapshot().sessions).toHaveLength(3);
  });
});

describe('demo tariff boundary examples', () => {
  it.each([[0, 0], [1_000, 500], [3_599_000, 500], [3_600_000, 500], [3_601_000, 1_000]])('charges %i milliseconds as %i bani', (elapsed, expected) => {
    expect(simulatedFee(0, elapsed, 500)).toBe(expected);
  });
});
