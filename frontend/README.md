# Smart Parking — frontend HTTP

Dashboard React + TypeScript + Vite în limba română. Datele și comenzile
vin din backend prin `ParkingApi`; mock-ul local este păstrat numai pentru
teste. Nu există fallback automat la date demo.

## Pornire

1. Instalați și porniți backend-ul conform [README](../backend/README.md).
2. Configurați un token pe backend conform [SECURITY](../backend/SECURITY.md).
3. Din `frontend`, cu Node.js 22.12+:

```sh
npm ci
npm run dev
```

Deschideți http://127.0.0.1:5173 și introduceți tokenul în „Token de acces”.
Tokenul rămâne numai în memorie, nu este salvat în browser storage și nu
se pune într-o variabilă VITE_* sau în surse. La reîncărcare se introduce
din nou. Un rol viewer poate doar citi, operator poate enter/pay/exit,
admin poate folosi și controalele de simulare; backend-ul autorizează
fiecare cerere.

Proxy-ul Vite transmite /api către BACKEND_URL (implicit
http://127.0.0.1:8000). Exemplul .env.example configurează doar adresa.
Pe Windows se poate folosi npm.cmd dacă politica PowerShell blochează npm.

## Comportament

- ParkingApi păstrează getSnapshot sincron, subscribe, execute, refresh și
  reset. Instanța implicită folosește HTTP, cu polling la 500 ms.
- Snapshot-ul inițial este necunoscut: nu inventează locuri libere sau un
  mod simulation înainte de primul răspuns.
- Răspunsurile se validează cu Ajv după OpenAPI-ul generat de backend.
  Polling-ul nu suprapune cereri. Cache-ul este îmbătrânit local folosind
  timpul monoton și durata cererii; eșecul HTTP invalidează datele fizice.
- Capacitatea pentru admitere este capacity.available, inclusiv claim-uri,
  nu numărul senzorilor care raportează liber.
- execute trimite POST o singură dată pe încercare și urmărește același ID
  prin GET până la rezultat sau deadline. accepted/executing nu înseamnă
  succes în UI. Un rezultat incert nu produce automat alt POST sau alt ID.
- Înainte de POST, UI salvează ID-ul și acțiunea în sessionStorage, pentru
  reluarea exactă după reload. Nu salvează credențiale. Cât timp rezultatul
  este incert, operațiile noi sunt blocate; „Verifică aceeași comandă”
  reia exact ID-ul/acțiunea, idempotent. Polling-ul poate confirma ulterior
  rezultatul fără o a doua trimitere.
- Sunt afișate valorile null, UNKNOWN, pending_entry/pending_exit și modul
  hardware. Controalele demo sunt dezactivate/ascunse în hardware.
- Resetarea datelor persistente nu are endpoint și este dezactivată în UI.
  Soldurile și tariful vin din backend; plata este întotdeauna simulată.
- Snapshot-ul conține sesiuni neînchise și cel mult 50 de evenimente și
  comenzi recente. Exportul UI include numai datele afișate; istoricul
  complet se citește din endpoint-urile paginate, nu este pretins ca
  încărcat de dashboard.

Tipurile au fost lărgite pentru compatibilitatea cu mock-ul de test;
răspunsurile HTTP sunt validate după schema strictă, nu după aceste
câmpuri TypeScript opționale.

## Verificare

```sh
npm test
npm run build
```

Pentru E2E, instalați întâi backend/.venv și Chromium în cache-ul proiectului.
Din frontend, în PowerShell:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = 'node_modules/.cache/ms-playwright'
npx playwright install chromium
npm run test:e2e
```

În shell POSIX:

```sh
PLAYWRIGHT_BROWSERS_PATH=node_modules/.cache/ms-playwright npx playwright install chromium
npm run test:e2e
```

Testele pornesc singure două API-uri FastAPI pe baze temporare și două
servere Vite (porturi 18000/18001 și 15173/15174). Nu reutilizează servere
existente și nu deschid adaptoare fizice. Un token aleator este creat doar
pentru procesele testului. Verifică browser → adaptor → proxy → backend:
intrare/plată/ieșire, modul hardware cu date necunoscute și răspunsul
pierdut al unei comenzi, fără POST suplimentar. Hardware-ul fizic și portul
serial nu sunt validate de aceste teste.

Pe Windows, mediul de execuție trebuie să permită Playwright să oprească
procesele temporare pe care le pornește. CI rulează E2E pe Ubuntu.

## Proveniență

Dashboard-ul de bază provine din feature/frontend-dashboard,
revizia 5972a3e4beeeaaf52c062f684cc55d5074d20165. Integrarea HTTP
păstrează aspectul și interfața ParkingApi, actualizând semantica pentru
contractul backend. Matricea este în
[frontend-compatibility.md](../backend/contracts/frontend-compatibility.md).
