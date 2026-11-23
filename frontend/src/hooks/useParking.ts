import { useSyncExternalStore } from 'react';
import { parkingApi } from '../api';

export function useParking() {
  const snapshot = useSyncExternalStore(parkingApi.subscribe, parkingApi.getSnapshot);

  return snapshot;
}
