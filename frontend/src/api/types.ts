export type NodeId = 'G' | 'S1' | 'S2' | 'S3' | 'S4' | 'S5';
export type Transport = 'TCP' | 'USB';
export type BarrierId = 'entry' | 'exit';
export type SlotState = 'free' | 'occupied' | 'unknown';
export type CommandStatus = 'accepted' | 'executing' | 'done' | 'rejected' | 'unknown';

export interface Station {
  id: NodeId;
  role: string;
  online: boolean;
  updatedAt: number;
}

export interface ParkingSlot {
  id: number;
  nodeId: 'S1' | 'S2';
  occupied: boolean;
  sessionId: string | null;
}

export interface Barrier {
  id: BarrierId;
  nodeId: 'S3' | 'S4';
  state: 'CLOSED' | 'OPENING' | 'OPEN' | 'CLOSING' | 'FAULT';
  obstacle: boolean;
  vehiclePresent: boolean;
  feedback: 'estimated';
}

export interface ParkingSession {
  id: string;
  plate: string;
  slotId: number;
  enteredAt: number;
  exitedAt: number | null;
  status: 'active' | 'paid' | 'completed';
  hourlyRateBani: number;
  amountDueBani: number;
  paidBani: number;
}

export interface ParkingEvent {
  id: string;
  at: number;
  level: 'info' | 'success' | 'warning';
  message: string;
}

export interface CommandResult {
  commandId: string;
  status: CommandStatus;
  message: string;
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
  mode: 'simulation';
  transport: Transport;
  updatedAt: number;
  hourlyRateBani: number;
  stations: Station[];
  slots: ParkingSlot[];
  barriers: Barrier[];
  sessions: ParkingSession[];
  events: ParkingEvent[];
  commands: CommandResult[];
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
