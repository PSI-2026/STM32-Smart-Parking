import { isNodeAvailable, getOccupancy } from './selectors';
import type { BarrierId, CommandResult, ParkingAction, ParkingApi, ParkingEvent, ParkingSession, ParkingSnapshot } from './types';

// All tariff and parking rules here belong to the simulated server adapter.
// Production fees and exit authorization must come from the real backend.
export function simulatedFee(enteredAt: number, now: number, rateBani: number): number {
  return Math.ceil(Math.max(0, now - enteredAt) / 3_600_000) * rateBani;
}

function initialSnapshot(now: number): ParkingSnapshot {
  const makeSession = (id: string, plate: string, slotId: number, minutes: number, paid: boolean): ParkingSession => ({
    id, plate, slotId, enteredAt: now - minutes * 60_000, exitedAt: null,
    status: paid ? 'paid' : 'active', hourlyRateBani: 500,
    amountDueBani: Math.ceil(minutes / 60) * 500,
    paidBani: paid ? Math.ceil(minutes / 60) * 500 : 0,
  });
  return {
    mode: 'simulation', transport: 'TCP', updatedAt: now, hourlyRateBani: 500,
    stations: [
      { id: 'G', role: 'Gateway · legătura cu PC-ul', online: true, updatedAt: now },
      { id: 'S1', role: 'Locurile P01–P02', online: true, updatedAt: now },
      { id: 'S2', role: 'Locurile P03–P04', online: true, updatedAt: now },
      { id: 'S3', role: 'Bariera de intrare', online: true, updatedAt: now },
      { id: 'S4', role: 'Bariera de ieșire', online: true, updatedAt: now },
      { id: 'S5', role: 'Mediu și semnalizare', online: true, updatedAt: now },
    ],
    slots: [
      { id: 1, nodeId: 'S1', occupied: true, sessionId: 'demo-1' },
      { id: 2, nodeId: 'S1', occupied: false, sessionId: null },
      { id: 3, nodeId: 'S2', occupied: true, sessionId: 'demo-2' },
      { id: 4, nodeId: 'S2', occupied: false, sessionId: null },
    ],
    barriers: [
      { id: 'entry', nodeId: 'S3', state: 'CLOSED', obstacle: false, feedback: 'estimated' },
      { id: 'exit', nodeId: 'S4', state: 'CLOSED', obstacle: false, feedback: 'estimated' },
    ],
    sessions: [makeSession('demo-1', 'B 101 DEM', 1, 74, false), makeSession('demo-2', 'CJ 24 DEM', 3, 38, true)],
    events: [
      { id: 'event-3', at: now - 180_000, level: 'success', message: 'Plată simulată confirmată · CJ 24 DEM' },
      { id: 'event-2', at: now - 38 * 60_000, level: 'info', message: 'Vehicul intrat · CJ 24 DEM → P03' },
      { id: 'event-1', at: now - 74 * 60_000, level: 'info', message: 'Vehicul intrat · B 101 DEM → P01' },
    ],
    commands: [],
  };
}

export function createMockParkingApi(options: { now?: () => number; delayMs?: number } = {}): ParkingApi {
  const now = options.now ?? Date.now;
  const delayMs = options.delayMs ?? 360;
  let state = initialSnapshot(now());
  let generation = 0;
  let movementBusy = false;
  const listeners = new Set<() => void>();
  const operations = new Map<string, { action: string; promise: Promise<CommandResult> }>();
  const timers = new Set<ReturnType<typeof setTimeout>>();

  const publish = () => { state = { ...state, updatedAt: now() }; listeners.forEach((listener) => listener()); };
  const event = (message: string, level: ParkingEvent['level'] = 'info') => {
    state = { ...state, events: [{ id: crypto.randomUUID(), at: now(), level, message }, ...state.events].slice(0, 100) };
  };
  const command = (commandId: string, status: CommandResult['status'], message: string): CommandResult => {
    const result = { commandId, status, message };
    state = { ...state, commands: [result, ...state.commands.filter((item) => item.commandId !== commandId)].slice(0, 20) };
    publish();
    return result;
  };
  const barrierPatch = (id: BarrierId, patch: Partial<ParkingSnapshot['barriers'][number]>) => {
    state = { ...state, barriers: state.barriers.map((barrier) => barrier.id === id ? { ...barrier, ...patch } : barrier) };
  };
  const schedule = (callback: () => void, milliseconds: number) => {
    const timer = setTimeout(() => { timers.delete(timer); callback(); }, milliseconds);
    timers.add(timer);
  };
  const closeLater = (id: BarrierId) => {
    const currentGeneration = generation;
    schedule(() => {
      if (currentGeneration !== generation) return;
      const barrier = state.barriers.find((item) => item.id === id)!;
      if (barrier.obstacle || !isNodeAvailable(state, barrier.nodeId, now())) {
        barrierPatch(id, { state: 'FAULT' });
        event('Închidere suspendată: obstacol sau comunicație indisponibilă.', 'warning');
        publish();
        return;
      }
      barrierPatch(id, { state: 'CLOSING' });
      publish();
      schedule(() => {
        if (currentGeneration !== generation) return;
        const current = state.barriers.find((item) => item.id === id)!;
        barrierPatch(id, { state: current.obstacle || !isNodeAvailable(state, current.nodeId, now()) ? 'FAULT' : 'CLOSED' });
        publish();
      }, delayMs);
    }, 1_200);
  };

  async function run(commandId: string, action: ParkingAction): Promise<CommandResult> {
    const reject = (message: string) => {
      event(message, 'warning');
      return command(commandId, 'rejected', message);
    };
    // Local simulation inputs do not travel through the gateway. They can be
    // changed offline, but selectors keep unavailable observations unknown.
    if (action.type === 'set-slot-sensor' || action.type === 'set-all-slot-sensors') {
      if (action.type === 'set-slot-sensor' && !state.slots.some((slot) => slot.id === action.slotId)) {
        return reject('Senzorul de ocupare selectat nu există.');
      }
      const changedSlots = state.slots.filter((slot) =>
        (action.type === 'set-all-slot-sensors' || slot.id === action.slotId) && slot.occupied !== action.occupied);
      state = { ...state, slots: state.slots.map((slot) =>
        changedSlots.some((changed) => changed.id === slot.id) ? { ...slot, occupied: action.occupied } : slot) };
      changedSlots.forEach((slot) => event(
        `P0${slot.id} · senzor ocupare ${action.occupied ? 'activat' : 'eliberat'} manual (${slot.nodeId}, simulare)`,
      ));
      const message = action.type === 'set-all-slot-sensors'
        ? `Senzori simulați: toate locurile ${action.occupied ? 'ocupate' : 'libere'}.`
        : `P0${action.slotId} · senzor ${action.occupied ? 'activat' : 'eliberat'} în simulator.`;
      return command(commandId, 'done', message);
    }
    if (action.type === 'set-node-online') {
      state = { ...state, stations: state.stations.map((node) => node.id === action.nodeId ? { ...node, online: action.online, updatedAt: now() } : node) };
      // Reconnection is a fresh simulator observation, never an assumption of free places.
      if (action.online) {
        state = { ...state, barriers: state.barriers.map((barrier) =>
          (action.nodeId === 'G' || barrier.nodeId === action.nodeId) && !barrier.obstacle
            ? { ...barrier, state: 'CLOSED' as const } : barrier) };
      }
      event(`${action.nodeId} · ${action.online ? 'conexiune restabilită' : 'conexiune întreruptă (simulare)'}`, action.online ? 'success' : 'warning');
      return command(commandId, 'done', 'Starea conexiunii simulate a fost actualizată.');
    }
    if (action.type === 'set-transport') {
      state = { ...state, transport: action.transport };
      event(`Transport simulat selectat · ${action.transport === 'TCP' ? 'Ethernet / TCP' : 'USB / RTU'}`);
      return command(commandId, 'done', 'Transportul simulat a fost schimbat.');
    }
    if (action.type === 'set-obstacle') {
      const barrier = state.barriers.find((item) => item.id === action.barrierId)!;
      barrierPatch(action.barrierId, { obstacle: action.active, state: action.active ? 'FAULT' : 'CLOSED' });
      event(`${barrier.nodeId} · obstacol ${action.active ? 'detectat' : 'eliminat'} (simulare)`, action.active ? 'warning' : 'success');
      return command(commandId, 'done', 'Senzorul de obstacol simulat a fost actualizat.');
    }
    if (!isNodeAvailable(state, 'G', now())) return reject('Gateway indisponibil. Comanda nu poate fi trimisă.');

    if (action.type === 'pay') {
      const session = state.sessions.find((item) => item.id === action.sessionId);
      if (!session || session.status === 'completed') return reject('Sesiunea nu mai este activă.');
      if (session.status === 'paid') return command(commandId, 'done', 'Plata simulată este deja confirmată.');
      const amount = simulatedFee(session.enteredAt, now(), session.hourlyRateBani);
      state = { ...state, sessions: state.sessions.map((item) => item.id === session.id
        ? { ...item, status: 'paid', paidBani: amount, amountDueBani: amount } : item) };
      event(`Plată simulată confirmată · ${session.plate}`, 'success');
      return command(commandId, 'done', `Plată simulată confirmată pentru ${session.plate}.`);
    }

    if (movementBusy) return reject('O comandă de acces este în curs. Așteaptă rezultatul.');
    const barrierId: BarrierId = action.type === 'enter' ? 'entry' : 'exit';
    const barrier = state.barriers.find((item) => item.id === barrierId)!;
    if (!isNodeAvailable(state, barrier.nodeId, now())) return reject('Stația barierei este indisponibilă.');
    if (barrier.obstacle || barrier.state !== 'CLOSED') return reject('Bariera nu este pregătită. Verifică starea și obstacolul.');
    if (getOccupancy(state, now()).unknown > 0) return reject('Datele locurilor sunt necunoscute. Restabilește comunicația.');

    let session: ParkingSession;
    if (action.type === 'enter') {
      const plate = action.plate.trim().toUpperCase().replace(/\s+/g, ' ');
      if (!/^[A-Z0-9][A-Z0-9 -]{1,13}[A-Z0-9]$/.test(plate) || !/[A-Z]/.test(plate) || !/\d/.test(plate)) {
        return reject('Introdu un număr fictiv de 3–15 caractere, cu litere și cifre.');
      }
      if (state.sessions.some((item) => item.plate === plate && item.status !== 'completed')) return reject('Vehiculul are deja o sesiune activă.');
      const slot = state.slots.find((item) => !item.occupied && item.sessionId === null);
      if (!slot) return reject(state.slots.some((item) => !item.occupied)
        ? 'Locurile libere au sesiuni asociate. Încheie sesiunile prin fluxul de ieșire.'
        : 'Parcarea este plină. Nu există locuri disponibile.');
      session = {
        id: crypto.randomUUID(), plate, slotId: slot.id, enteredAt: now(), exitedAt: null,
        status: 'active', hourlyRateBani: state.hourlyRateBani, amountDueBani: 0, paidBani: 0,
      };
    } else {
      const existing = state.sessions.find((item) => item.id === action.sessionId);
      if (!existing || existing.status === 'completed') return reject('Sesiunea nu mai este activă.');
      if (existing.status !== 'paid') return reject('Ieșirea necesită confirmarea plății simulate.');
      session = existing;
    }

    movementBusy = true;
    const currentGeneration = generation;
    command(commandId, 'accepted', 'Comandă acceptată de simulator.');
    barrierPatch(barrierId, { state: 'OPENING' });
    command(commandId, 'executing', 'Deschidere simulată în curs.');
    await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
    if (currentGeneration !== generation) return { commandId, status: 'unknown', message: 'Comanda a fost anulată prin resetarea simulării.' };
    movementBusy = false;
    const latestBarrier = state.barriers.find((item) => item.id === barrierId)!;
    if (!isNodeAvailable(state, latestBarrier.nodeId, now()) || getOccupancy(state, now()).unknown > 0 || latestBarrier.obstacle) {
      barrierPatch(barrierId, { state: 'FAULT' });
      event('Comandă întreruptă. Verifică legătura și interblocările.', 'warning');
      return command(commandId, 'unknown', 'Execuția nu a fost confirmată. Nu retrimite automat comanda.');
    }

    if (action.type === 'enter') {
      const target = state.slots.find((slot) => slot.id === session.slotId)!;
      if (target.occupied || target.sessionId !== null) {
        barrierPatch(barrierId, { state: 'FAULT' });
        event(`Intrare anulată: P0${target.id} a devenit indisponibil în timpul comenzii.`, 'warning');
        return command(commandId, 'rejected', 'Locul selectat a devenit indisponibil. Intrarea nu a fost confirmată.');
      }
    }

    barrierPatch(barrierId, { state: 'OPEN' });
    if (action.type === 'enter') {
      session = { ...session, enteredAt: now() };
      state = { ...state, sessions: [session, ...state.sessions], slots: state.slots.map((slot) =>
        slot.id === session.slotId ? { ...slot, occupied: true, sessionId: session.id } : slot) };
      event(`Vehicul intrat · ${session.plate} → P0${session.slotId}`, 'success');
    } else {
      state = { ...state, sessions: state.sessions.map((item) => item.id === session.id
        ? { ...item, status: 'completed', exitedAt: now() } : item), slots: state.slots.map((slot) =>
        slot.sessionId === session.id ? { ...slot, occupied: false, sessionId: null } : slot) };
      event(`Ieșire autorizată și loc eliberat (simulare) · ${session.plate}`, 'success');
    }
    closeLater(barrierId);
    return command(commandId, 'done', action.type === 'enter' ? `${session.plate} · intrare simulată în P0${session.slotId}.` : `${session.plate} · ieșire simulată confirmată.`);
  }

  return {
    getSnapshot: () => state,
    subscribe: (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    execute: (commandId, action) => {
      const signature = JSON.stringify(action);
      const previous = operations.get(commandId);
      if (previous) return previous.action === signature ? previous.promise
        : Promise.resolve({ commandId, status: 'rejected', message: 'ID-ul comenzii este deja folosit pentru altă operație.' });
      const promise = run(commandId, action);
      operations.set(commandId, { action: signature, promise });
      return promise;
    },
    refresh: () => {
      const gatewayOnline = state.stations.find((node) => node.id === 'G')!.online;
      state = { ...state,
        stations: state.stations.map((node) => node.online && gatewayOnline ? { ...node, updatedAt: now() } : node),
        sessions: state.sessions.map((session) => session.status === 'active'
          ? { ...session, amountDueBani: simulatedFee(session.enteredAt, now(), session.hourlyRateBani) } : session),
      };
      publish();
    },
    reset: () => {
      generation += 1;
      timers.forEach(clearTimeout);
      timers.clear();
      operations.clear();
      movementBusy = false;
      state = initialSnapshot(now());
      publish();
    },
  };
}
