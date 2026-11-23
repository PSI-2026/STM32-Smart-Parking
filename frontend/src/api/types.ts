export type NodeId = 'G' | 'S1' | 'S2' | 'S3' | 'S4' | 'S5';
export type Transport = 'TCP' | 'USB';
export type BarrierId = 'entry' | 'exit';
export type SlotState = 'free' | 'occupied' | 'unknown';
export type CommandStatus = 'accepted' | 'executing' | 'done' | 'rejected' | 'unknown' | 'expired' | 'failed';
export interface Observation {
  quality?: 'valid' | 'unknown' | 'stale' | 'unavailable';
  ageMs?: number | null;
  updatedAt?: number | null;
}

export interface Station extends Observation {
  id: NodeId;
  role: string;
  online: boolean;
  updatedAt: number | null;
  schemaVersion?: number | null;
  bootEpoch?: number | null;
  sampleSequence?: number | null;
}

export interface ParkingSlot extends Observation {
  id: number;
  nodeId: 'S1' | 'S2';
  occupied: boolean | null;
  sessionId: string | null;
}

export interface Barrier extends Observation {
  id: BarrierId;
  nodeId: 'S3' | 'S4';
  state: 'CLOSED' | 'OPENING' | 'OPEN' | 'CLOSING' | 'FAULT' | 'UNKNOWN';
  obstacle: boolean | null;
  vehiclePresent: boolean | null;
  feedback: 'estimated' | 'measured' | 'unknown';
}

export interface ParkingSession {
  id: string;
  plate: string;
  slotId: number | null;
  enteredAt: number | null;
  exitedAt: number | null;
  status: 'pending_entry' | 'active' | 'paid' | 'pending_exit' | 'completed' | 'cancelled';
  hourlyRateBani: number;
  amountDueBani: number;
  paidBani: number;
}

export interface ParkingEvent {
  id: string;
  at: number;
  level: 'info' | 'success' | 'warning' | 'error';
  message: string;
  code?: string;
}

export interface CommandResult {
  commandId: string;
  status: CommandStatus;
  message: string;
  createdAt?: number;
  updatedAt?: number;
  sessionId?: string | null;
  error?: { code: string; message: string; retryable: boolean } | null;
}

export type ParkingAction =
  | { type: 'enter'; plate: string }
  | { type: 'pay'; sessionId: string }
  | { type: 'exit'; sessionId: string }
  | { type: 'set-slot-sensor'; slotId: number; occupied: boolean }
  | { type: 'set-all-slot-sensors'; occupied: boolean }
  | { type: 'set-node-online'; nodeId: NodeId; online: boolean }
  | { type: 'set-obstacle'; barrierId: BarrierId; active: boolean }
  | { type: 'set-barrier-presence'; barrierId: BarrierId; present: boolean }
  | { type: 'set-transport'; transport: Transport };

export interface ParkingSnapshot {
  mode: 'simulation' | 'hardware' | 'unknown';
  transport: Transport;
  updatedAt: number;
  hourlyRateBani: number;
  stations: Station[];
  slots: ParkingSlot[];
  barriers: Barrier[];
  sessions: ParkingSession[];
  events: ParkingEvent[];
  commands: CommandResult[];
  contractVersion?: string;
  staleAfterMs?: number;
  capacity?: { physicalOccupied: number | null; outstandingClaims: number; available: number | null; reconciliationRequired: boolean };
  apiConnection?: 'loading' | 'online' | 'offline';
  apiMessage?: string;
}

// The UI only consumes this interface. The HTTP adapter and its wire schema
// must be agreed with Student 2 before replacing the simulation.
export interface ParkingApi {
  getSnapshot: () => ParkingSnapshot;
  subscribe: (listener: () => void) => () => void;
  execute: (commandId: string, action: ParkingAction) => Promise<CommandResult>;
  refresh: () => void;
  reset: () => void;
}
