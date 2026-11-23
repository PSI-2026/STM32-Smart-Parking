import { useState } from 'react';
import { parkingApi } from '../api';
import type { ParkingSnapshot } from '../api/types';

export function ApiAccess({ snapshot }: { snapshot: ParkingSnapshot }) {
  const [token, setToken] = useState('');
  return <section className="panel api-access" aria-label="Acces backend">
    <form onSubmit={event => { event.preventDefault(); parkingApi.setAccessToken(token); setToken(''); }}>
      <label htmlFor="access-token">Token de acces</label>
      <input id="access-token" type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} />
      <button className="button secondary small" type="submit">Conectează API</button>
      <button className="button secondary small" type="button" onClick={() => parkingApi.setAccessToken('')}>Deconectează API</button>
    </form>
    <p role="status">{snapshot.apiConnection === 'online' ? 'API conectat · date furnizate de backend'
      : snapshot.apiMessage ?? 'Se așteaptă datele backendului. Introdu tokenul de acces dacă este necesar.'}</p>
  </section>;
}
