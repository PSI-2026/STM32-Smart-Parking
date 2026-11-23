import type { CommandResult, ParkingAction, ParkingApi, ParkingSnapshot } from './types';
import { assertTopology, validCommand, validError, validRequest, validSnapshot } from './wire';

export function unknownSnapshot(): ParkingSnapshot {
  const observation = { quality: 'unknown' as const, ageMs: null, updatedAt: null };
  return {
    mode: 'unknown', transport: 'TCP', updatedAt: 0, hourlyRateBani: 0, contractVersion: '1.0.0', staleAfterMs: 2000,
    stations: (['G', 'S1', 'S2', 'S3', 'S4', 'S5'] as const).map((id, i) => ({
      id, role: ['gateway', 'slots', 'slots', 'entry', 'exit', 'environment'][i], online: false,
      schemaVersion: null, bootEpoch: null, sampleSequence: null, ...observation })),
    slots: [1, 2, 3, 4].map(id => ({ id, nodeId: id <= 2 ? 'S1' as const : 'S2' as const, occupied: null, sessionId: null, ...observation })),
    barriers: (['entry', 'exit'] as const).map(id => ({ id, nodeId: id === 'entry' ? 'S3' as const : 'S4' as const,
      state: 'UNKNOWN', obstacle: null, vehiclePresent: null, feedback: 'unknown', ...observation })),
    capacity: { physicalOccupied: null, outstandingClaims: 0, available: null, reconciliationRequired: false },
    sessions: [], events: [], commands: [], apiConnection: 'loading',
  };
}

export function ageSnapshot(source: ParkingSnapshot, elapsed: number): ParkingSnapshot {
  const snapshot = structuredClone(source);
  const threshold = snapshot.staleAfterMs ?? 2000;
  const observations = [...snapshot.stations, ...snapshot.slots, ...snapshot.barriers];
  for (const item of observations) {
    if (item.ageMs != null) item.ageMs += Math.max(0, Math.ceil(elapsed));
    if (item.quality === 'valid' && (item.ageMs == null || item.ageMs >= threshold)) item.quality = 'stale';
  }
  const gateway = snapshot.stations.find(n => n.id === 'G');
  for (const node of snapshot.stations) {
    if (node.id !== 'G' && (gateway?.quality !== 'valid' || !gateway.online)) node.quality = 'unavailable';
    if (node.quality !== 'valid') node.online = false;
  }
  for (const item of [...snapshot.slots, ...snapshot.barriers]) {
    const station = snapshot.stations.find(n => n.id === item.nodeId);
    if (station?.quality !== 'valid' || !station.online) item.quality = 'unavailable';
    if (item.quality !== 'valid') {
      if ('occupied' in item) item.occupied = null;
      else { item.state = 'UNKNOWN'; item.obstacle = null; item.vehiclePresent = null; item.feedback = 'unknown'; }
    }
  }
  if (snapshot.slots.some(s => s.quality !== 'valid') && snapshot.capacity) {
    snapshot.capacity.available = null; snapshot.capacity.physicalOccupied = null;
  }
  return snapshot;
}

class HttpFailure extends Error {
  constructor(readonly status: number, readonly code: string, message: string) { super(message); }
}

interface Options {
  fetch?: typeof fetch;
  now?: () => number;
  pollMs?: number;
  requestTimeoutMs?: number;
  commandTimeoutMs?: number;
}

export function createHttpParkingApi(options: Options = {}): ParkingApi & { setAccessToken: (token: string) => void; dispose: () => void } {
  const request = options.fetch ?? fetch;
  const now = options.now ?? (() => performance.now());
  const pollMs = options.pollMs ?? 500;
  const requestTimeoutMs = options.requestTimeoutMs ?? 5000;
  const commandTimeoutMs = options.commandTimeoutMs ?? 15000;
  let state = unknownSnapshot();
  let sample: ParkingSnapshot | null = null;
  let sampleStarted = 0;
  let token = '';
  let epoch = 0;
  let disposed = false;
  let inFlight: Promise<void> | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;
  const listeners = new Set<() => void>();
  const controllers = new Set<AbortController>();
  const operations = new Map<string, { signature: string; promise: Promise<CommandResult> | null }>();
  const publish = (next: ParkingSnapshot) => { state = next; listeners.forEach(listener => listener()); };

  async function json(path: string, init: RequestInit = {}, timeout = requestTimeoutMs) {
    const controller = new AbortController(); controllers.add(controller);
    const deadline = setTimeout(() => controller.abort(), Math.max(1, timeout));
    try {
      const response = await request('/api/v1' + path, { ...init, signal: controller.signal, cache: 'no-store',
        headers: { Accept: 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers } });
      const body: unknown = await response.json();
      if (!response.ok) {
        if (validError(body)) throw new HttpFailure(response.status, body.error.code, body.error.message);
        throw new Error('Răspuns API invalid.');
      }
      return body;
    } finally { clearTimeout(deadline); controllers.delete(controller); }
  }

  function refresh() {
    if (inFlight || disposed) return;
    const started = now(), generation = epoch;
    const pending = (async () => {
      try {
        const body = await json('/snapshot');
        if (!validSnapshot(body)) throw new Error('Snapshot incompatibil cu API v1.');
        assertTopology(body);
        if (generation !== epoch || disposed) return;
        sample = body; sampleStarted = started;
        publish({ ...ageSnapshot(body, now() - started), apiConnection: 'online' });
      } catch (error) {
        if (generation !== epoch || disposed) return;
        sample = null;
        publish({ ...ageSnapshot(state, 10000), apiConnection: 'offline',
          apiMessage: error instanceof HttpFailure ? error.message : 'Datele backendului nu sunt disponibile.' });
      }
    })();
    inFlight = pending;
    void pending.finally(() => { if (inFlight === pending) inFlight = null; });
  }

  async function execute(commandId: string, action: ParkingAction): Promise<CommandResult> {
    if (disposed) throw new Error('Adaptor închis.');
    if (!validRequest({ commandId, action })) throw new Error('Comandă invalidă.');
    const signature = JSON.stringify(Object.fromEntries(Object.entries(action).sort(([a], [b]) => a.localeCompare(b))));
    const previous = operations.get(commandId);
    if (previous && previous.signature !== signature) throw new Error('ID-ul identifică altă comandă.');
    if (previous?.promise) return previous.promise;
    const generation = epoch;
    const pending = (async (): Promise<CommandResult> => {
      const deadline = now() + commandTimeoutMs;
      const uncertain = (): CommandResult => ({ commandId, status: 'unknown', message: 'Rezultat incert. Verifică aceeași comandă; nu crea un ID nou.' });
      try {
        let body = await json('/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ commandId, action }) }, Math.min(requestTimeoutMs, commandTimeoutMs));
        while (true) {
          if (disposed || generation !== epoch) return uncertain();
          if (!validCommand(body) || body.commandId !== commandId) throw new Error('Rezultat necorelat.');
          if (body.status !== 'accepted' && body.status !== 'executing') { refresh(); return body; }
          const remaining = deadline - now();
          if (remaining <= 0) return uncertain();
          await new Promise(resolve => setTimeout(resolve, Math.min(pollMs, remaining)));
          if (disposed || generation !== epoch || now() >= deadline) return uncertain();
          body = await json('/commands/' + encodeURIComponent(commandId), {}, Math.min(requestTimeoutMs, deadline - now()));
        }
      } catch (error) {
        if (error instanceof HttpFailure && [401, 403, 409, 422].includes(error.status)) {
          return { commandId, status: 'rejected', message: error.message, error: { code: error.code, message: error.message, retryable: false } };
        }
        return uncertain();
      } finally {
        const operation = operations.get(commandId);
        if (operation) operation.promise = null;
      }
    })();
    operations.set(commandId, { signature, promise: pending });
    return pending;
  }

  return {
    getSnapshot: () => state,
    subscribe(listener) {
      listeners.add(listener);
      if (timer === null) {
        refresh();
        let lastPoll = now();
        timer = setInterval(() => {
          if (sample) publish({ ...ageSnapshot(sample, now() - sampleStarted), apiConnection: 'online' });
          if (now() - lastPoll >= pollMs) { lastPoll = now(); refresh(); }
        }, Math.min(250, pollMs));
      }
      return () => { listeners.delete(listener); if (!listeners.size && timer !== null) { clearInterval(timer); timer = null; } };
    },
    refresh, execute,
    reset() { throw new Error('Resetarea datelor persistente nu este disponibilă prin API.'); },
    setAccessToken(value) {
      token = value.trim(); epoch++; sample = null;
      controllers.forEach(controller => controller.abort());
      publish(unknownSnapshot());
      void (inFlight ?? Promise.resolve()).finally(refresh);
    },
    dispose() { disposed = true; if (timer !== null) clearInterval(timer); timer = null; listeners.clear(); controllers.forEach(c => c.abort()); },
  };
}
