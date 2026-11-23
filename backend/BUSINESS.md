# Persistență și reguli de business — pasul 3

Implementarea este în `app/storage.py`, `app/telemetry.py` și `app/parking.py`. Ea poate fi
testată independent de HTTP și hardware. Rutele și worker-ul sunt conectate
în pasul 4, descris în [API.md](API.md); simulatorul este conectat în pasul 5,
transporturile în pasul 6. Nu există I/O MODBUS în tranzacții.

## Inițializare

Din cod Python executat cu directorul curent `backend`:

```python
from app.storage import Database
from app.parking import ParkingService

database = Database("data/parking.sqlite3")
service = ParkingService(database, mode="simulation", hourly_rate_bani=500)
service.recover()  # o singură dată la startup, înainte de worker și cereri
```

`Database` creează schema curentă v3, verificată prin `PRAGMA user_version`.
Migrarea tranzacțională din v1 adaugă istoricul independent al telemetriei
și marcajele persistente de contradicție/refuz. Datele existente se păstrează;
refuzurile și contradicțiile demonstrabile din ultimul rezultat v1 sunt
preluate în marcajele noi.
Migrarea v2→v3 adaugă starea și comenzile simulatorului, fără a modifica
sesiunile sau plățile existente.
O versiune necunoscută este refuzată; nu se șterg sau reinițializează datele.
SQLite folosește WAL, foreign keys, synchronous FULL și busy timeout 5 s.
Fiecare unitate de lucru exterioară are o conexiune proprie și `BEGIN IMMEDIATE`;
citirile au tranzacții scurte. Tranzacțiile nu sunt ținute peste `await`
sau cereri de rețea. Nu sunt necesare dependențe suplimentare.
În pasul 5, apelurile imbricate ale simulatorului CPU/SQLite partajează
conexiunea per thread și folosesc SAVEPOINT. Un context read-only nu poate
fi promovat la scriere. Nu se folosesc aceste tranzacții exterioare pentru
I/O fizic sau await.

Se rulează **un singur proces de control**, fără mai mulți worker-i Uvicorn
asupra aceluiași dispozitiv. În interiorul procesului, thread-urile pot
utiliza aceeași instanță Database/ParkingService; SQLite serializează
operațiile de scriere. Înregistrarea modului în DB împiedică deschiderea
aceleiași baze în alt mod; pentru hardware se folosește o bază separată.

Persistă: comenzi/acțiuni normalizate, sesiuni și plăcuțe, claims, plăți
simulate, mapări MCU și contoare, dovezi consumate, evenimente și ultima
telemetrie. Vehiculul este identificat prin numărul normalizat din sesiuni;
nu există încă un registru separat de proprietari sau metadate vehicul.
`backend/data/`, bazele SQLite și sidecar-urile sunt ignorate de Git.

## Admitere și procesare

1. `admit(CommandRequest)` normalizează acțiunea și salvează ID-ul înaintea
   verificărilor operaționale. Returnează `Admission(result, replayed)`.
   Replay-ul identic nu schimbă datele; alt conținut produce
   `BusinessFault(IDEMPOTENCY_CONFLICT)`. Nu se uită ID-urile la restart.
2. `process(commandId)` operează numai pe accepted. Un savepoint delimitează
   efectele de business: un refuz anulează efectele parțiale, dar salvează
   rezultatul rejected și evenimentul. O eroare SQLite neașteptată face
   rollback la întreaga procesare, păstrând admiterea anterioară accepted.
3. Intrarea verifică datele curente, interblocarea, sesiunea duplicată și
   capacitatea. Sesiunea pending_entry, claim-ul și comanda MCU sunt create
   atomic. Ieșirea cere paid și trece în pending_exit. Plata se finalizează
   atomic fără comandă de dispozitiv.

Un număr de înmatriculare are cel mult o sesiune neînchisă, garantat și prin
index unic. Un loc are cel mult o asociere activă. Modul hardware refuză
acțiunile demo prin rezultat persistent SIMULATION_ONLY. În simulation,
procesarea acțiunilor demo este atașată de SimulatorRuntime în pasul 5.
Fără simulator activ, metoda ridică NotImplementedError, iar worker-ul
exclude aceste acțiuni; admiterea rămâne accepted, fără efecte parțiale.

`BusinessFault.detail` folosește codurile ErrorDetail aprobate; adaptorul
HTTP va traduce excepțiile apărute înainte de admitere în ApiError. Refuzul
operațional după admitere se citește din CommandResult, nu ca eroare HTTP.

## Limita de I/O și recuperarea după restart

`process()` salvează maparea exactă ID API → nod/boot/ID u32/bloc, cu
send_state=prepared. `get_device_command()` recuperează acea mapare pentru
reconciliere. `claim_dispatch()` revalidează calea, boot-ul, bariera și
capacitatea, apoi salvează sent **înainte** de I/O și returnează comanda
o singură dată. Numai apelantul care primește comanda poate iniția I/O.
Repetarea metodei returnează None, nu retrimite.

Aceasta prioritizează evitarea unei deschideri duplicate: o întrerupere
între marcarea sent și scrierea efectivă poate lăsa o comandă incertă chiar
dacă nu a ajuns pe fir. La imposibilitatea revalidării înainte de trimitere
se păstrează conservator unknown și claim-ul. Nu se pretinde execuție
fizică exact o dată. Firmware-ul verifică separat lease-ul și interblocările.

`record_device_result()` verifică identitatea și ecoul complet față de
maparea persistentă și refuză rezultate simulation în hardware. Un refuz
preexecuție demonstrat anulează sesiunea pending_entry și claim-ul sau
readuce pending_exit în paid. Dacă s-a observat anterior progres MCU sau
un rezultat care poate implica execuție (done/failed/expired), o înregistrare
ulterioară rejected este contradictorie. Ordinea inversă (rejected urmat
de progres) este de asemenea contradictorie, chiar dacă API-ul avea deja
un rezultat terminal. `progress_seen`, `refusal_seen` și `contradiction`
sunt independente de ultimul rezultat. Contradicția nu se șterge prin alt
accepted/done, restart sau snapshot nou. Ea pune comanda în unknown și
îngheață capacitatea globală prin reconciliationRequired. Nicio nouă
trecere, contabilizare, plată sau ieșire pentru acea sesiune nu o rezolvă
automat. Dacă primul refuz eliberase deja claim-ul și anulase sesiunea,
nu se reactivează pe ascuns sesiunea istorică: capacitatea rămâne null
până la reconciliere explicită. Dovezile și tranzacțiile confirmate înainte
de apariția contradicției nu sunt rescrise retroactiv.

Blocarea se verifică pe toate comenzile legate de sesiune, nu numai pe
comanda curentă. Se revalidează în tranzacția de dispatch înainte de sent,
la consumul dovezii, înaintea normalizării pentru contabilizare și înainte
ca un rezultat MCU al altei comenzi să modifice sesiunea. O ieșire pregătită
înaintea contradicției intrării nu poate ocoli verificarea. Rezultatele
dispozitivului pot fi salvate pentru diagnostic, dar nu dezgheață sesiunea.

Timeout-ul, failed, expired și done fără dovadă de trecere nu finalizează
accesul. `recover()` diferențiază două cazuri:

- `prepared`: baza dovedește că intenția de trimitere nu a fost salvată.
  Comanda executing/unknown este anulată atomic cu rezultat rejected;
  intrarea pending este cancelled și claim-ul held eliberat, iar ieșirea
  pending revine la paid. Maparea și ID-ul numeric rămân în istoric.
  Aceeași comandă nu se trimite; o intenție nouă poate fi admisă după
  obținerea datelor proaspete, fără blocarea permanentă a barierei.
- `sent`: trimiterea poate fi în curs sau efectuată. Comanda executing
  devine unknown; rezervările rămân și nu se inițiază retrimitere automată.

Dacă sesiunea are deja o contradicție pe oricare comandă, recuperarea
poate anula comanda prepared sigur netrimisă, dar nu modifică automat
starea sesiunii sau claim-ul. Astfel, anularea unei ieșiri prepared nu
readuce în paid o sesiune înghețată din cauza intrării contradictorii.

Recuperarea șterge cache-ul public de telemetrie, păstrează istoricul per
nod și îi invalidează continuitatea. Comenzile accepted
rămân disponibile prin `pending_commands()`; nu au avut efecte de business
parțiale. Recuperarea nu emite I/O și nu se apelează pentru fiecare request.

## Dovezi, ocupare și capacitate

`consume_passage()` cere o mapare sent, progres MCU neconflictual, acțiunea
enter/exit corectă și dovada explicită pentru același nod/boot/ID/bloc.
Verifică modul, timpul între trimitere și prezent și starea sesiunii. ID-ul
dovezii, tranziția sesiunii, rezultatul comenzii și evenimentul sunt salvate
în aceeași tranzacție. Același ID și conținut sunt no-op; un ID cu alt
conținut este refuzat. O a doua dovadă nu repetă tranziția. Hardware v2.1
nu poate furniza momentan o trecere confirmed, conform contractului.

După intrare, claim-ul rămâne held și session.slotId poate fi null.
`account_occupancy()` este o limită **internă de încredere pentru simulator**,
nu un endpoint public. Ea primește un eveniment corelat, o sesiune intrată,
un loc anterior liber și telemetria în care numai acel loc devine ocupat.
Înaintea oricărei mutații de business se aplică regulile istoricului de
secvențe, vârstei și căii. Se verifică snapshot-ul efectiv salvat în
tranzacție, nu doar DTO-ul primit; el trebuie să demonstreze în continuare
ocuparea validă. Consumul claim-ului, asocierea și actualizarea senzorului
sunt atomice și deduplicate prin evidenceId. Orice eșec anulează și
actualizarea candidatului/istoricului, fără consum de claim sau dovadă.
Funcția nu este permisă în modul hardware sau pentru o intrare cu
contradicție MCU persistentă.

`ingest_telemetry()` nu inventează asocieri sau treceri. Dacă o modificare
necorelată sau o întrerupere a observațiilor întâlnește claims held,
reconciliationRequired rămâne persistent și available=null. Nici o
diferență netă ulterioară, nici contabilizarea altui loc nu șterg automat
acea ambiguitate. Reconcilierea operatorului rămâne o operație auditată
separată, neexpusă în API v1; nu se șterge DB ca mecanism de recuperare.

Capacitatea folosește senzorii valizi și claims held, nu numărul sesiunilor.
Confirmarea unei ieșiri eliberează un claim încă held (vehiculul intrat,
dar încă neparcat); un loc fizic ocupat rămâne ocupat până la senzor.

## Telemetrie și timp

Telemetria se revalidează la ingestie și se îmbătrânește monoton la citire,
cu invalidarea copiilor dependente de gateway/stație. `telemetry_history`
păstrează separat, per nod, boot-ul și secvența cele mai recente, payload-ul,
vârsta la ancoră și timpul monoton. Un snapshot unavailable cu identitate
null nu șterge aceste date. Reingestia aceleiași perechi boot/secvență
nu reduce vârsta acumulată, chiar dacă între timp snapshot-ul public
a devenit indisponibil sau expirat.

Secvențele se compară modulo u32: delta 1..2^31-1 este progres, delta
zero este același eșantion, restul este regresie/ambiguitate. Un payload
schimbat pentru aceeași identitate sau un boot mai vechi este refuzat;
valoarea primită devine unknown fără a înlocui identitatea maximă păstrată.
Wrap-ul numeric este admis numai cu continuitate demonstrată și eșantion
precedent neexpirat. Un wrap peste întrerupere cere un boot nou demonstrat
sau reconciliere viitoare; repetarea secvențelor joase nu îl validează.
Boot-ul persistent nu face wrap automat în acest profil.

La prima conectare, boot nou, restart sau întrerupere ambiguă, se păstrează
o bază de observație și se cere un progres ulterior înainte de validare.
Un eșantion identic repetat nu încheie această perioadă. Când gateway-ul
nu este valid, se întrerupe și continuitatea stațiilor dependente. În
practică pornirea completă cere o bază și avansuri pentru gateway și
stații (trei snapshot-uri succesive în testele cu toate nodurile împreună).
Adaptorul din pasul 6 rămâne responsabil și pentru FreshnessProof și
coerența blocului FC04; serviciul nu deduce o achiziție nouă din succesul HTTP.

Cache-ul salvat nu este autoritate după restart: fiecare instanță Database
are runtime_id nou, iar timpii monotoni ai instanței vechi sunt invalizi.
Un răspuns HTTP nu va pretinde că datele persistate sunt măsurători noi.

Rata se memorează în sesiune. Tariful este minimum o oră, apoi fiecare oră
începută: 0 ms și exact 3.600.000 ms costă o oră, 3.600.001 ms costă două.
Plata salvează o singură înregistrare per sesiune și oprește taxarea.
Alt ID de plată pentru aceeași sesiune paid nu mai debitează. Un ceas UTC
anterior intrării confirmate refuză calculul/plata, fără sume negative.

## Citire și verificare

`get_session`, `open_sessions`, `get_command`, `recent_commands`,
`list_sessions`, `list_events`, `get_capacity` și `get_telemetry` sunt
punctele de integrare pentru API. Listele paginate folosesc un cursor
keyset timp/ID validat, nu offset-uri mutate de inserări noi. Compunerea
snapshot-ului HTTP dintr-o singură tranzacție este implementată în `snapshot()`;
apelurile independente de citire nu pretind același snapshot SQLite.

Din rădăcina repository-ului:

```sh
uv run --project backend --frozen python -B -m unittest discover -s backend/tests -v
uv run --project backend --frozen python -B backend/scripts/export_contracts.py --check
```

Testele folosesc fișiere SQLite temporare și dispozitive reprezentate prin
DTO-uri, fără hardware sau server separat. Acoperă fluxul complet, ultima
capacitate și concurența, plăți repetate/concurente, probe duplicate,
rollback injectat în plată, restart, timeout, progres contradictoriu,
telemetrie expirată/republicată/întârziată, wrap cu și fără continuitate,
contradicții în ambele ordine, recuperare prepared/sent, migrare v1→v2,
epuizarea ID-urilor și integritatea SQLite. Testele
nu validează transporturile fizice sau un firmware STM32.
