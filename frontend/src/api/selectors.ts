import type { Barrier, NodeId, Observation, ParkingSlot, ParkingSnapshot, SlotState } from './types';

export const STALE_AFTER_MS = 2_000;

function fresh(snapshot: ParkingSnapshot, item: Observation, now: number) {
  if (snapshot.contractVersion) return item.quality === 'valid' && item.ageMs != null && item.ageMs < (snapshot.staleAfterMs ?? STALE_AFTER_MS);
  return item.updatedAt != null && now - item.updatedAt <= STALE_AFTER_MS;
}

export function isNodeAvailable(snapshot: ParkingSnapshot, nodeId: NodeId, now = Date.now()): boolean {
  return [snapshot.stations.find((node) => node.id === 'G'), snapshot.stations.find((node) => node.id === nodeId)]
    .every((node) => node !== undefined && node.online && fresh(snapshot, node, now));
}

export function getSlotState(snapshot: ParkingSnapshot, slot: ParkingSlot, now = Date.now()): SlotState {
  return isNodeAvailable(snapshot, slot.nodeId, now) && slot.occupied !== null && (!snapshot.contractVersion || fresh(snapshot, slot, now))
    ? (slot.occupied ? 'occupied' : 'free') : 'unknown';
}

export function getOccupancy(snapshot: ParkingSnapshot, now = Date.now()) {
  const counts = { free: 0, occupied: 0, unknown: 0 };
  snapshot.slots.forEach((slot) => { counts[getSlotState(snapshot, slot, now)] += 1; });
  return counts;
}

export function getBarrierState(snapshot: ParkingSnapshot, barrier: Barrier, now = Date.now()) {
  return isNodeAvailable(snapshot, barrier.nodeId, now) && (!snapshot.contractVersion || fresh(snapshot, barrier, now)) ? barrier.state : 'UNKNOWN';
}
