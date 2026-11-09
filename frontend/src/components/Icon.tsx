import type { CSSProperties } from 'react';

const paths = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.6" /><rect x="14" y="3" width="7" height="7" rx="1.6" /><rect x="3" y="14" width="7" height="7" rx="1.6" /><rect x="14" y="14" width="7" height="7" rx="1.6" /></>,
  car: <><path d="m5 10 2-6h10l2 6M4 10h16v8H4zM7 18v2m10-2v2M7 14h1m8 0h1" /></>,
  chip: <><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 1v5m6-5v5M9 18v5m6-5v5M1 9h5m-5 6h5m12-6h5m-5 6h5" /><rect x="9" y="9" width="6" height="6" rx="1" /></>,
  list: <><path d="M8 5h12M8 12h12M8 19h12M3 5h.01M3 12h.01M3 19h.01" /></>,
  arrow: <><path d="M5 12h14m-6-6 6 6-6 6" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  reset: <><path d="M3 10a9 9 0 1 1 2 8M3 4v6h6" /></>,
  signal: <><path d="M3 18h2m3-5v5m4-9v9m4-13v13m4-17v17" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  wallet: <><path d="M20 8V5H5a2 2 0 0 0 0 4h15v11H5a2 2 0 0 1-2-2V7" /><path d="M20 12h-6v4h6" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  alert: <><path d="m12 3 10 17H2L12 3zM12 9v4m0 3h.01" /></>,
  download: <><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" /></>,
  search: <><circle cx="10" cy="10" r="6" /><path d="m15 15 5 5" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10h.01" /></>,
};

export type IconName = keyof typeof paths;

export function Icon({ name, size = 20, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>{paths[name]}</svg>;
}

export function CarTop({ occupied }: { occupied: boolean }) {
  return <svg className={`car-top ${occupied ? '' : 'car-ghost'}`} viewBox="0 0 64 112" aria-hidden="true">
    <rect x="5" y="24" width="5" height="14" rx="2" fill="#3e5149" /><rect x="54" y="24" width="5" height="14" rx="2" fill="#3e5149" />
    <rect x="9" y="4" width="46" height="104" rx="17" fill="currentColor" />
    <path d="m17 25 4-8h22l4 8 1 17H16l1-17ZM16 78h32l-3 17H19l-3-17Z" fill="#e5eee9" />
    <rect x="18" y="46" width="28" height="28" rx="5" fill="#fff" opacity=".15" />
    <path d="M13 48v27m38-27v27M16 10l7-2m18 0 7 2M17 102h7m16 0h7" fill="none" stroke="#c6d5cc" strokeWidth="3" strokeLinecap="round" />
  </svg>;
}
