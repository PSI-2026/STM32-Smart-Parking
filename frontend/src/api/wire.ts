import Ajv2020 from 'ajv/dist/2020';
import specification from '../../../backend/contracts/openapi.v1.json';
import type { CommandResult, ParkingSnapshot } from './types';

// One schema source for backend and browser. No permissive JSON-to-DTO cast.
const ajv = new Ajv2020({ strict: false, validateFormats: false });
ajv.addSchema({ $id: 'parking-wire', components: specification.components });
export const validSnapshot = ajv.compile<ParkingSnapshot>({ $ref: 'parking-wire#/components/schemas/ParkingSnapshot' });
export const validCommand = ajv.compile<CommandResult>({ $ref: 'parking-wire#/components/schemas/CommandResult' });
export const validRequest = ajv.compile({ $ref: 'parking-wire#/components/schemas/CommandRequest' });
export const validError = ajv.compile<{ error: { code: string; message: string; retryable: boolean } }>({ $ref: 'parking-wire#/components/schemas/ApiError' });

export function assertTopology(snapshot: ParkingSnapshot) {
  if (snapshot.contractVersion !== '1.0.0' || snapshot.stations.map(n => n.id).sort().join() !== 'G,S1,S2,S3,S4,S5'
    || snapshot.slots.map(s => s.id).sort().join() !== '1,2,3,4'
    || snapshot.barriers.map(b => b.id).sort().join() !== 'entry,exit') throw new Error('Topologie API incompatibilă.');
  const stations = new Map(snapshot.stations.map(station => [station.id, station]));
  const fresh = (item: { quality?: string; ageMs?: number | null; updatedAt?: number | null }) =>
    item.quality === 'valid' && item.ageMs != null && item.ageMs < (snapshot.staleAfterMs ?? 2000) && item.updatedAt != null;
  const roles = { G: 'gateway', S1: 'slots', S2: 'slots', S3: 'entry', S4: 'exit', S5: 'environment' };
  for (const station of snapshot.stations) {
    if (station.role !== roles[station.id]) throw new Error('Rol de stație invalid.');
    if (station.quality === 'valid' && (!fresh(station) || !station.online || station.schemaVersion !== 513
      || station.bootEpoch == null || station.sampleSequence == null)) throw new Error('Identitate de stație invalidă.');
  }
  const validPath = (node: string, age: number | null | undefined) => {
    const station = snapshot.stations.find(item => item.id === node), gateway = stations.get('G');
    return station && gateway && fresh(station) && fresh(gateway) && station.online && gateway.online
      && age != null && age >= station.ageMs! && age >= gateway.ageMs!;
  };
  for (const slot of snapshot.slots) {
    if (slot.nodeId !== (slot.id <= 2 ? 'S1' : 'S2') || (slot.quality !== 'valid' && slot.occupied !== null)) throw new Error('Loc invalid.');
    if (slot.quality === 'valid' && (!fresh(slot) || slot.occupied === null || !validPath(slot.nodeId, slot.ageMs))) throw new Error('Loc fără cale validă.');
  }
  for (const barrier of snapshot.barriers) {
    if (barrier.nodeId !== (barrier.id === 'entry' ? 'S3' : 'S4')) throw new Error('Barieră invalidă.');
    if (barrier.quality === 'valid' && (!fresh(barrier) || barrier.state === 'UNKNOWN' || barrier.obstacle === null
      || barrier.vehiclePresent === null || barrier.feedback === 'unknown' || !validPath(barrier.nodeId, barrier.ageMs))) throw new Error('Barieră fără cale validă.');
    if (barrier.quality !== 'valid' && (barrier.state !== 'UNKNOWN' || barrier.obstacle !== null || barrier.vehiclePresent !== null || barrier.feedback !== 'unknown')) throw new Error('Stare de barieră invalidă.');
  }
  const capacity = snapshot.capacity;
  if (!capacity) throw new Error('Capacitate absentă.');
  if (capacity.physicalOccupied !== null && (snapshot.slots.some(slot => slot.quality !== 'valid')
    || capacity.physicalOccupied !== snapshot.slots.filter(slot => slot.occupied === true).length)) throw new Error('Ocupare inconsistentă.');
  if (capacity.available !== null && (capacity.physicalOccupied === null || capacity.reconciliationRequired
    || capacity.available !== 4 - capacity.physicalOccupied - capacity.outstandingClaims)) throw new Error('Capacitate inconsistentă.');
}
