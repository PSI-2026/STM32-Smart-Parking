# Contracte de integrare — API v1.0.0 / MODBUS țintă v2.1

Acestea sunt contracte pentru etapele următoare. Numai health este implementat
în server. Nici firmware-ul actual, nici vechea hartă locală v2.0 nu oferă
încă extensia v2.1 descrisă aici. Lipsa ei blochează scrierile hardware;
nu se încearcă autodetectare prin comenzi sau fallback la v2.0/single-slave.

## Surse și verificare

Sursele executabile sunt `app/contracts/api.py` și `firmware.py`. JSON-urile
și exemplele sunt generate; nu se editează manual. Din rădăcina repository-ului:

```sh
uv run --project backend --frozen python backend/scripts/export_contracts.py
uv run --project backend --frozen python backend/scripts/export_contracts.py --check
uv run --project backend --frozen python -m unittest discover -s backend/tests -v
```

`openapi.v1.json` este specificația țintă, cu `x-implemented` pe operații.
`/openapi.json` al serverului descrie doar implementarea efectivă. Schema
descrie structura; validatorii Python aplică suplimentar relațiile dintre
câmpuri. Exemplele sunt normative pentru semantică, nu dovezi hardware.

## Convenții și rute

JSON acceptă numai camelCase, inclusiv în acțiunile imbricate; proprietățile
suplimentare și snake_case sunt refuzate. Codul Python poate construi modele
separat prin `from_internal()`, care nu este frontiera HTTP. Momentele sunt
numere întregi UTC Unix în milisecunde; sumele sunt întregi în bani.
Identificatorii sunt opaci, 1–128 caractere ASCII alfanumerice, `_` sau `-`.
Nodurile sunt `G`, `S1`…`S5`, locurile 1–4, barierele `entry` și `exit`.

| Metodă / rută după `/api/v1` | Succes | Erori înainte de admitere/citire |
| --- | --- | --- |
| GET `/health` | 200, contractul existent | Nicio eroare de business |
| GET `/snapshot` | 200, inclusiv cu telemetrie necunoscută | 500 |
| POST `/commands` | 202 comandă nouă; 200 replay | 409 conflict ID; 422 format; 503 persistență indisponibilă; 500 |
| GET `/commands/{commandId}` | 200 | 404, 422, 500 |
| GET `/sessions` | 200 paginat | 422, 500 |
| GET `/sessions/{sessionId}` | 200 | 404, 422, 500 |
| GET `/events` | 200 paginat | 422, 500 |

Listele paginate au `limit` 1–200, implicit 50, `cursor` opac și
`nextCursor: null` la sfârșit. Ordinea este descrescătoare după timpul
creării, apoi ID stabil. Cursor invalid: 422. Snapshot-ul include toate
cele șase noduri, patru locuri și două bariere; numai sesiuni neînchise,
maximum cele mai recente 50 evenimente și 50 comenzi.

## Admitere, persistență și replay

`POST /commands` primește `{commandId, action}`. Se procedează astfel:

1. Se validează structura, apoi se normalizează numărul de înmatriculare:
   spații marginale eliminate, spații interne comprimate, majuscule.
2. În tranzacție, se caută ID-ul. Dacă există cu aceeași acțiune normalizată,
   se întoarce 200 cu rezultatul persistent actual, chiar dacă este refuzat.
   Cu altă acțiune: 409 `IDEMPOTENCY_CONFLICT`, fără a modifica originalul.
3. Dacă nu există, se persistă comanda și acțiunea, apoi se întoarce 202 cu
   `accepted`. Toate verificările operaționale sunt făcute după această
   admitere, inclusiv sesiune absentă, parcare plină, lipsa plății,
   interblocare, date indisponibile și acțiune demo în modul hardware.
4. Rezultatele operaționale se păstrează în comandă. Un exit neplătit devine
   `rejected/PAYMENT_REQUIRED`; după plată, același ID rămâne refuzat. Pentru
   o nouă intenție se folosește un ID nou, numai dacă rezultatul anterior
   dovedește că operația nu s-a executat. Un rezultat incert nu permite asta.

Formatul erorilor HTTP este `{error: {code, message, retryable}}`.
422 și 503 înaintea persistenței nu rezervă ID-ul. Dacă răspunsul se pierde
sau apare 500, clientul repetă aceeași cerere cu același ID, fără să
presupună că persistarea a eșuat. După restart se aplică aceeași regulă;
comenzile și amprentele lor nu se uită automat. `retryable=true` înseamnă
reinterogare/replay cu același ID, niciodată reexecutarea unei comenzi
persistente refuzate și nici schimbarea ID-ului unei operații incerte.
Comanda respinsă definitiv poate fi urmată de o intenție nouă cu ID nou.

Stări: `accepted` → `executing` → `done`, `rejected`, `failed`, `expired`
sau `unknown`. Se poate refuza direct din `accepted`. `unknown` permite
reconciliere ulterioară; nu este succes. Codurile de eroare sunt enumerate
în modele. La implementarea rutelor, erorile implicite FastAPI vor fi
adaptate la formatul API; serverul curent păstrează doar health.

Acțiunile `enter`, `pay`, `exit` sunt de business. `set-slot-sensor`,
`set-all-slot-sensors`, `set-node-online`, `set-obstacle`,
`set-barrier-presence`, `set-transport` sunt exclusiv demo; în hardware
devin comenzi persistente `rejected/SIMULATION_ONLY`. Transportul real se
selectează din configurație. Resetarea demo-ului nu este expusă în API v1.

## Telemetrie, prospețime și calea de comunicație

API-ul și `DeviceTelemetry` validează aceeași topologie și aceeași regulă:
niciun loc, barieră sau nod copil nu poate avea date `valid` fără gateway
valid, online și recent. Un senzor valid cere și stația sa validă/online.
Stațiile valide cer schema v2.1, boot cunoscut și secvență de eșantion.
`DeviceTelemetry` folosește `SlotTelemetry`, fără `sessionId`; serviciul
adaugă asocierea de business când compune `ParkingSnapshot`.

`quality`: `valid`, `unknown`, `stale`, `unavailable`. `staleAfterMs` este
configurabil 500–10000, implicit 2000. La vârstă >= limită, datele nu sunt
valide. `updatedAt` este momentul achiziției pe gazdă în UTC; vechimea se
calculează monoton, nu prin diferențe de ceas UTC.

Profilul admite numai citiri directe la Unit ID real. Cache-ul gateway-ului
v2.0 nu este utilizabil pentru acest profil. Fiecare FC04 de 37 registre
IR `0x0300` produce o singură copie atomică, înghețată pentru răspuns:
identitate, boot, secvență, vârsta reală a eșantionului, flags, validitate,
payload și înregistrarea ultimei comenzi, inclusiv ecoul celor nouă cuvinte
FC16 procesate la offseturile relative 28–36. Câmpurile exacte sunt în manifest.
O citire fragmentată, cu valori invalide sau fără identitate compatibilă
nu este eșantion utilizabil. Registrele nefolosite sunt zero.

MCU incrementează `sampleSequence` numai la o achiziție nouă, chiar când
valoarea nu se schimbă; `sampleAgeMs` crește de la acea achiziție, saturat
la u32 maxim, fără resetare la citire. Backend-ul păstrează timpul monoton
primei observații a cheii `(nod, boot, sequence)` și estimarea conservatoare
de vârstă la acel răspuns: `firstEstimatedAgeMs = prima sampleAgeMs + primul RTT`.
Aceste două valori nu sunt resetate la o nouă citire a aceleiași secvențe.
La citirile ulterioare calculează conservator:

`ageMs = max(sampleAgeMs + durata cererii + timpul de la răspuns,
firstEstimatedAgeMs + timpul monoton de la primul răspuns al aceleiași secvențe)`.

Exemplu de regresie: prima citire vede 1500 ms, RTT=10 ms, deci salvează
1510 ms. După 600 ms, chiar dacă MCU repetă 1500 ms și RTT=10 ms,
vârsta este cel puțin 1510+600=2110 ms, deci eșantionul este expirat.
`examples/frozen-sample.json` fixează acest caz. Starea de prospețime se
reconstruiește după restart în modul necunoscut, cu verificarea progresului
secvenței; nu se transferă timpi monotoni între procese.

O secvență repetată nu întinerește eșantionul. La wrap se acceptă progresul
modulo u32 doar cu continuitate și boot identic; după goluri/ambiguitate se
reinițializează observația fără a valida date vechi până la o achiziție
nouă demonstrată. La prima conectare se cere progres de secvență înainte
de publicarea datelor valide. Un MCU care îngheață atât secvența cât și
vârsta nu poate produce validitate nelimitată prin citiri repetate.

Flags ready/local-data-valid trebuie să fie active. local-data-valid
înseamnă înregistrare de achiziție coerentă; nu promite validitatea tuturor
senzorilor. Pentru S1/S2, validMask din antet și payload[2] trebuie să fie
egale exact; numai b0 (senzorul A) și b1 (senzorul B) sunt permise. Dacă
nu coincid, întregul eșantion al stației este respins și ambele locuri sunt
necunoscute. Dacă sunt egale cu 1 sau 2, se publică numai senzorul valid;
bitul de ocupare al celuilalt nu se utilizează. La mască 0 ambele sunt
necunoscute. `freeCount` este utilizabil numai când ambele măști sunt 3 și
trebuie să fie `2-popcount(occupancyMask)`. Altfel payload[1] trebuie să fie
65535 și nu se folosește pentru capacitate. `SlotSample` validează regulile;
`examples/partial-validity-fc04.json` include toate cele 37 cuvinte și A
valid/ocupat, B necunoscut. Pentru bariere toate cele patru câmpuri de
payload trebuie să fie valide.
Masca online din G trebuie să includă stația; o lipsă invalidează imediat
calea sa. `sampleAgeMs` și secvența sunt pentru sursa locală, nu pentru
momentul construirii răspunsului. Datele copilului nu pot fi declarate mai
proaspete decât calea sa validată.

La pierderea unei căi, adaptorul invalidează imediat datele dependente.
Pentru orice calitate diferită de valid: `occupied: null`, barieră
`UNKNOWN`, intrări null, feedback `unknown`. Fără eșantion, timpii sunt
null. Disponibilitatea necunoscută înseamnă `capacity.available: null`.

## Rezultatul MCU, timeout și istoricul limitat

Extensia v2.1 păstrează blocul de comandă v2.0: FC16 atomic, nouă registre
HR `0x0100`, u32 high-first, TTL 100–10000 ms pentru deschidere. Lease-ul
valid se reînnoiește prin HR4; durata implicită propusă este 2000 ms.
În v2.1, adaptorul activ de pe PC emite FC06 HR4=1 cu același Unit ID
ca FC16: 3 pentru S3, 4 pentru S4. Gateway-ul doar rutează acea cerere
la stație, fără reînnoire autonomă a lease-ului ei. Stația verifică la
acceptare propriul lease de control extern. HR4 la Unit ID247 ar reînnoi
doar lease-ul gateway-ului și nu autorizează S3/S4. Această alegere v2.1
înlocuiește explicit propunerea v2.0 în care gateway-ul reînnoia stațiile.
La expirare se refuză o deschidere nouă; nu se forțează închiderea.
`examples/lease-routing.json` prezintă traseul complet pentru ambele bariere.
S3 cere capacity=1; S4 payment=2. Reset defect: operație 2, TTL=0,
authorization=0, fără expunere HTTP v1. Interblocările rămân locale.

API-ul persistă maparea ID text → `(nod, boot, ID MCU u32 nenul, bloc exact)`
înainte de scriere. ID-urile cresc per nod/boot; un singur controler este
activ și nu emite altă comandă pe aceeași barieră cât timp există rezultat
incert. La epuizarea u32 se opresc comenzile și se cere mentenanță; nu se
face wrap automat sau restart automat pentru a reemite intenții vechi.

Înregistrarea atomică este despre **ultima cerere procesată, inclusiv una
refuzată înainte de acceptare**. Ea conține `recordBootEpoch` (boot-ul
solicitat), `recordCommandId`, status, cod și `recordCommandWord0..8`,
ecoul exact al blocului cererii respective. Dacă B este refuzată după A,
înregistrarea indică B; progresul ulterior al lui A nu schimbă pointerul
înapoi la A. La boot nou înregistrarea este goală. `recordPresent=0`
înseamnă toate câmpurile record zero, deci rezultat unknown la interogare.

Rezultat cunoscut numai dacă identitatea atomică, boot-ul curent, boot-ul
recordului, ID-ul și toate cele nouă cuvinte FC16 corespund cererii.
`result_for()` aplică această regulă; `read_command()` primește comanda
completă persistentă, nu doar ID-ul numeric. Un record cunoscut include
`commandBlock`, iar un rezultat unknown are `commandBlock: null`.
Același ID poate descrie două intenții conflictuale: un done al unui open
nu dovedește reset-fault, iar un refuz id-content-conflict pentru reset
nu dovedește că open-ul original nu s-a executat. Ecoul diferit produce
unknown pentru original, păstrând orice claim și reconcilierea necesară.
Exemplele `same-ID-different-block` și `original-open-after-conflicting-reset`
sunt incluse în `examples/reconciliation.json`.
Perechi permise: accepted/executing→0, done→1, rejected→2/3/4/5,
expired→6, failed→7. Unknown are `resultCode: null`, `evidence: unproven`
și un motiv explicit. Done+actuator-fault este invalid.

Ecoul unei cereri refuzate se validează structural (exact nouă cuvinte
u16, ID nenul și boot solicitat conforme cu recordul), fără regulile de
emitere din `DeviceCommand`. Astfel un open cu authorization=0 poate fi
reprezentat ca rejected/authorization-missing, chiar dacă backend-ul nu
are voie să emită acea cerere. `result_for()` păstrează comparația exactă
a blocurilor; nu înlocuiește autorizarea lipsă cu cea intenționată.
ID zero sau blocuri cu lungime incorectă sunt erori de protocol și nu
creează o înregistrare de comandă în acest profil. Manifestul enumeră
separat comparația boot-ului curent și a boot-ului recordului cu cel așteptat.

După timeout se citește această înregistrare. Dacă nu se pot demonstra
identitatea și coerența: unknown. Nu se combină status/boot/ID citite din
blocuri separate și nu se atribuie lui A refuzul lui B. Istoricul intern
de deduplicare (minimum 32 cereri) nu este interogabil prin profil; dacă
ultima înregistrare a fost înlocuită, lookup-ul este unknown, nu „nu s-a
executat”. Backend-ul nu retrimite automat blocuri incerte.

Firmware-ul trebuie să refuze ID-uri vechi evacuate, să deduplice același
ID cu același bloc și să refuze același ID cu alt bloc. În acest profil,
backend-ul nu face replay fizic automat nici când un rezultat cunoscut
poate fi returnat din persistență/lookup; reîncercarea unei operații
definitiv neexecutate este o intenție nouă. După schimbarea boot-ului,
intențiile vechi rămân în aplicație pentru reconciliere, fără reemitere
sub un ID nou. `examples/reconciliation.json` acoperă aceste cazuri.

## Trecere versus progresul barierei

`DeviceCommandResult.done` descrie executarea comenzii dispozitivului,
niciodată trecerea vehiculului. `PassageEvidence` este un DTO separat,
corelat prin nod, boot, ID numeric și blocul exact de deschidere. Include
un ID unic al dovezii, momentul și starea confirmed/unavailable/lost.
`passage_matches()` cere explicit modul și acțiunea business; acceptă numai
open în modul simulation cu sursă simulation și enter→S3 sau exit→S4.
Reset-fault și orice dovadă simulation în modul hardware sunt refuzate.
Helperul verifică potrivirea structurală, nu autorizează singur tranziția:
în etapa de persistență, serviciul încarcă maparea comenzii API și a
sesiunii din baza de date, verifică acțiunea, modul și rezultatul neconflictual
al comenzii dispozitivului, apoi consumă evidenceId o singură dată în
tranzacția care salvează trecerea și tranziția sesiunii. O dovadă duplicată,
anterioară emiterii comenzii, pentru altă sesiune sau pentru un bloc
conflictual nu schimbă sesiunea. Aceste verificări tranzacționale sunt
obligații ale etapei de business, nu funcții implementate în pasul 2.

Profilul hardware v2.1 nu oferă dovadă de trecere și întoarce unavailable.
Prezent → deschis → absent nu dovedește sensul deplasării. La întreruperea
observațiilor se raportează lost. Nici polling-ul, nici închiderea barierei
nu substituie o dovadă. După încheierea progresului fără dovadă,
enter/exit de business rămân unknown și sesiunea pending. Reconcilierea
operatorului trebuie să fie o operație auditată separată, încă neexpusă
în API v1; nu se editează direct stările pentru a pretinde integrare.

Simulatorul poate produce un eveniment explicit corelat de trecere,
independent de schimbarea senzorului de prezență. `source: simulation`
este momentan singura dovadă confirmed acceptată de model. O extensie
hardware viitoare va necesita o sursă de dovadă și un contract versionat.
Simulatorul nu finalizează o sesiune doar prin comutarea vehiclePresent.

## Capacitate și sesiuni

Snapshot-ul publică separat `capacity`: physicalOccupied (din senzori),
outstandingClaims (rezervări necontabilizate fizic), available și
reconciliationRequired. Când datele sunt valide și reconciliate:
`available = 4 - physicalOccupied - outstandingClaims`.
La incertitudine, available este null și se blochează admiterea.

| Moment | Rezervare / ocupare contabilizată |
| --- | --- |
| Intrare autorizată | Creează un claim persistent înainte de deschidere. |
| Trecere confirmată, încă fără ocupare | Claim-ul rămâne; nu reapare capacitate liberă. |
| Ocupare corelată neambiguu | În aceeași tranzacție O crește și claim-ul este consumat o singură dată. |
| Rezultat incert | Claim-ul rămâne până la reconciliere. |
| Refuz care dovedește că nu a început accesul | Claim-ul se anulează o singură dată. |
| Ocupare fără corelare demonstrabilă | Se păstrează dovezile/claim-ul, available=null; nu se dublează contabilizarea ca verdict numeric. |

Corelarea nu cere identificarea plăcuței la loc: se poate transfera un claim
dintr-un pool către o ocupare demonstrată în aceeași tranzacție a
simulatorului sau într-o reconciliere auditată. Ordinea FIFO a claim-urilor
este doar contabilă și nu atribuie automat `sessionId` unui loc.
O diferență netă între două snapshot-uri hardware nu dovedește singură
corelarea: pot exista ieșiri/intrări între citiri. Dacă lipsește dovada,
nu se consumă claim-ul doar pe baza acestei diferențe.

Exemplu ultima capacitate: O=3,R=0,A=1 → A autorizată: O=3,R=1,A=0 →
A trece dar nu parchează: tot 3,1,0 → ocupare corelată: 4,0,0.
Cererea B este refuzată în ambele intervale. Cu slotId null și ocupare
ambiguă: reconciliationRequired=true, available=null, B rămâne blocată.
Verificarea capacității, crearea sesiunii pending și a claim-ului sunt o
singură tranzacție atomică în etapa de persistență, nu trei verificări.

Stări sesiune: pending_entry, active, paid, pending_exit, completed,
cancelled. enteredAt/exitedAt sunt puse numai după dovezi de trecere;
slotId poate rămâne null. Senzorii sunt autoritatea pentru ocupare; plata
și ieșirea autorizată nu eliberează locul. Tariful este minimum o oră,
apoi fiecare oră începută; rata se salvează în sesiune. Plata demo
achită soldul la acel moment și oprește taxarea până la ieșire, fără
expirare în v1. amountDueBani=sold rămas, paidBani=total achitat.

## Frontend și limite

Matricea câmp cu câmp este în `frontend-compatibility.md`. Referința
`references/frontend-types.ts` este copiată din commit-ul frontend
`5972a3e4beeeaaf52c062f684cc55d5074d20165`, astfel încât review-ul nu cere
checkout de branch sau acces web. Compatibilitatea este verificată prin
inspecție, nu prin rularea celor două componente împreună.

DeviceAdapter nu include sesiuni, tarife sau plăți. G asigură calea de
comunicație, S5 este prezent ca identitate, dar I/O de mediu nu intră în
acest subset. MODBUS TCP folosește MBAP; USB folosește RTU/serial; RTU
prin socket Renode nu se confundă cu MODBUS TCP. OPC UA, MBE și serviciile
industriale sunt în afara acestui contract de parcare.
