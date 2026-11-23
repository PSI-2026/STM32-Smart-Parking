# Simulator backend — pasul 5

Simulatorul este activ implicit în `PARKING_MODE=simulation`. Folosește
aceleași rute și reguli de business ca integrarea hardware. Nu necesită
placă, Renode, port serial sau frontend. Nu există plăți bancare reale.

## Pornire și flux

Comanda de pornire rămâne cea din [README.md](README.md). La prima pornire,
parcarea are patru locuri libere, două bariere închise și toate nodurile
virtuale online. Nu sunt create vehicule sau plăți fictive.

1. Trimite `enter` prin POST `/api/v1/commands`, cu ID unic și plate.
2. Urmărește GET `/api/v1/commands/{commandId}` până la done. Răspunsul
   include sessionId. Simulatorul deschide bariera, produce o dovadă
   explicită de trecere și parchează pe primul loc liber neasociat.
3. Trimite `pay` cu sessionId; soldul este achitat și locul rămâne ocupat.
4. Trimite `exit` cu sessionId. Dovada explicită închide sesiunea, iar
   evenimentul corelat al senzorului confirmă locul liber.

Deschiderea, trecerea și închiderea sunt etape separate. După done, bariera
poate fi încă CLOSING; pentru un nou acces pe aceeași bandă așteaptă CLOSED
în snapshot. O comandă nouă primită prea devreme poate fi refuzată prin
INTERLOCK_ACTIVE. Plata lipsă sau parcarea plină produc refuzuri persistente.
Replay-ul aceluiași ID nu creează alt vehicul, altă plată sau altă trecere.

## Configurație

| Variabilă | Implicit | Comportament |
| --- | --- | --- |
| PARKING_SIMULATOR_ENABLED | true | Activează simulatorul numai în modul simulation. |
| PARKING_SIMULATOR_STEP_DELAY_MS | 200 | 50–10000 ms pentru fiecare etapă a barierei. |
| PARKING_SIMULATOR_AUTO_PASSAGE | true | Driverul virtual produce evenimente explicite de trecere. false lasă vehiculul în așteptare. |
| PARKING_WORKER_INTERVAL_SECONDS | 0.1 | Rezoluția actualizărilor; intervalele lungi pot expira telemetria. |

Cu simulator_enabled=false se păstrează comportamentul API fără adaptor:
date necunoscute, fără dispatch. În hardware, simulatorul nu este atașat,
chiar dacă simulator_enabled este true. Selectarea TCP/USB în demo este
o etichetă de transport virtual, nu deschide conexiuni fizice.

## Controale prin acțiunile existente

Toate controalele sunt comenzi persistente, cu commandId și action:

| action.type | Parametri | Efect |
| --- | --- | --- |
| set-slot-sensor | slotId, occupied | Modifică un senzor fizic virtual, fără sesiune/plată. |
| set-all-slot-sensors | occupied | Modifică numai cei patru senzori. |
| set-node-online | nodeId, online | Deconectează/reconectează un nod virtual. |
| set-obstacle | barrierId, active | Blochează mișcarea și trecerea pe acea bandă. |
| set-barrier-presence | barrierId, present | Modifică prezența; nu deschide bariera și nu confirmă trecerea. |
| set-transport | transport | TCP/USB raportat în snapshot și păstrat la restart. |

Pierderea S1/S2 face locurile dependente necunoscute. Pierderea G face
toată telemetria dependentă necunoscută. Reconectarea cere progres real
al secvențelor virtuale, nu doar comutarea etichetei online.

Un obstacol împiedică progresul temporizat; eliminarea lui permite
continuarea dacă nu s-au pierdut observațiile și sesiunea este reconciliată.
Un nod deconectat în timpul unui acces neconfirmat produce lost/unknown
în tranzacția care aplică deconectarea, chiar dacă o comandă online urmează
în același lot. Reconectarea restabilește numai comunicația, nu trecerea.
Citirea rezultatului și replay-ul blocului abandonat rămân unknown, iar
read_passage rămâne lost. Înregistrarea unei alte cereri cu alt bloc nu
este ștearsă la abandonarea originalului. Claim-ul rămâne activ. Schimbările
manuale de ocupare în timp ce există claims pot introduce ambiguitate și
blochează capacitatea, conform contractului. Resetarea datelor și
reconcilierea operatorului nu sunt expuse în API v1.

## Persistență și atomicitate

Schema SQLite v3 migrează din v1/v2 și adaugă simulator_state și
simulator_commands. Ocuparea, nodurile, barierele și transportul sunt
persistente. Un simulator nou nu inventează o parcare goală peste o bază
veche cu sesiuni și fără stare virtuală; acea combinație este refuzată.
Pentru pornirea unui demo separat se configurează o altă bază prin
PARKING_DATABASE_PATH, fără ștergerea istoricului existent.

Fiecare ciclu virtual este o unitate de lucru SQLite. Avansarea fiecărui
acces are un SAVEPOINT dedicat: modificarea lumii pentru acea trecere,
dovada, sesiunea și transferul claim-ului se salvează împreună. O excepție
după generarea trecerii anulează numai acel acces, inclusiv ocuparea
virtuală. După rollback, accesul este marcat lost/unknown și bariera FAULT,
fără dovadă consumată sau claim eliberat. Comenzile independente deja
procesate și cealaltă bandă pot progresa în același ciclu; accesul pierdut
nu este reîncercat automat în fiecare ciclu.

Apelurile imbricate folosesc aceeași conexiune per thread și SAVEPOINT,
fără promovarea unui snapshot read-only la writer. Nu poate rămâne un
claim consumat cu un senzor persistent artificial liber. O eroare globală
a bazei poate necesita în continuare rollback-ul tranzacției exterioare.

Tranzacția exterioară este permisă numai pentru simulatorul CPU/SQLite,
fără await sau I/O fizic. Driverele reale trebuie să păstreze limita
claim_dispatch commit înainte de I/O; nu se includ în această unitate.

La restart se incrementează bootEpoch virtual, iar comenzile neterminate
nu sunt retrimise și nu generează dovezi noi. Sesiunile, plățile și ocuparea
deja confirmate se păstrează. O închidere locală rămasă după o trecere
salvată poate fi finalizată la startup fără obstacol; un acces neconfirmat
rămâne FAULT/unknown și cere reconciliere.

SimulatedDeviceAdapter oferă metodele async ale DeviceAdapter și puncte
sincrone pentru coordinator. Citește ultima înregistrare observabilă,
corelează nod/boot/ID/bloc și deduplică cererile fără a reporni temporizarea.
Un ID cu alt bloc este refuzat; rezultatul lui nu este atribuit originalului.
Secvențele și nodurile sunt virtuale; nu demonstrează existența a cinci MCU.

## Verificare

```sh
uv run --project backend --frozen python -B -m unittest discover -s backend/tests -v
uv run --project backend --frozen python -B backend/scripts/export_contracts.py --check
```

Testele includ un flux complet HTTP/ASGI cu worker real, fără injectarea
telemetriei sau dovezilor, și replay după redeschiderea aplicației.
Cu ceas controlat se verifică temporizarea, obstacolele, validitatea
parțială, pierderea nodurilor, cele patru locuri, două benzi simultane,
deduplicarea, rollback-ul și restartul în mijlocul accesului. Acestea
nu sunt teste de integrare cu hardware sau cu frontend-ul React.
