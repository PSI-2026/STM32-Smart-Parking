import type { Barrier, NodeId, ParkingSlot, ParkingSnapshot, SlotState } from './types';

export const STALE_AFTER_MS = 2_000;

export function isNodeAvailable(snapshot: ParkingSnapshot, nodeId: NodeId, now = Date.now()): boolean {
  return [snapshot.stations.find((node) => node.id === 'G'), snapshot.stations.find((node) => node.id === nodeId)]
    .every((node) => node !== undefined && node.online && now - node.updatedAt <= STALE_AFTER_MS);
}

export function getSlotState(snapshot: ParkingSnapshot, slot: ParkingSlot, now = Date.now()): SlotState {
  return isNodeAvailable(snapshot, slot.nodeId, now) ? (slot.occupied ? 'occupied' : 'free') : 'unknown';
}

export function getOccupancy(snapshot: ParkingSnapshot, now = Date.now()) {
  const counts = { free: 0, occupied: 0, unknown: 0 };
  snapshot.slots.forEach((slot) => { counts[getSlotState(snapshot, slot, now)] += 1; });
  return counts;
}

export function getBarrierState(snapshot: ParkingSnapshot, barrier: Barrier, now = Date.now()) {
  return isNodeAvailable(snapshot, barrier.nodeId, now) ? barrier.state : 'UNKNOWN';
}
