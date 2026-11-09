export const money = (bani: number) => new Intl.NumberFormat('ro-RO', {
  style: 'currency', currency: 'RON', maximumFractionDigits: 2,
}).format(bani / 100);

export const time = (timestamp: number) => new Intl.DateTimeFormat('ro-RO', {
  hour: '2-digit', minute: '2-digit',
}).format(timestamp);

export function duration(start: number, end: number) {
  const minutes = Math.floor(Math.max(0, end - start) / 60_000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min` : `${minutes} min`;
}
