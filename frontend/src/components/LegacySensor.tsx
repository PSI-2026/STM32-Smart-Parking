import { useEffect, useState } from 'react';
import { parkingApi } from '../api';
import type { LegacyTelemetry } from '../api/types';

export function LegacySensor({ onSelected }: { onSelected: (selected: boolean) => void }) {
  const [data, setData] = useState<LegacyTelemetry | null>(null);
  useEffect(() => {
    let active = true, busy = false, lastPoll = -Infinity, started = 0;
    let sample: LegacyTelemetry | null = null;
    const publish = () => {
      if (!active || !sample) return;
      const age = sample.ageMs === null ? null : sample.ageMs + Math.max(0, Math.ceil(performance.now() - started));
      const stale = age !== null && age >= sample.staleAfterMs;
      setData({ ...sample, ageMs: age, quality: stale ? 'stale' : sample.quality,
        occupied: stale ? null : sample.occupied, connected: stale ? false : sample.connected });
    };
    const poll = async () => {
      if (busy) return;
      busy = true; lastPoll = performance.now();
      const requestStarted = lastPoll;
      try {
        const value = await parkingApi.readLegacyTelemetry();
        if (!active) return;
        sample = value; started = requestStarted;
        onSelected(value.selected); publish();
      } catch {
        if (active && sample) {
          sample = { ...sample, quality: 'unavailable', connected: false, occupied: null, rawRegisters: null };
          publish();
        }
      } finally { busy = false; }
    };
    void poll();
    const timer = setInterval(() => {
      publish();
      if (performance.now() - lastPoll >= 500) void poll();
    }, 250);
    return () => { active = false; clearInterval(timer); onSelected(false); };
  }, [onSelected]);
  if (!data?.selected) return null;
  const reported = data.quality === 'reported' && data.occupied !== null;
  return <section className="panel api-access" aria-label="Senzor fizic v1.0">
    <h2>STM32 v1.0 · numai citire</h2>
    <p>FC03 · Unit ID {data.unitId} · P01 fizic</p>
    <p role="status" aria-live="polite"><strong>{reported ? data.occupied ? 'P01 ocupat (raportat de placă)' : 'P01 liber (raportat de placă)' : 'P01 necunoscut'}</strong></p>
    <p>{data.connected ? 'Răspuns USB/RTU recent' : 'Observație indisponibilă sau expirată'} · {data.quality}</p>
    <p>Prospețime confirmată doar pentru comunicație. Firmware-ul nu raportează vechimea achiziției sau boot-ul MCU.</p>
    <p>P02–P04 și capacitatea parcării rămân necunoscute. Comenzile barierei, plățile și sesiunile sunt dezactivate în acest profil.</p>
    {data.rawRegisters && <details><summary>Registre citite</summary><code>{JSON.stringify(data.rawRegisters)}</code></details>}
  </section>;
}
