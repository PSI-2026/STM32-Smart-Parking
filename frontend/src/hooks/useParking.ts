import { useEffect, useSyncExternalStore } from 'react';
import { parkingApi } from '../api';

export function useParking() {
  const snapshot = useSyncExternalStore(parkingApi.subscribe, parkingApi.getSnapshot);

  useEffect(() => {
    const timer = window.setInterval(parkingApi.refresh, 500);
    return () => window.clearInterval(timer);
  }, [parkingApi]);

  return snapshot;
}
