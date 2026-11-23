# Adaptoare MODBUS — pasul 6

Backend-ul implementează profilul țintă **distributed-v2.1 / 0x0201** din
[manifest](contracts/modbus-parking.v2.json). Firmware-ul actual nu este
considerat compatibil până la implementarea profilului și testarea pe STM32.
Nu există autodetecție prin scrieri sau fallback la registrele v2.0.

## Configurare

Instalați dependențele cu `uv sync --project backend --locked`.
Folosiți o bază separată de cea a simulatorului. Exemplu PowerShell TCP:

```powershell
$env:PARKING_MODE = 'hardware'
$env:PARKING_DATABASE_PATH = 'backend/data/hardware.sqlite3'
$env:PARKING_HARDWARE_ENABLED = 'true'
$env:PARKING_TRANSPORT = 'TCP'
$env:PARKING_MODBUS_HOST = '192.168.1.50'
$env:PARKING_MODBUS_PORT = '502'
uv run --project backend uvicorn app.main:app --app-dir backend
```

Pentru RTU prin USB/serial, înlocuiți configurația transportului:

```powershell
$env:PARKING_TRANSPORT = 'USB'
$env:PARKING_MODBUS_SERIAL_PORT = 'COM3'
$env:PARKING_MODBUS_BAUDRATE = '19200'
$env:PARKING_MODBUS_PARITY = 'N'
```

Serial: 8 biți, un stop bit; paritate N/E/O. TCP implicit 127.0.0.1:502;
serial implicit COM3, 19200, N. Timeout-ul per cerere este configurabil prin
`PARKING_MODBUS_TIMEOUT_SECONDS` (implicit 0.3, interval 0.05–2 secunde).
Worker-ul așteaptă `PARKING_WORKER_INTERVAL_SECONDS` între cicluri; timpul
ciclului include citirile serializate și timeout-urile. O singură instanță
backend trebuie să controleze magistrala. `HARDWARE_ENABLED` este implicit
false; în acest caz nu se deschide conexiunea, iar telemetria este necunoscută.
Health verifică disponibilitatea API-ului, nu compatibilitatea MCU.

## Citire și trimitere

- FC04 citește atomic 37 de registre de la 0x0300, direct la Unit ID
  G=247, S1=1 … S5=5. Nu este acceptat un cache de stații în gateway.
- Decoderul verifică identitatea, schema, dimensiunea, payload-ul și ecoul
  rezultatului. Măștile parțiale S1/S2 publică numai senzorii valizi;
  freeCount nu este folosit pentru capacitate. ledOutputMask folosește
  patru biți (0..15), inclusiv vectorul documentat [1, 1, 3, 6].
- Vârsta include RTT-ul și timpul până la publicarea întregului lot.
  Repetarea aceleiași secvențe nu întinerește eșantionul. Prima observație
  și reluarea după întrerupere stabilesc numai o bază de observație;
  doar avansul secvenței în același boot, în intervalul de prospețime,
  dovedește continuitatea. Repetarea bazei nu constituie progres.
  Wrap-ul cere și continuitate temporală demonstrată. După un wrap
  ambiguu se păstrează separat o secvență candidată, fără a înlocui ancora
  acceptată. Un avans al candidatului în același boot și înainte de expirare
  permite reluarea; repetarea candidatului nu este suficientă. Aceeași regulă
  este aplicată în adaptor și SQLite; candidații nu dovedesc continuitatea
  între runtime-uri. Istoricul
  persistent al serviciului verifică suplimentar ordinea și continuitatea.
  Repetarea aceleiași perechi boot/secvență păstrează ancora inițială, chiar
  după expirare sau întrerupere. Când candidatul a expirat, o secvență distinctă
  devine noua bază; încă un avans este necesar pentru reluare.
- O cale gateway invalidă invalidează stațiile și senzorii dependenți.
  Datele lipsă sunt null/UNKNOWN, niciodată locuri libere implicite.
  Stațiile declarate offline în masca gateway-ului nu sunt interogate.
  Timeout-ul unei stații invalidează numai istoricul ei; o eroare la G
  invalidează toate căile. Închiderea preventivă a conexiunii după un
  timeout de stație nu șterge dovezile încă recente ale celorlalte noduri.
- Worker-ul salvează `sent` înainte de I/O, apoi adaptorul revalidează
  identitatea, boot-ul, prospețimea și calea. FC06 HR4=1 și FC16 HR256
  cu nouă cuvinte sunt adresate aceleiași stații S3 sau S4.
- PyModbus are retries=0; o protecție la emiterea PDU blochează și o a doua
  scriere în aceeași operație a bibliotecii. Timeout-ul exterior limitează
  cererile; o eroare de comunicație închide conexiunea înainte de reutilizare.
- După timeout sau restart se citește numai rezultatul blocului original.
  Nodul, boot-ul curent și cel din record, ID-ul și toate cele nouă cuvinte
  trebuie să coincidă. Alt record sau lipsa lui înseamnă unknown.
  Reconcilierea folosește același istoric de boot, secvență și vârstă ca
  polling-ul și revalidarea înainte de scriere. Observațiile gateway și
  stație trebuie să fie recente și continue; o regresie la un boot vechi
  rămâne unknown. Vârsta eșantionului dovedește actualitatea observației
  și a căii, nu vârsta recordului: ultimul rezultat poate rămâne stocat
  oricât, cât timp este returnat în observații curente validate.
  Worker-ul încarcă limitele de boot din SQLite înainte de polling, iar
  aplicarea unui rezultat verifică din nou limita persistentă a stației în
  aceeași tranzacție cu efectele asupra sesiunii/claim-ului. Un adaptor nou
  după restart nu poate elibera claim-ul printr-un refuz dintr-un boot vechi.
  Limita de identitate se salvează separat în metadata imediat după decodarea
  fiecărui cadru coerent, printr-un callback atașat de worker, înainte ca
  adaptorul să continue polling-ul/reconcilierea. Commit-ul nu așteaptă
  progresul secvenței sau publicarea unui snapshot valid. SQLite păstrează
  distinct istoricul de prospețime; o limită de boot nu declară senzorii valizi.
  Fiecare citire a cache-ului verifică limita în aceeași tranzacție cu
  snapshot-ul, capacitatea sau operația de business. Un boot depășit
  invalidează imediat nodul și senzorii săi; un boot depășit la G invalidează
  toate căile dependente, fără a aștepta următorul polling.
  Reconcilierea și submit verifică gateway-ul și masca offline înainte de
  FC04 către stația țintă; o stație offline nu adaugă un timeout de citire.
  Nu se retrimite automat și nu se creează un ID înlocuitor.
- Operațiile SQLite se execută separat de I/O. O eroare la o comandă nu
  anulează comenzile independente deja salvate.

## Limita confirmării fizice

Profilul v2.1 nu oferă dovadă de trecere. `read_passage()` raportează
unavailable. Chiar un rezultat MCU done lasă rezultatul de business unknown,
sesiunea în așteptare și claim-ul held. Nu se deduce trecerea din poziția
barierei, prezență sau ocuparea unui senzor. Reconcilierea manuală auditată
și un viitor profil cu dovadă hardware nu sunt expuse de API v1.

## Verificare

`test_modbus.py` folosește un server TCP local cu cadre MODBUS reale,
inclusiv răspuns pierdut după FC16, ambele benzi, versiune incompatibilă,
validitate parțială, eșantion înghețat și integrarea worker/SQLite.
Aceleași fluxuri sunt verificate cu ADU RTU și CRC pe un flux TCP local;
acesta verifică framing-ul RTU, **nu driverul serial sau portul fizic**.
Fabrica serial este verificată separat fără deschiderea unui dispozitiv.

Pe hardware mai trebuie verificate registrele și atomicitatea firmware,
rutarea Unit ID, configurația serială/cablarea, lease-ul la stația țintă,
deconectarea/reconectarea și un timeout produs după executarea FC16.
Suita locală nu înlocuiește aceste verificări.

Biblioteca de transport: [documentația oficială PyModbus](https://pymodbus.readthedocs.io/en/latest/source/client.html).
Versiunile instalate sunt fixate în `uv.lock` (PyModbus 3.16.2, pyserial 3.5).
