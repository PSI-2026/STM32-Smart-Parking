export interface BackendHealth {
  status: 'healthy';
  service: 'smart-parking-backend';
  version: string;
}

class HealthCheckError extends Error {}

/** Only checks HTTP connectivity; parking data still comes from the local simulator. */
export async function checkBackendHealth(signal?: AbortSignal): Promise<BackendHealth> {
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), 5_000);
  try {
    const response = await fetch('/api/v1/health', {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      signal: signal ? AbortSignal.any([signal, timeout.signal]) : timeout.signal,
    });
    if (!response.ok) throw new HealthCheckError(`Backend indisponibil (HTTP ${response.status}). Verifică dacă serverul este pornit.`);

    let data: unknown;
    try { data = await response.json(); }
    catch { throw new HealthCheckError('Backend-ul nu a returnat un răspuns JSON valid. Verifică adresa API.'); }

    if (typeof data !== 'object' || data === null
      || !('status' in data) || data.status !== 'healthy'
      || !('service' in data) || data.service !== 'smart-parking-backend'
      || !('version' in data) || typeof data.version !== 'string' || !data.version.trim()) {
      throw new HealthCheckError('Răspunsul nu confirmă starea healthy a serviciului Smart Parking.');
    }
    return { status: 'healthy', service: 'smart-parking-backend', version: data.version };
  } catch (error) {
    if (signal?.aborted) throw error;
    if (timeout.signal.aborted) throw new HealthCheckError('Backend-ul nu a răspuns în 5 secunde. Reîncearcă verificarea.');
    if (error instanceof HealthCheckError) throw error;
    throw new HealthCheckError('Conexiunea cu backend-ul a eșuat. Verifică dacă serverul este pornit.');
  } finally {
    clearTimeout(timer);
  }
}
