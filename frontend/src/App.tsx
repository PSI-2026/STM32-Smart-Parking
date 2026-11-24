import { useEffect, useRef, useState } from 'react';
import { parkingApi } from './api';
import { validRequest } from './api/wire';
import { ApiAccess } from './components/ApiAccess';
import { LegacySensor } from './components/LegacySensor';
import { getBarrierState, getOccupancy, getSlotState, isNodeAvailable } from './api/selectors';
import type { ParkingAction, ParkingSnapshot } from './api/types';
import { EntryDialog } from './components/EntryDialog';
import { SensorSimulation } from './components/SensorSimulation';
import { SensorDrawer } from './components/SensorDrawer';
import { BackendConnection } from './components/BackendConnection';
import { Events } from './components/Events';
import { CarTop, Icon } from './components/Icon';
import type { IconName } from './components/Icon';
import { useParking } from './hooks/useParking';
import { SessionsPanel } from './components/SessionsPanel';

type View = 'overview' | 'system';
type Notice = { message: string; error: boolean };
type Send = (action: ParkingAction) => Promise<boolean>;
type PendingRequest = { commandId: string; action: ParkingAction };
const PENDING_KEY = 'parking.pending-command.v1';
function restoredRequest(): PendingRequest | null {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(PENDING_KEY) ?? 'null');
    return validRequest(value) ? value as PendingRequest : null;
  } catch { return null; }
}

const navigation: { id: View; label: string; icon: IconName }[] = [
  { id: 'overview', label: 'Parcare', icon: 'grid' },
  { id: 'system', label: 'Sistem', icon: 'chip' },
];
const titles: Record<View, string> = {
  overview: 'Parcare',
  system: 'Sistem',
};

function Badge({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'green' | 'amber' | 'neutral' | 'red' }) {
  return <span className={`badge ${tone}`}><span className="status-dot" />{children}</span>;
}

export function App() {
  const snapshot = useParking();
  const [view, setView] = useState<View>('overview');
  const [entryOpen, setEntryOpen] = useState(false);
  const [sensorsOpen, setSensorsOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'active' | 'all'>('active');
  const [unresolved, setUnresolved] = useState<PendingRequest | null>(restoredRequest);
  const [legacySelected, setLegacySelected] = useState(false);
  const busy = pending || unresolved !== null;
  const counts = getOccupancy(snapshot);
  const online = isNodeAvailable(snapshot, 'G');
  const entry = snapshot.barriers.find((barrier) => barrier.id === 'entry')!;
  const canEnter = !busy && snapshot.apiConnection === 'online' && (snapshot.capacity?.available ?? 0) > 0 && counts.unknown === 0 && isNodeAvailable(snapshot, 'S3') && getBarrierState(snapshot, entry) === 'CLOSED' && entry.obstacle === false;

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 7_000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const navigate = (nextView: View) => { setSensorsOpen(false); setView(nextView); window.scrollTo({ top: 0, behavior: 'smooth' }); };

  async function perform(request: PendingRequest): Promise<boolean> {
    if (pendingRef.current) return false;
    pendingRef.current = true; setPending(true);
    try {
      // Store the original ID/action before POST; a reload must not invent a retry ID.
      sessionStorage.setItem(PENDING_KEY, JSON.stringify(request));
      setUnresolved(request);
      const result = await parkingApi.execute(request.commandId, request.action);
      const unresolvedReplay = unresolved !== null && ['UNAUTHORIZED', 'FORBIDDEN', 'IDEMPOTENCY_CONFLICT', 'VALIDATION_ERROR'].includes(result.error?.code ?? '');
      if (result.status !== 'unknown' && !unresolvedReplay) {
        sessionStorage.removeItem(PENDING_KEY); setUnresolved(null);
      }
      const success = result.status === 'done';
      setNotice({ message: result.message, error: !success });
      return success;
    } catch {
      setNotice({ message: 'Comanda nu a fost confirmată. Verifică același ID înainte de o operație nouă.', error: true });
      return false;
    } finally { pendingRef.current = false; setPending(false); }
  }
  const send: Send = action => unresolved ? Promise.resolve(false) : perform({ commandId: crypto.randomUUID(), action });

  useEffect(() => {
    if (!unresolved || pending) return;
    const command = snapshot.commands.find(item => item.commandId === unresolved.commandId);
    if (command && !['accepted', 'executing', 'unknown'].includes(command.status)) {
      sessionStorage.removeItem(PENDING_KEY); setUnresolved(null);
      if (unresolved.action.type === 'enter' && command.status === 'done') setEntryOpen(false);
      setNotice({ message: command.message, error: command.status !== 'done' });
    }
  }, [snapshot.commands, unresolved, pending]);

  const exportEvents = () => {
    const blob = new Blob([JSON.stringify({ mode: snapshot.mode, exportedAt: new Date().toISOString(), events: snapshot.events, commands: snapshot.commands }, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `smart-parking-demo-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
    setNotice({ message: 'Evenimentele și comenzile afișate au fost exportate în JSON.', error: false });
  };

  return <div className="app-shell">
    <a className="skip-link" href="#main">Sari la conținut</a>
    <aside className="sidebar">
      <a className="brand" href="#main" onClick={() => navigate('overview')} aria-label="Smart Parking, parcare"><span className="brand-mark">P<span /></span><span>smart<span className="brand-light">parking</span><small>STM32 · CONTROL CENTER</small></span></a>
      <div className="sidebar-label">SPAȚIU DE LUCRU</div>
      <nav aria-label="Navigare principală">{navigation.map((item) => <button key={item.id} className={`nav-item ${view === item.id ? 'active' : ''}`} onClick={() => navigate(item.id)} aria-current={view === item.id ? 'page' : undefined}><Icon name={item.icon} size={19} /><span>{item.label}</span></button>)}</nav>
    </aside>

    <div className="workspace">
      <header className="topbar"><div className="breadcrumb">Smart Parking <span>/</span><strong>{navigation.find((item) => item.id === view)!.label}</strong></div><div className="topbar-status"><span className="simulation-label" title="Modul și comunicația sunt raportate de backend. Plata este simulată."><span />{snapshot.mode === 'hardware' ? 'Mod hardware' : snapshot.mode === 'simulation' ? 'Simulare backend' : 'Mod necunoscut'}</span><span className="topbar-divider" /><span className={`connection ${online ? '' : 'offline'}`}><span className="status-dot" />{legacySelected ? 'Profil v1 · doar citire' : online ? 'Sistem conectat' : 'Gateway indisponibil'}</span></div></header>
      <main id="main" tabIndex={-1}>
        <div className="page-heading"><h1>{titles[view]}</h1><div className="heading-actions">{view === 'system'
          ? <button className="button secondary" disabled title="API-ul nu permite ștergerea datelor persistente."><Icon name="reset" size={16} /><span>Date persistente</span></button>
          : <button className="button primary" onClick={() => setEntryOpen(true)} disabled={!canEnter} title={!canEnter ? 'Intrarea necesită capacitate confirmată de backend și bariera pregătită.' : 'Înregistrează un vehicul'}><Icon name="plus" size={18} />Intrare vehicul</button>
        }</div></div>

        <ApiAccess snapshot={snapshot} />
        {snapshot.mode === 'hardware' && <LegacySensor onSelected={setLegacySelected} />}
        {unresolved && <div className="connection-alert" role="status"><span>Comandă în așteptare: {unresolved.commandId}. Nu emite o comandă nouă pentru aceeași operație.</span><button className="button secondary small" disabled={pending} onClick={() => void perform(unresolved)}>Verifică aceeași comandă</button></div>}
        {!online && !legacySelected && <div className="connection-alert" role="alert"><Icon name="alert" size={18} />Gateway deconectat. Datele sunt necunoscute, iar comenzile de acces sunt suspendate. Verifică alimentarea și comunicația.</div>}

        {view === 'overview' && !legacySelected && <section className="panel parking-overview" aria-labelledby="parking-overview-title">
          <div className="panel-heading parking-overview-heading">
            <div><h2 id="parking-overview-title">Situația parcării</h2><OccupancySummary snapshot={snapshot} /><p role="status">Capacitate disponibilă: {snapshot.capacity?.available ?? 'necunoscută'} · Rezervări în curs: {snapshot.capacity?.outstandingClaims ?? '—'}</p></div>
            <button disabled={snapshot.mode !== 'simulation'} className="button secondary small" aria-expanded={sensorsOpen} aria-controls="sensor-drawer" onClick={() => setSensorsOpen(true)}><Icon name="chip" size={16} />Simulare senzori</button>
          </div>
          <div className="parking-overview-body"><ParkingMap snapshot={snapshot} onSlot={(slotId) => {
          const slot = snapshot.slots.find((item) => item.id === slotId)!;
          const state = getSlotState(snapshot, slot);
          const session = snapshot.sessions.find((item) => item.id === slot.sessionId && item.status !== 'completed');
          if (state !== 'unknown' && session) {
            setSearch(session.plate);
            const heading = document.getElementById('sessions-title');
            heading?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            heading?.focus({ preventScroll: true });
          } else if (state === 'occupied') {
            setNotice({ message: `P0${slot.id} · vehicul detectat de senzor, fără sesiune asociată.`, error: false });
          } else if (state === 'free' && canEnter) setEntryOpen(true);
          else setNotice({ message: state === 'unknown' ? 'Date indisponibile pentru acest loc. Verifică stația din Sistem.' : 'Intrarea nu este disponibilă momentan. Verifică bariera și comunicația.', error: true });
          }} /><AccessPanel snapshot={snapshot} /></div>
        </section>}

        {view === 'overview' && !legacySelected && <SessionsPanel snapshot={snapshot} pending={busy} search={search} setSearch={setSearch} filter={filter} setFilter={setFilter} send={send} />}
        {view === 'system' && <div className="system-sections">
          {!legacySelected && <Diagnostics snapshot={snapshot} send={send} pending={busy} />}
          <SensorSimulation snapshot={snapshot} onAction={send} pending={busy} />
          <Events snapshot={snapshot} onExport={exportEvents} />
        </div>}

        <footer className="page-footer"><span><span className="status-dot" />STM32 Smart Parking <span className="footer-separator">/</span> Proiectarea Sistemelor Înglobate</span><span>4 locuri · 5 stații · 1 gateway</span></footer>
      </main>
    </div>

    {sensorsOpen && snapshot.mode === 'simulation' && <SensorDrawer snapshot={snapshot} pending={busy} onAction={send} onClose={() => setSensorsOpen(false)} />}
    {entryOpen && <EntryDialog pending={pending} blocked={unresolved !== null && !pending} onClose={() => setEntryOpen(false)} onEnter={(plate) => send({ type: 'enter', plate })} />}
    <div className="notification-region" aria-live="polite" aria-atomic="true">{notice && <div className={`toast ${notice.error ? 'toast-error' : ''}`}><Icon name={notice.error ? 'alert' : 'check'} size={20} /><span>{notice.message}</span><button className="icon-button" aria-label="Închide notificarea" onClick={() => setNotice(null)}><Icon name="close" size={17} /></button></div>}</div>
  </div>;
}

function OccupancySummary({ snapshot }: { snapshot: ParkingSnapshot }) {
  const counts = getOccupancy(snapshot);
  return <section className="occupancy-summary" aria-label="Ocuparea parcării" aria-live="polite" aria-atomic="true">
    <span className="occupancy-value free"><i /><strong>{counts.free}</strong> {counts.free === 1 ? 'liber' : 'libere'}</span>
    <span className="summary-separator" aria-hidden="true">·</span>
    <span className="occupancy-value occupied"><i /><strong>{counts.occupied}</strong> {counts.occupied === 1 ? 'ocupat' : 'ocupate'}</span>
    <span className="summary-separator" aria-hidden="true">·</span>
    <span className="occupancy-value unknown"><i /><strong>{counts.unknown}</strong> {counts.unknown === 1 ? 'necunoscut' : 'necunoscute'}</span>
  </section>;
}

function ParkingMap({ snapshot, onSlot }: {
  snapshot: ParkingSnapshot; onSlot: (id: number) => void;
}) {
  return <section className="parking-map" aria-labelledby="parking-title"><h3 id="parking-title">Locuri de parcare</h3>
    <div className="parking-ground">
      <div className="map-plan">
        <div className="parking-row">
          {snapshot.slots.slice(0, 2).map((slot) => <Slot key={slot.id} slotId={slot.id} snapshot={snapshot} onClick={() => onSlot(slot.id)} />)}
        </div>
        <div className="parking-row lower-row">
          {snapshot.slots.slice(2).map((slot) => <Slot key={slot.id} slotId={slot.id} snapshot={snapshot} onClick={() => onSlot(slot.id)} />)}
        </div>
      </div>
    </div>
    <div className="map-legend"><span><i className="legend-dot free" />Liber</span><span><i className="legend-dot occupied" />Ocupat</span><span><i className="legend-dot unknown" />Necunoscut</span><span className="map-hint">Selectează un loc pentru detalii <Icon name="arrow" size={14} /></span></div>
  </section>;
}

function Slot({ slotId, snapshot, onClick }: { slotId: number; snapshot: ParkingSnapshot; onClick: () => void }) {
  const slot = snapshot.slots.find((item) => item.id === slotId)!;
  const state = getSlotState(snapshot, slot);
  const session = snapshot.sessions.find((item) => item.id === slot.sessionId);
  const label = state === 'free' ? 'Disponibil' : state === 'occupied' ? 'Ocupat' : 'Necunoscut';
  return <button className={`parking-slot ${state}`} onClick={onClick} aria-label={`P0${slot.id}, ${label}${state === 'occupied' && session ? `, ${session.plate}` : ''}`}><span className="slot-heading"><strong>P0{slot.id}</strong><small>{slot.nodeId}</small></span><span className="slot-middle">{state === 'occupied' ? <CarTop occupied /> : state === 'free' ? <span className="slot-p">P</span> : <span className="slot-question">?</span>}</span><span className="slot-label">{state === 'occupied' ? session?.plate ?? 'Vehicul detectat' : label}</span><span className={`slot-state-dot ${state}`} /></button>;
}

const barrierLabels = { CLOSED: 'Închisă', OPENING: 'Se deschide', OPEN: 'Deschisă', CLOSING: 'Se închide', FAULT: 'Interblocare', UNKNOWN: 'Necunoscută' };
function AccessPanel({ snapshot }: { snapshot: ParkingSnapshot }) {
  return (
    <section className="access-panel" aria-labelledby="access-title">
      <div className="panel-heading"><div><h3 id="access-title">Control acces</h3><p>Intrare și ieșire din parcare</p></div><Icon name="signal" size={20} /></div>
      <div className="barrier-list" aria-live="polite">
        {snapshot.barriers.map((barrier) => {
          const state = getBarrierState(snapshot, barrier);
          const open = state === 'OPEN' || state === 'OPENING';
          const obstacleLabel = state === 'UNKNOWN' ? 'Obstacol necunoscut'
            : barrier.obstacle ? 'Obstacol detectat' : 'Fără obstacol';
          const presenceLabel = state === 'UNKNOWN' ? 'Prezență necunoscută'
            : barrier.vehiclePresent ? 'Vehicul detectat' : 'Fără vehicul';
          return (
            <div className="barrier-card" key={barrier.id}>
              <div className="barrier-title">
                <span className="barrier-direction"><Icon name="arrow" size={17} style={barrier.id === 'exit' ? { transform: 'rotate(-40deg)' } : undefined} />{barrier.id === 'entry' ? 'Barieră intrare' : 'Barieră ieșire'}</span>
                <Badge tone={state === 'FAULT' ? 'amber' : open ? 'green' : 'neutral'}>{barrierLabels[state]}</Badge>
              </div>
              <div className={`barrier-illustration ${open ? 'is-open' : ''} ${state === 'FAULT' ? 'is-warning' : ''} ${state === 'UNKNOWN' ? 'is-unknown' : ''}`} aria-hidden="true">
                <div className="gate-post"><span /><i /></div><div className="gate-arm" /><div className="gate-floor" />
              </div>
              <div className="barrier-meta"><span>{barrier.nodeId} · {state === 'UNKNOWN' ? 'Poziție necunoscută' : barrier.feedback === 'measured' ? 'Poziție măsurată' : 'Poziție estimată'}</span><span className={barrier.obstacle && state !== 'UNKNOWN' ? 'barrier-warning' : ''}>{obstacleLabel}</span></div>
              <div className="barrier-presence"><Icon name="car" size={13} /><span>{presenceLabel}</span></div>
            </div>
          );
        })}
      </div>
      <div className="access-note"><Icon name="info" size={15} /><span>Intrarea deschide S3. Ieșirea prin S4 necesită plata simulată confirmată.</span></div>
    </section>
  );
}

function Diagnostics({ snapshot, send, pending }: { snapshot: ParkingSnapshot; send: Send; pending: boolean }) {
  const onlineCount = snapshot.stations.filter((node) => isNodeAvailable(snapshot, node.id)).length;
  return (
    <section className="panel diagnostics-panel" aria-labelledby="diagnostics-title">
      <div className="panel-heading"><div><h2 id="diagnostics-title">Starea sistemului</h2><p>{onlineCount} din 6 noduri disponibile</p></div></div>
      <BackendConnection />
      <div className="nodes-grid">
        {snapshot.stations.map((node) => {
          const available = isNodeAvailable(snapshot, node.id);
          return (
            <div className={`node-card ${available ? '' : 'unavailable'}`} key={node.id}>
              <div className="node-icon"><Icon name={node.id === 'G' ? 'signal' : 'chip'} size={19} /></div>
              <div className="node-copy">
                <div><strong>{node.id === 'G' ? 'Gateway' : `Stația ${node.id}`}</strong><span className={`node-dot ${available ? '' : 'off'}`} aria-label={available ? 'Conectat' : 'Indisponibil'} /></div>
                <p>{node.role}</p>
                <small>{available ? 'Date actualizate' : node.ageMs == null ? 'Date necunoscute' : `Vechime: ${Math.floor(node.ageMs / 1000)} s`}</small>
              </div>
              <button className={`button small ${node.online ? 'secondary' : 'primary'}`} disabled={pending || snapshot.mode !== 'simulation'} onClick={() => void send({ type: 'set-node-online', nodeId: node.id, online: !node.online })} aria-label={`${node.online ? 'Deconectează' : 'Reconectează'} ${node.id}`}>
                {node.online ? 'Deconectează' : 'Reconectează'}
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
