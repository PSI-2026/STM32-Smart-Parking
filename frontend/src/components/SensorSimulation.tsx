import { getSlotState, isNodeAvailable } from '../api/selectors';
import type { ParkingAction, ParkingSnapshot } from '../api/types';
import { Icon } from './Icon';
import './SensorSimulation.css';

interface SensorSimulationProps {
  snapshot: ParkingSnapshot;
  pending: boolean;
  onAction: (action: ParkingAction) => Promise<boolean>;
  headingId?: string;
}

const stateLabels = { free: 'Liber', occupied: 'Ocupat', unknown: 'Necunoscut' };

export function SensorSimulation({ snapshot, pending, onAction, headingId = 'sensor-simulation-title' }: SensorSimulationProps) {
  if (snapshot.mode !== 'simulation') return null;

  return (
    <section className="panel sensor-panel" aria-labelledby={headingId}>
      <div className="panel-heading sensor-panel-heading">
        <div>
          <h2 id={headingId}>Simulare senzori</h2>
          <p>Simulează ocuparea locurilor, prezența vehiculelor și obstacolele.</p>
        </div>
      </div>

      <div className="sensor-section-heading">
        <h3>Locuri de parcare</h3>
        <div className="sensor-bulk-actions">
          <button
            className="button secondary small"
            disabled={pending || snapshot.slots.every((slot) => !slot.occupied)}
            onClick={() => void onAction({ type: 'set-all-slot-sensors', occupied: false })}
          >
            Toate libere
          </button>
          <button
            className="button small sensor-occupy-all"
            disabled={pending || snapshot.slots.every((slot) => slot.occupied)}
            onClick={() => void onAction({ type: 'set-all-slot-sensors', occupied: true })}
          >
            Toate ocupate
          </button>
        </div>
      </div>

      <div className="sensor-grid">
        {snapshot.slots.map((slot) => {
          const observed = getSlotState(snapshot, slot);
          const inputId = `slot-sensor-${slot.id}`;

          return (
            <div className="sensor-card" key={slot.id}>
              <div className="sensor-card-heading">
                <div className="sensor-identity">
                  <span className="sensor-icon"><Icon name="chip" size={20} /></span>
                  <div><strong>P0{slot.id}</strong><small>Stația {slot.nodeId}</small></div>
                </div>
                <span className={`sensor-observation ${observed}`}>
                  <span className="status-dot" />{stateLabels[observed]}
                </span>
              </div>
              <label className="sensor-switch" htmlFor={inputId}>
                <span>Vehicul detectat</span>
                <span className="sensor-switch-control">
                  <span className={`sensor-input-value ${slot.occupied ? 'on' : ''}`} aria-hidden="true">
                    {slot.occupied ? 'ON' : 'OFF'}
                  </span>
                  <input
                    id={inputId}
                    type="checkbox"
                    role="switch"
                    aria-label={`Vehicul detectat la P0${slot.id}`}
                    checked={slot.occupied}
                    disabled={pending}
                    onChange={(event) => void onAction({ type: 'set-slot-sensor', slotId: slot.id, occupied: event.target.checked })}
                  />
                </span>
              </label>
              <p className="sensor-card-note">
                {observed === 'unknown'
                  ? 'Date indisponibile. Poziția senzorului rămâne memorată în simulator.'
                  : 'ON = ocupat · OFF = liber'}
              </p>
            </div>
          );
        })}
      </div>

      <div className="sensor-section-heading"><h3>Bariere</h3></div>
      <div className="sensor-grid sensor-barrier-grid">
        {snapshot.barriers.map((barrier) => {
          const direction = barrier.id === 'entry' ? 'intrare' : 'ieșire';
          const available = isNodeAvailable(snapshot, barrier.nodeId);
          return (
            <div className="sensor-card" key={barrier.id}>
              <div className="sensor-card-heading">
                <div className="sensor-identity">
                  <span className="sensor-icon"><Icon name="car" size={20} /></span>
                  <div><strong>{barrier.id === 'entry' ? 'Intrare' : 'Ieșire'}</strong><small>Stația {barrier.nodeId}</small></div>
                </div>
                <span className={`sensor-observation ${available ? 'free' : 'unknown'}`}><span className="status-dot" />{available ? 'Conectat' : 'Necunoscut'}</span>
              </div>
              <label className="sensor-switch presence">
                <span>Prezență vehicul</span>
                <span className="sensor-switch-control">
                  <span className={`sensor-input-value ${barrier.vehiclePresent ? 'on' : ''}`} aria-hidden="true">{barrier.vehiclePresent ? 'ON' : 'OFF'}</span>
                  <input
                    type="checkbox"
                    role="switch"
                    aria-label={`Vehicul detectat la ${direction}`}
                    checked={barrier.vehiclePresent}
                    disabled={pending}
                    onChange={(event) => void onAction({ type: 'set-barrier-presence', barrierId: barrier.id, present: event.target.checked })}
                  />
                </span>
              </label>
              <label className="sensor-switch obstacle">
                <span>Obstacol</span>
                <span className="sensor-switch-control">
                  <span className={`sensor-input-value ${barrier.obstacle ? 'on' : ''}`} aria-hidden="true">{barrier.obstacle ? 'ON' : 'OFF'}</span>
                  <input
                    type="checkbox"
                    role="switch"
                    aria-label={`Obstacol la ${direction}`}
                    checked={barrier.obstacle}
                    disabled={pending}
                    onChange={(event) => void onAction({ type: 'set-obstacle', barrierId: barrier.id, active: event.target.checked })}
                  />
                </span>
              </label>
              {!available && <p className="sensor-card-note">Date indisponibile. Valorile senzorilor rămân memorate în simulator.</p>}
            </div>
          );
        })}
      </div>

      <div className="sensor-panel-note">
        <Icon name="info" size={16} />
        <p>Prezența vehiculului nu deschide automat bariera. Gestionează sesiunile, plata și autorizarea accesului din Parcare.</p>
      </div>
    </section>
  );
}
