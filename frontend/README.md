# Smart Parking — frontend

Interfață în limba română pentru monitorizarea și simularea unei parcări cu patru locuri și două bariere, realizată cu React, TypeScript și Vite. Demo-ul funcționează în browser, fără backend sau hardware. Conexiunea HTTP cu backend-ul se verifică separat.

## Pornire

Este necesar Node.js 22.12+ și npm. Din rădăcina proiectului:

```sh
cd frontend
npm ci
npm run dev
```

Deschide `http://127.0.0.1:5173`. Portul este fix; dacă frontend-ul rulează deja, folosește instanța existentă.

Pe Windows, dacă `npm` nu funcționează în PowerShell, folosește `npm.cmd`, de exemplu `npm.cmd run dev`.

## Funcționalități

- **Parcare:** ocuparea locurilor, controlul accesului, sesiuni, căutare după număr de înmatriculare și plăți simulate.
- **Sistem:** starea nodurilor simulate, verificarea conexiunii cu backend-ul, simularea senzorilor, exportul jurnalului în JSON și resetarea demo-ului.

La pornire există două sesiuni fictive: **B 101 DEM** în P01, neplătită, și **CJ 24 DEM** în P03, plătită. Pentru a demonstra fluxul:

1. Alege **Intrare vehicul** și introdu un număr fictiv. Simulatorul alocă un loc liber și deschide temporar bariera de intrare.
2. Alege **Plată demo** pentru sesiunea respectivă. Tariful este de 5 RON pentru fiecare oră începută; plata singură nu eliberează locul.
3. Alege **Autorizează ieșirea**. După verificarea plății și a interblocărilor, simulatorul deschide bariera de ieșire, încheie sesiunea și eliberează locul.

**Simulare senzori**, disponibilă din ambele pagini, permite modificarea ocupării P01–P04 și a prezenței vehiculelor sau obstacolelor la bariere. **Toate libere** și **Toate ocupate** modifică numai senzorii locurilor. Acționarea senzorilor nu creează sau închide sesiuni și nu înregistrează plăți. Prezența unui vehicul nu deschide automat bariera, iar un obstacol blochează accesul prin bariera respectivă.

Deconectarea unui nod din **Sistem** face datele lui necunoscute. Deconectarea gateway-ului G face toate locurile și barierele necunoscute. **Resetează demo** cere confirmare și reface starea inițială.

**Jurnal de evenimente** permite căutarea după mesaj, nod sau vehicul, inclusiv fără diacritice, și filtrarea după nivel. Afișează inițial cele mai recente opt evenimente; **Arată mai multe** extinde lista, iar **Restrânge lista** revine la afișarea compactă. Rezultatele comenzilor se pot deschide separat. **Exportă JSON** include toate evenimentele și rezultatele comenzilor din memorie, indiferent de filtrele alese.

## Conexiune cu backend-ul

În **Sistem → Starea sistemului → Backend API**, apasă **Testează conexiunea**. Verificarea rulează la cerere, are o limită de 5 secunde și afișează rezultatul, versiunea API și ora ultimului test.

Contract verificat în branch-ul `feature/backend-fastapi`, commit `afd19879acb0e8b104dc2d7ef15bf8bf14d07dcc`: `GET /api/v1/health`, cu răspunsul:

```json
{"status":"healthy","service":"smart-parking-backend","version":"0.1.0"}
```

Vite transmite cererile `/api/*` către `http://127.0.0.1:8000`, atât în `dev`, cât și în `preview`. Pentru altă adresă, creează `frontend/.env.local` folosind [.env.example](.env.example):

```dotenv
BACKEND_URL=http://127.0.0.1:8000
```

Repornește Vite după schimbarea adresei. Browserul trimite cererile prin proxy-ul frontend, fără modificări CORS în backend.

<details>
<summary>Pornirea backend-ului din branch-ul separat, în PowerShell</summary>

Sunt necesare Python 3.12+ și `uv`. Din rădăcina proiectului, extrage backend-ul într-un director ignorat de Git, păstrând branch-ul frontend curent:

```powershell
git fetch --no-tags origin feature/backend-fastapi
New-Item -ItemType Directory -Path frontend/.backend-test.local -Force | Out-Null
git archive --format=zip --output=frontend/.backend-test.local/source.zip origin/feature/backend-fastapi backend
Expand-Archive -LiteralPath frontend/.backend-test.local/source.zip -DestinationPath frontend/.backend-test.local -Force
uv sync --frozen --project frontend/.backend-test.local/backend
Set-Location frontend/.backend-test.local/backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Acești pași folosesc versiunea descărcată a branch-ului backend. Păstrează terminalul deschis cât timp testezi conexiunea. Dacă ai pregătit deja acest director, pentru repornire sunt suficiente ultimele două comenzi, pornind din rădăcina proiectului. Oprește backend-ul cu Ctrl+C când ai terminat.

</details>

### Depanare: „Backend indisponibil (HTTP 500)”

Această eroare poate apărea când proxy-ul frontend nu poate contacta backend-ul:

1. Verifică dacă backend-ul rulează și răspunde la `http://127.0.0.1:8000/api/v1/health`, sau la adresa configurată în `BACKEND_URL`.
2. Verifică adresa și portul din `.env.local`, dacă fișierul există. Repornește Vite dacă le-ai modificat.
3. Apasă din nou **Testează conexiunea**. Mesajul afișat reprezintă rezultatul ultimului test și nu se actualizează automat.

Dacă backend-ul răspunde direct, dar testul prin frontend eșuează, verifică mesajele din terminalele backend și Vite.

## Testare

Rulează comenzile din directorul `frontend`:

| Comandă | Scop |
| --- | --- |
| `npm test` | Testează simulatorul și validarea răspunsului health, inclusiv erorile și timeout-ul. |
| `npm run build` | Verifică TypeScript și generează build-ul în `dist/`. |
| `npm run preview` | Servește local build-ul generat; folosește adresa afișată în terminal. |
| `npm run test:backend` | Verifică prin HTTP real conexiunea frontend → backend. Necesită ambele servere pornite. |

Pentru testarea unui frontend pornit pe alt port, setează `FRONTEND_URL` înainte de test. Exemplu în PowerShell, pentru `preview` pe portul 4173:

```powershell
$env:FRONTEND_URL='http://127.0.0.1:4173'
npm.cmd run test:backend
```

Testul de conexiune eșuează dacă backend-ul este indisponibil, răspunsul nu este JSON sau nu confirmă serviciul `smart-parking-backend` în starea `healthy`.

## Limitări

- Locurile, nodurile, barierele, sesiunile și plățile sunt simulate local. Starea este păstrată în memoria paginii și se resetează la reîncărcare.
- Verificarea health confirmă numai conexiunea HTTP. Backend-ul verificat nu oferă încă endpoint-uri pentru datele și comenzile parcării. Eticheta **Sistem conectat** se referă la gateway-ul simulat.
- Poziția barierei este estimată. Datele nodurilor deconectate sau mai vechi de 2 secunde sunt afișate ca necunoscute.
- Un build static publicat separat necesită configurarea rutei `/api` către backend în serverul de hosting; proxy-ul Vite funcționează în `dev` și `preview`.
