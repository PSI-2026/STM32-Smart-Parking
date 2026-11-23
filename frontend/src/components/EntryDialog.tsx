import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Icon } from './Icon';

export function EntryDialog({ onClose, onEnter, pending, blocked = false }: {
  onClose: () => void;
  onEnter: (plate: string) => Promise<boolean>;
  pending: boolean;
  blocked?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const plateInput = useRef<HTMLInputElement>(null);
  const [plate, setPlate] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    plateInput.current?.focus();
    return () => element.close();
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    if (await onEnter(plate)) onClose();
    else setError('Intrarea nu a fost confirmată. Verifică mesajul și starea sistemului.');
  }
  return <dialog ref={dialog} className="entry-dialog" aria-labelledby="entry-title" onCancel={(event) => { if (pending) event.preventDefault(); else onClose(); }}>
    <div className="dialog-heading"><span className="dialog-icon"><Icon name="car" size={25} /></span><button className="icon-button" aria-label="Închide formularul" onClick={onClose} disabled={pending}><Icon name="close" /></button></div>
    <p className="eyebrow">ACCES ÎN PARCARE</p>
    <h2 id="entry-title">Un nou început de sesiune.</h2>
    <p>Introdu numărul vehiculului. Backend-ul verifică disponibilitatea și autorizează accesul.</p>
    <form onSubmit={submit}>
      <label htmlFor="plate">Număr de înmatriculare</label>
      <input ref={plateInput} id="plate" className="plate-input" value={plate} onChange={(event) => setPlate(event.target.value.toUpperCase())} placeholder="B 123 DEM" minLength={3} maxLength={15} pattern="[A-Za-z0-9][A-Za-z0-9 \-]{1,13}[A-Za-z0-9]" required autoComplete="off" disabled={pending} aria-describedby="plate-hint entry-error" />
      <small id="plate-hint">3–15 caractere; litere, cifre, spații sau cratimă.</small>
      {error && <p id="entry-error" className="form-error" role="alert">{error}</p>}
      <div className="dialog-note"><Icon name="info" size={17} /><span>Comanda este trimisă backendului. În modul hardware poate acționa bariera fizică. Plata este simulată.</span></div>
      <button className="button primary dialog-submit" disabled={pending || blocked}>{pending ? 'Se confirmă intrarea…' : 'Autorizează intrarea'}<Icon name="arrow" size={18} /></button>
    </form>
  </dialog>;
}
