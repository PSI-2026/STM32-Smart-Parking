import { getBarrierState, getOccupancy, isNodeAvailable } from '../api/selectors';
import type { ParkingAction, ParkingSession, ParkingSnapshot } from '../api/types';
import { duration, money, time } from '../lib/format';
import { Icon } from './Icon';

const labels: Record<ParkingSession['status'], string> = {
  pending_entry: 'Intrare în așteptare', active: 'Neplătit', paid: 'Plătit · demo',
  pending_exit: 'Ieșire în așteptare', completed: 'Încheiată', cancelled: 'Anulată',
};

export function SessionsPanel({ snapshot, search, setSearch, filter, setFilter, pending, send }: {
  snapshot: ParkingSnapshot; search: string; setSearch: (value: string) => void;
  filter: 'active' | 'all'; setFilter: (value: 'active' | 'all') => void;
  pending: boolean; send: (action: ParkingAction) => Promise<boolean>;
}) {
  const sessions = snapshot.sessions.filter(session => (filter === 'all' || !['completed', 'cancelled'].includes(session.status))
    && session.plate.toLowerCase().includes(search.trim().toLowerCase()));
  const barrier = snapshot.barriers.find(item => item.id === 'exit')!;
  const canExit = (session: ParkingSession) => !pending && session.status === 'paid' && snapshot.apiConnection === 'online'
    && isNodeAvailable(snapshot, 'S4') && getBarrierState(snapshot, barrier) === 'CLOSED'
    && barrier.obstacle === false && getOccupancy(snapshot).unknown === 0;
  return <section className="panel sessions-panel" aria-labelledby="sessions-title">
    <div className="panel-heading sessions-heading">
      <div className="sessions-heading-copy">
        <h2 id="sessions-title" tabIndex={-1}>Sesiuni de parcare</h2>
        <p>Tarif backend: {snapshot.mode === 'unknown' ? '—' : money(snapshot.hourlyRateBani)} / oră. Plata este simulată.</p>
      </div>
      <div className="sessions-toolbar">
        <div className="segmented-control" aria-label="Filtrare sesiuni">
          <button aria-pressed={filter === 'active'} onClick={() => setFilter('active')}>Curente</button>
          <button aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>Sesiuni primite</button>
        </div>
        <label className="search-field"><Icon name="search" size={17} />
          <input aria-label="Caută număr de înmatriculare" value={search} onChange={event => setSearch(event.target.value)} placeholder="Caută un număr…" />
        </label>
      </div>
    </div>
    <div className="table-scroll"><table><thead><tr><th>VEHICUL</th><th>LOC</th><th>INTRARE / DURATĂ</th><th>TAXĂ SIMULATĂ</th><th>STARE</th><th>ACȚIUNE</th></tr></thead>
      <tbody>{sessions.map(session => <tr key={session.id}>
        <td><span className="plate"><span className="plate-eu">RO</span>{session.plate}</span></td>
        <td>{session.slotId === null ? 'Neatribuit' : `P0${session.slotId}`}</td>
        <td>{time(session.enteredAt)}<div className="table-sub">{duration(session.enteredAt, session.exitedAt ?? snapshot.updatedAt)}</div></td>
        <td>{money(session.amountDueBani)}</td>
        <td><span className="badge">{labels[session.status]}</span></td>
        <td>{session.status === 'active'
          ? <button className="button small secondary" disabled={pending || snapshot.apiConnection !== 'online'}
            onClick={() => void send({ type: 'pay', sessionId: session.id })}>Plată demo</button>
          : session.status === 'paid'
            ? <button className="button small exit-button" disabled={!canExit(session)}
              onClick={() => void send({ type: 'exit', sessionId: session.id })}>Autorizează ieșirea</button>
            : <span>{session.status === 'completed' ? time(session.exitedAt) : labels[session.status]}</span>}</td>
      </tr>)}</tbody>
    </table>{sessions.length === 0 && <div className="empty-state"><strong>Nicio sesiune disponibilă</strong><p>Sunt afișate sesiunile furnizate în snapshot-ul backendului.</p></div>}</div>
    <div className="table-footer">Tariful și soldul sunt calculate de backend. Istoricul închis este disponibil separat prin API-ul paginat.</div>
  </section>;
}
