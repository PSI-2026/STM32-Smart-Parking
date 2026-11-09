import { useEffect, useRef } from 'react';
import type { ParkingAction, ParkingSnapshot } from '../api/types';
import { Icon } from './Icon';
import { SensorSimulation } from './SensorSimulation';
import './SensorDrawer.css';

interface SensorDrawerProps {
  snapshot: ParkingSnapshot;
  pending: boolean;
  onAction: (action: ParkingAction) => Promise<boolean>;
  onClose: () => void;
}

export function SensorDrawer({ onClose, ...sensorProps }: SensorDrawerProps) {
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const element = dialog.current!;
    const opener = document.activeElement;
    element.showModal();
    return () => {
      element.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialog}
      id="sensor-drawer"
      className="sensor-drawer"
      aria-labelledby="quick-sensor-title"
      onCancel={onClose}
    >
      <button className="icon-button sensor-drawer-close" aria-label="Închide simularea senzorilor" onClick={onClose}>
        <Icon name="close" size={21} />
      </button>
      <SensorSimulation {...sensorProps} headingId="quick-sensor-title" />
    </dialog>
  );
}
