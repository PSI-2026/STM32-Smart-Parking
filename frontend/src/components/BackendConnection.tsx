import { useEffect, useRef, useState } from 'react';
import { checkBackendHealth } from '../api/backendHealth';
import { Icon } from './Icon';
import './BackendConnection.css';

type ConnectionState =
  | { phase: 'idle' | 'checking' }
  | { phase: 'online'; version: string; checkedAt: number }
  | { phase: 'error'; message: string; checkedAt: number };

export function BackendConnection() {
  const [state, setState] = useState<ConnectionState>({ phase: 'idle' });
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  const check = async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setState({ phase: 'checking' });
    try {
      const health = await checkBackendHealth(controller.signal);
      if (!controller.signal.aborted) setState({ phase: 'online', version: health.version, checkedAt: Date.now() });
    } catch (error) {
      if (!controller.signal.aborted) setState({ phase: 'error', message: error instanceof Error ? error.message : 'Verificarea conexiunii a eșuat.', checkedAt: Date.now() });
    } finally {
      if (request.current === controller) request.current = null;
    }
  };

  return <div className={`backend-connection ${state.phase}`}>
    <div className="backend-connection-copy">
      <strong><Icon name="signal" size={15} />Backend API</strong>
      <div role="status" aria-live="polite" aria-atomic="true">
        <p>{state.phase === 'online' ? `Conexiune reușită · v${state.version}`
          : state.phase === 'error' ? state.message
            : state.phase === 'checking' ? 'Se verifică conexiunea…' : 'Conexiune neverificată'}</p>
        {'checkedAt' in state && <small>Ultimul test: {new Date(state.checkedAt).toLocaleTimeString('ro-RO')}</small>}
      </div>
      <small>Test API la cerere. Datele parcării rămân simulate local.</small>
    </div>
    <button className="button secondary small" onClick={() => void check()} disabled={state.phase === 'checking'}>
      {state.phase === 'checking' ? 'Se verifică…' : 'Testează conexiunea'}
    </button>
  </div>;
}
