import { useState } from 'react';
import type { CommandStatus, ParkingEvent, ParkingSnapshot } from '../api/types';
import { Icon } from './Icon';
import './Events.css';

const PAGE_SIZE = 8;
type LevelFilter = 'all' | ParkingEvent['level'];

const levels: { value: LevelFilter; label: string }[] = [
  { value: 'all', label: 'Toate nivelurile' },
  { value: 'info', label: 'Informații' },
  { value: 'success', label: 'Reușite' },
  { value: 'warning', label: 'Avertizări' },
];
const levelLabels = { info: 'Informație', success: 'Reușită', warning: 'Avertizare' };
const commandLabels: Record<CommandStatus, string> = {
  accepted: 'Acceptată', executing: 'În execuție', done: 'Finalizată', rejected: 'Respinsă', unknown: 'Necunoscută',
};
const eventTime = new Intl.DateTimeFormat('ro-RO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });

function searchText(value: string) {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('ro-RO').replace(/\s+/g, '');
}

export function Events({ snapshot, onExport }: { snapshot: ParkingSnapshot; onExport: () => void }) {
  const [query, setQuery] = useState('');
  const [level, setLevel] = useState<LevelFilter>('all');
  const [limit, setLimit] = useState(PAGE_SIZE);
  const events = snapshot.events.slice(0, 100);
  const needle = searchText(query);
  const filtered = events.filter((event) => (level === 'all' || event.level === level) && searchText(event.message).includes(needle));
  const visible = filtered.slice(0, limit);
  const hasFilters = query.trim() !== '' || level !== 'all';

  const resetFilters = () => { setQuery(''); setLevel('all'); setLimit(PAGE_SIZE); };

  return (
    <section className="panel events-panel" aria-labelledby="events-title">
      <div className="panel-heading">
        <div className="journal-heading-copy"><h2 id="events-title">Jurnal de evenimente</h2><p>{events.length} evenimente · ultimele 100 sunt păstrate în memorie</p></div>
        <button className="button secondary small" onClick={onExport} title="Exportă toate evenimentele și rezultatele comenzilor din memorie, indiferent de filtre."><Icon name="download" size={15} />Exportă JSON</button>
      </div>

      <div className="journal-toolbar" role="group" aria-label="Filtrare evenimente">
        <label className="journal-level-filter"><span>Nivel</span><select aria-label="Nivelul evenimentelor" value={level} onChange={(event) => { setLevel(event.target.value as LevelFilter); setLimit(PAGE_SIZE); }}>
          {levels.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select></label>
        <label className="search-field journal-search"><Icon name="search" size={17} /><input aria-label="Caută în evenimente" value={query} onChange={(event) => { setQuery(event.target.value); setLimit(PAGE_SIZE); }} placeholder="Caută mesaj, nod sau vehicul…" />{query && <button className="icon-button" aria-label="Șterge căutarea din jurnal" onClick={() => { setQuery(''); setLimit(PAGE_SIZE); }}><Icon name="close" size={14} /></button>}</label>
      </div>

      {visible.length > 0 ? <ol className="journal-list" aria-label="Evenimente filtrate">
        {visible.map((event) => <li key={event.id} className="journal-row">
          <span className={`journal-level ${event.level}`} role="img" aria-label={levelLabels[event.level]} title={levelLabels[event.level]}><Icon name={event.level === 'warning' ? 'alert' : event.level === 'success' ? 'check' : 'info'} size={14} /></span>
          <p className="journal-message">{event.message}</p>
          <time className="journal-time" dateTime={new Date(event.at).toISOString()} title={new Date(event.at).toLocaleString('ro-RO')}>{eventTime.format(event.at)}</time>
        </li>)}
      </ol> : <div className="journal-empty">
        <Icon name="list" size={24} /><strong>{hasFilters ? 'Niciun eveniment pentru filtrele alese' : 'Jurnalul este gol'}</strong>
        <p>{hasFilters ? 'Modifică termenul căutat sau nivelul evenimentelor.' : 'Acțiunile din simulator vor apărea aici.'}</p>
        {hasFilters && <button className="button secondary small" onClick={resetFilters}>Resetează filtrele</button>}
      </div>}

      <div className="journal-footer">
        <span role="status" aria-live="polite" aria-atomic="true">Afișate {visible.length} din {filtered.length} evenimente{hasFilters ? ` · ${events.length} în total` : ''}</span>
        <div className="journal-page-actions">
          {limit > PAGE_SIZE && filtered.length > PAGE_SIZE && <button className="button secondary small" onClick={() => setLimit(PAGE_SIZE)}>Restrânge lista</button>}
          {visible.length < filtered.length && <button className="button secondary small" onClick={() => setLimit((value) => value + PAGE_SIZE)}>Arată mai multe</button>}
        </div>
      </div>

      {snapshot.commands.length > 0 && <details className="journal-commands">
        <summary>Rezultate comenzi <span className="number-pill">{snapshot.commands.length}</span></summary>
        <ul className="journal-command-list" aria-label="Rezultatele comenzilor">
          {snapshot.commands.map((command) => <li key={command.commandId}>
            <div className="journal-command-heading"><code title={command.commandId}>{command.commandId.slice(0, 8)}</code><span className={`journal-command-status ${command.status}`}>{commandLabels[command.status]}</span></div>
            <p>{command.message}</p>
          </li>)}
        </ul>
      </details>}
    </section>
  );
}
