import { useEffect, useRef, useState } from 'react';
import { parkingApi } from './api';
import { getBarrierState, getOccupancy, getSlotState, isNodeAvailable } from './api/selectors';
import type { ParkingAction, ParkingSnapshot, ParkingSession } from './api/types';
import { EntryDialog } from './components/EntryDialog';
import { SensorSimulation } from './components/SensorSimulation';
import { SensorDrawer } from './components/SensorDrawer';
import { BackendConnection } from './components/BackendConnection';
import { CarTop, Icon } from './components/Icon';
import type { IconName } from './components/Icon';
import { useParking } from './hooks/useParking';
import { duration, money, time } from './lib/format';

type View = 'overview' | 'system';
type Notice = { message: string; error: boolean };
type Send = (action: ParkingAction) => Promise<boolean>;

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
  const [resetRequested, setResetRequested] = useState(false);
  const counts = getOccupancy(snapshot);
  const online = isNodeAvailable(snapshot, 'G');
  const entry = snapshot.barriers.find((barrier) => barrier.id === 'entry')!;
  const hasAssignableSlot = snapshot.slots.some((slot) => !slot.occupied && slot.sessionId === null);
  const canEnter = !pending && hasAssignableSlot && counts.unknown === 0 && isNodeAvailable(snapshot, 'S3') && entry.state === 'CLOSED' && !entry.obstacle;

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 7_000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const navigate = (nextView: View) => { setSensorsOpen(false); setView(nextView); window.scrollTo({ top: 0, behavior: 'smooth' }); };

  const send: Send = async (action) => {
    if (pendingRef.current) return false;
    pendingRef.current = true;
    setPending(true);
    try {
      const result = await parkingApi.execute(crypto.randomUUID(), action);
      const success = result.status === 'done';
      setNotice({ message: result.message, error: !success });
      return success;
    } catch {
      setNotice({ message: 'Rezultatul comenzii nu este disponibil. Verifică starea înainte de a reîncerca.', error: true });
      return false;
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };

  const exportEvents = () => {
    const blob = new Blob([JSON.stringify({ mode: snapshot.mode, exportedAt: new Date().toISOString(), events: snapshot.events, commands: snapshot.commands }, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `smart-parking-demo-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
    setNotice({ message: 'Jurnalul simulat a fost exportat în format JSON.', error: false });
  };

  return <div className="app-shell">
    <a className="skip-link" href="#main">Sari la conținut</a>
    <aside className="sidebar">
      <a className="brand" href="#main" onClick={() => navigate('overview')} aria-label="Smart Parking, parcare"><span className="brand-mark">P<span /></span><span>smart<span className="brand-light">parking</span><small>STM32 · CONTROL CENTER</small></span></a>
      <div className="sidebar-label">SPAȚIU DE LUCRU</div>
      <nav aria-label="Navigare principală">{navigation.map((item) => <button key={item.id} className={`nav-item ${view === item.id ? 'active' : ''}`} onClick={() => navigate(item.id)} aria-current={view === item.id ? 'page' : undefined}><Icon name={item.icon} size={19} /><span>{item.label}</span></button>)}</nav>
    </aside>

    <div className="workspace">
      <header className="topbar"><div className="breadcrumb">Smart Parking <span>/</span><strong>{navigation.find((item) => item.id === view)!.label}</strong></div><div className="topbar-status"><span className="simulation-label" title="Date, bariere și plăți simulate. Niciun dispozitiv fizic nu este conectat."><span />Mod simulare</span><span className="topbar-divider" /><span className={`connection ${online ? '' : 'offline'}`}><span className="status-dot" />{online ? 'Sistem conectat' : 'Gateway indisponibil'}</span></div></header>
      <main id="main" tabIndex={-1}>
        <div className="page-heading"><h1>{titles[view]}</h1><div className="heading-actions">{view === 'system'
          ? <button className="button secondary" disabled={pending} onClick={() => setResetRequested(true)}><Icon name="reset" size={16} /><span>Resetează demo</span></button>
          : <button className="button primary" onClick={() => setEntryOpen(true)} disabled={!canEnter} title={!canEnter ? 'Intrarea necesită un loc liber fără sesiune asociată, date valide și bariera pregătită.' : 'Înregistrează un vehicul fictiv'}><Icon name="plus" size={18} />Intrare vehicul</button>
        }</div></div>

        {!online && <div className="connection-alert" role="alert"><Icon name="alert" size={18} />Gateway deconectat. Datele sunt necunoscute, iar comenzile de acces sunt suspendate. Reconectează G din Sistem.</div>}

        {view === 'overview' && <OccupancySummary snapshot={snapshot} />}
        {view === 'overview' && <div className="overview-grid"><ParkingMap snapshot={snapshot} sensorsOpen={sensorsOpen} onSensors={() => setSensorsOpen(true)} onSlot={(slotId) => {
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
        }} /><AccessPanel snapshot={snapshot} /></div>}

        {view === 'overview' && <SessionsPanel snapshot={snapshot} pending={pending} search={search} setSearch={setSearch} filter={filter} setFilter={setFilter} send={send} />}
        {view === 'system' && <div className="system-sections">
          <Diagnostics snapshot={snapshot} send={send} pending={pending} />
          <SensorSimulation snapshot={snapshot} onAction={send} pending={pending} />
          <Events snapshot={snapshot} onExport={exportEvents} />
        </div>}

        <footer className="page-footer"><span><span className="status-dot" />STM32 Smart Parking <span className="footer-separator">/</span> Proiectarea Sistemelor Înglobate</span><span>4 locuri · 5 stații · 1 gateway</span></footer>
      </main>
    </div>

    {sensorsOpen && <SensorDrawer snapshot={snapshot} pending={pending} onAction={send} onClose={() => setSensorsOpen(false)} />}
    {entryOpen && <EntryDialog pending={pending} onClose={() => setEntryOpen(false)} onEnter={(plate) => send({ type: 'enter', plate })} />}
    {resetRequested && <ResetDialog onCancel={() => setResetRequested(false)} onReset={() => {
      parkingApi.reset(); setResetRequested(false); setSearch(''); setFilter('active');
      setNotice({ message: 'Demo resetat. Cele două sesiuni de exemplu au fost restaurate.', error: false });
    }} />}
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

function SessionSummary({ snapshot }: { snapshot: ParkingSnapshot }) {
  const revenue = snapshot.sessions.reduce((sum, session) => sum + session.paidBani, 0);
  return <section className="session-summary" aria-label="Rezumat sesiuni">
    <span><Icon name="wallet" size={17} /><strong>{money(revenue)}</strong> încasări simulate</span>
    <span>Tarif: <strong>{money(snapshot.hourlyRateBani)} / oră</strong></span>
  </section>;
}

function ParkingMap({ snapshot, onSlot, sensorsOpen, onSensors }: {
  snapshot: ParkingSnapshot; onSlot: (id: number) => void; sensorsOpen: boolean; onSensors: () => void;
}) {
  return <section className="panel parking-panel" aria-labelledby="parking-title"><div className="panel-heading"><h2 id="parking-title">Locuri de parcare</h2><button className="button secondary small" aria-expanded={sensorsOpen} aria-controls="sensor-drawer" onClick={onSensors}><Icon name="chip" size={16} />Simulare senzori</button></div>
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
    <section className="panel access-panel" aria-labelledby="access-title">
      <div className="panel-heading"><div><h2 id="access-title">Control acces</h2><p>Intrare și ieșire din parcare</p></div><Icon name="signal" size={20} /></div>
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
              <div className="barrier-meta"><span>{barrier.nodeId} · {state === 'UNKNOWN' ? 'Poziție necunoscută' : 'Poziție estimată'}</span><span className={barrier.obstacle && state !== 'UNKNOWN' ? 'barrier-warning' : ''}>{obstacleLabel}</span></div>
              <div className="barrier-presence"><Icon name="car" size={13} /><span>{presenceLabel}</span></div>
            </div>
          );
        })}
      </div>
      <div className="access-note"><Icon name="info" size={15} /><span>Intrarea deschide S3. Ieșirea prin S4 necesită plata simulată confirmată.</span></div>
    </section>
  );
}

function SessionsPanel({ snapshot, search, setSearch, filter, setFilter, pending, send }: {
  snapshot: ParkingSnapshot; search: string; setSearch: (value: string) => void;
  filter: 'active' | 'all'; setFilter: (value: 'active' | 'all') => void;
  pending: boolean; send: Send;
}) {
  const sessions = snapshot.sessions.filter((session) => (filter === 'all' || session.status !== 'completed') && session.plate.toLowerCase().includes(search.trim().toLowerCase()));
  const canExit = (session: ParkingSession) => {
    const barrier = snapshot.barriers.find((item) => item.id === 'exit')!;
    return !pending && session.status === 'paid' && isNodeAvailable(snapshot, 'S4') && barrier.state === 'CLOSED' && !barrier.obstacle && getOccupancy(snapshot).unknown === 0;
  };
  return <section className="panel sessions-panel" aria-labelledby="sessions-title"><div className="panel-heading"><div className="title-inline"><h2 id="sessions-title" tabIndex={-1}>Sesiuni de parcare</h2><span className="number-pill">{snapshot.sessions.filter((session) => session.status !== 'completed').length} active</span></div></div><SessionSummary snapshot={snapshot} /><div className="sessions-toolbar"><div className="segmented-control" aria-label="Filtrare sesiuni"><button aria-pressed={filter === 'active'} className={filter === 'active' ? 'selected' : ''} onClick={() => setFilter('active')}>În parcare</button><button aria-pressed={filter === 'all'} className={filter === 'all' ? 'selected' : ''} onClick={() => setFilter('all')}>Toate sesiunile</button></div><label className="search-field"><Icon name="search" size={17} /><input aria-label="Caută număr de înmatriculare" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Caută un număr…" />{search && <button className="icon-button" aria-label="Șterge căutarea" onClick={() => setSearch('')}><Icon name="close" size={14} /></button>}</label></div><div className="table-scroll"><table><thead><tr><th>VEHICUL</th><th>LOC</th><th>INTRARE / DURATĂ</th><th>TAXĂ SIMULATĂ</th><th>STARE</th><th className="actions-heading">ACȚIUNE</th></tr></thead><tbody>{sessions.map((session) => <tr key={session.id}><td><span className="plate"><span className="plate-eu">RO</span>{session.plate}</span></td><td><span className="slot-table-label">P0{session.slotId}</span></td><td><div className="table-main">{time(session.enteredAt)}</div><div className="table-sub">{duration(session.enteredAt, session.exitedAt ?? snapshot.updatedAt)}</div></td><td><span className="table-main amount">{money(session.amountDueBani)}</span><div className="table-sub">{money(session.hourlyRateBani)} / oră începută</div></td><td><Badge tone={session.status === 'paid' ? 'green' : session.status === 'active' ? 'amber' : 'neutral'}>{session.status === 'paid' ? 'Plătit · demo' : session.status === 'active' ? 'Neplătit' : 'Încheiată'}</Badge></td><td className="table-actions">{session.status === 'active' ? <button className="button small secondary" disabled={pending || !isNodeAvailable(snapshot, 'G')} onClick={() => void send({ type: 'pay', sessionId: session.id })} aria-label={`Simulează plata pentru ${session.plate}`}><Icon name="wallet" size={15} />Plată demo</button> : session.status === 'paid' ? <button className="button small exit-button" disabled={!canExit(session)} onClick={() => void send({ type: 'exit', sessionId: session.id })} aria-label={`Autorizează ieșirea pentru ${session.plate}`}>Autorizează ieșirea<Icon name="arrow" size={15} /></button> : <span className="completed-label"><Icon name="check" size={16} />{time(session.exitedAt!)}</span>}</td></tr>)}</tbody></table>{sessions.length === 0 && <div className="empty-state"><Icon name="car" size={28} /><strong>{search ? 'Niciun vehicul găsit' : 'Nicio sesiune activă'}</strong><p>{search ? 'Încearcă alt număr sau afișează toate sesiunile.' : 'Următoarea intrare va apărea aici.'}</p></div>}</div><div className="table-footer"><Icon name="info" size={14} />Tariful este calculat de simulator. Plata și autorizarea ieșirii sunt operații distincte.</div></section>;
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
                <small>{available ? 'Date actualizate acum' : `Ultimele date: ${Math.max(0, Math.floor((snapshot.updatedAt - node.updatedAt) / 1_000))} s în urmă`}</small>
              </div>
              <button className={`button small ${node.online ? 'secondary' : 'primary'}`} disabled={pending} onClick={() => void send({ type: 'set-node-online', nodeId: node.id, online: !node.online })} aria-label={`${node.online ? 'Deconectează' : 'Reconectează'} ${node.id}`}>
                {node.online ? 'Deconectează' : 'Reconectează'}
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Events({ snapshot, onExport }: { snapshot: ParkingSnapshot; onExport: () => void }) {
  return (
    <section className="panel events-panel" aria-labelledby="events-title">
      <div className="panel-heading">
        <div><h2 id="events-title">Jurnal de evenimente</h2><p>{snapshot.events.length} evenimente · ultimele 100 sunt păstrate în memorie</p></div>
        <button className="button secondary small" onClick={onExport}><Icon name="download" size={15} />Exportă JSON</button>
      </div>
      <ol className="event-list">
        {snapshot.events.slice(0, 100).map((event) => (
          <li key={event.id}>
            <span className={`event-icon ${event.level}`}><Icon name={event.level === 'warning' ? 'alert' : event.level === 'success' ? 'check' : 'arrow'} size={14} /></span>
            <div><p>{event.message}</p><small>{new Date(event.at).toLocaleDateString('ro-RO', { day: '2-digit', month: 'short' })} · {time(event.at)}</small></div>
            <time dateTime={new Date(event.at).toISOString()}>{time(event.at)}</time>
          </li>
        ))}
      </ol>
      {snapshot.commands.length > 0 && <div className="command-history"><h3>Rezultate comenzi</h3>{snapshot.commands.map((item) => <div key={item.commandId}><code>{item.commandId.slice(0, 8)}</code><Badge tone={item.status === 'done' ? 'green' : 'amber'}>{item.status}</Badge><p>{item.message}</p></div>)}</div>}
    </section>
  );
}

function ResetDialog({ onCancel, onReset }: { onCancel: () => void; onReset: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const element = dialog.current!; element.showModal(); return () => element.close(); }, []);
  return <dialog ref={dialog} className="entry-dialog reset-dialog" aria-labelledby="reset-title" onCancel={onCancel}><span className="dialog-icon"><Icon name="reset" size={24} /></span><h2 id="reset-title">Reluăm demonstrația?</h2><p>Sesiunile și evenimentele din memorie vor fi înlocuite cu datele de exemplu.</p><div className="dialog-actions"><button className="button secondary" onClick={onCancel} autoFocus>Păstrează datele</button><button className="button primary" onClick={onReset}>Resetează demo</button></div></dialog>;
}
