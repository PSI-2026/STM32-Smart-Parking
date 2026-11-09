import { getSlotState } from '../api/selectors';
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
          <p>Activează sau eliberează manual senzorii celor patru locuri.</p>
        </div>
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

      <div className="sensor-panel-note">
        <Icon name="info" size={16} />
        <p>Aceste comutatoare schimbă doar senzorii simulați. Sesiunile și plățile se gestionează separat.</p>
      </div>
    </section>
  );
}
