# API HTTP — pasul 4

Pornirea este în [README.md](README.md). Toate rutele din contractul API v1
sunt conectate acum la serviciul SQLite. `/docs` și `/openapi.json`
descriu implementarea curentă; `contracts/openapi.v1.json` păstrează
specificația de integrare exportată din modelele comune.

## Configurație

Se folosesc variabile de mediu cu prefix `PARKING_`. Nu se încarcă automat
niciun fișier `.env`, inclusiv cel local rămas din pregătirea Node.js.

| Variabilă | Implicit | Rol |
| --- | --- | --- |
| PARKING_DATABASE_PATH | backend/data/parking.sqlite3, absolut față de surse | Baza persistentă; o cale configurată relativ este relativă la directorul de pornire. |
| PARKING_MODE | simulation | simulation sau hardware; baza nu poate schimba modul. |
| PARKING_TRANSPORT | TCP | TCP sau USB, raportat în snapshot; transportul fizic nu este încă conectat. |
| PARKING_HOURLY_RATE_BANI | 500 | Rata pentru sesiuni noi; rata sesiunilor existente nu se schimbă. |
| PARKING_WORKER_ENABLED | true | Procesarea automată a cozii de business. |
| PARKING_WORKER_INTERVAL_SECONDS | 0.1 | Interval 0.05–5 secunde între loturi. |

Se rulează un singur proces Uvicorn, fără `--workers` multiplu.
Factory-ul `create_app(settings, service=...)` permite teste cu baze
temporare și ceas controlat. Importul modulului nu deschide DB. Lifespan-ul
creează serviciul, execută recover înainte de cereri și pornește worker-ul.
La închidere semnalizează oprirea și așteaptă finalizarea lucrului curent.

## Rute

| Metodă / rută | Comportament |
| --- | --- |
| GET /api/v1/health | Răspunsul original, fără sondare hardware. |
| GET /api/v1/snapshot | O singură tranzacție SQLite pentru telemetrie, capacitate, sesiuni, evenimente și comenzi. |
| POST /api/v1/commands | Admitere persistentă: 202 pentru ID nou, 200 pentru replay. |
| GET /api/v1/commands/{commandId} | Starea persistentă curentă. |
| GET /api/v1/sessions | Istoric paginat; include și sesiuni închise. |
| GET /api/v1/sessions/{sessionId} | Sesiune și sold calculat. |
| GET /api/v1/events | Jurnal paginat, utilizabil pentru export JSON. |

`limit` este 1–200, implicit 50. `cursor` este token-ul `nextCursor` din
pagina precedentă; null înseamnă sfârșit. Snapshot-ul conține numai sesiuni
neînchise și maximum 50 evenimente/comenzi recente, nu tot istoricul.
Toate răspunsurile API au Cache-Control: no-store.

Exemplu PowerShell:

```powershell
$body = @{commandId='entry-demo-001'; action=@{type='enter'; plate='B 101 DEM'}} | ConvertTo-Json -Depth 3
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/commands -ContentType application/json -Body $body
Invoke-RestMethod http://127.0.0.1:8000/api/v1/commands/entry-demo-001
Invoke-RestMethod http://127.0.0.1:8000/api/v1/snapshot
```

Clientul generează ID-ul o singură dată pentru o intenție și îl păstrează
la retry. 202/accepted confirmă persistența, nu accesul. Worker-ul poate
avansa comanda înaintea primului GET; răspunsul POST inițial rămâne accepted.
Refuzurile operaționale apar în CommandResult.error, nu retroactiv în HTTP.

## Worker și stadiul integrării

Worker-ul procesează enter/pay/exit din coada accepted în loturi de cel
mult 50. În hardware procesează și refuză acțiunile demo. În simulation,
acțiunile demo rămân accepted până la integrarea simulatorului în pasul 5;
nu sunt aplicate și nu blochează procesarea celorlalte comenzi.

O excepție de procesare păstrează comanda accepted prin rollback și aplică
un backoff de 5 secunde în memoria worker-ului. Selecția umple mai întâi
lotul cu prime încercări; numai locurile rămase sunt oferite retry-urilor
eligibile, ordonate după termenul de retry (cel mai vechi primul), apoi ID
pentru egalități. O încercare eșuată primește un termen nou și trece după
retry-urile care așteaptă de mai mult timp. Astfel o coadă închisă nu lasă
o comandă recuperabilă în urma acelorași eșecuri lente. Un retry expirat
în timpul unui lot lent nu poate trece înaintea
comenzilor încă neîncercate. Prioritatea este pentru admiterea progresului
nou; sub un flux nelimitat de comenzi noi, retry-urile pot fi amânate.
La restart, evidența încercărilor/backoff-ul se poate reseta; efectele de business
rămân protejate de tranzacție/idempotență. Oprirea se verifică între comenzi.

Acest worker nu apelează claim_dispatch și nu trimite comenzi fizice.
Fără adaptor, pornirea afișează date necunoscute și o intrare poate primi
rejected/DATA_UNAVAILABLE. Cu telemetrie injectată de teste, accesul poate
ajunge executing/prepared, dar nu devine done fără dovada explicită.
Nu există încă simulator complet, I/O MODBUS sau test E2E cu frontend-ul.

## Erori

Forma este `{error:{code,message,retryable}}`, inclusiv pentru validarea
FastAPI. Snake_case, proprietățile suplimentare și tipurile JSON greșite
sunt refuzate. JSON-ul trunchiat și octeții cu codare invalidă primesc tot
422 VALIDATION_ERROR; mesajul despre metodă este rezervat pentru 405.
Corpul invalid nu este reflectat în răspuns.

- 404 NOT_FOUND pentru resurse absente.
- 409 IDEMPOTENCY_CONFLICT pentru același ID cu altă acțiune normalizată.
- 422 VALIDATION_ERROR pentru corp, ID, limită sau cursor invalid.
- 503 SERVICE_UNAVAILABLE pentru SQLite ocupat; DATA_UNAVAILABLE poate
  apărea la citire când datele de business nu pot fi evaluate corect.
- 500 INTERNAL_ERROR pentru erori neașteptate, fără traceback în răspuns.

După timeout/500/503 se repetă aceeași intenție cu același ID. Faptul că
un răspuns a lipsit nu dovedește că admiterea a eșuat. Erorile 404/405 de
rutare sunt și ele JSON; 405 păstrează antetul Allow.

## Verificare

Testele HTTP folosesc TestClient/ASGI și fișiere SQLite temporare, nu un
server TCP sau hardware. Verifică rutele, erorile, aliasurile JSON,
replay-ul, paginarea, startup/shutdown, worker-ul și restartul aplicației.
Un test scrie în DB din alt thread în timpul construirii snapshot-ului
și confirmă că rezultatul rămâne în tranzacția de citire inițială.
Fluxul HTTP intrare/plată/ieșire folosește dovezi DTO explicite la limita
adaptorului; nu revendică simulare fizică.
