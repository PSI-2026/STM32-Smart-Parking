# Predare software — pasul 8

Backend-ul și dashboard-ul HTTP sunt implementate. Predarea software se
verifică separat de compatibilitatea și validarea fizică STM32, realizate
de Mert. Pornirea implicită este în simulare; hardware-ul este dezactivat.

## Instalare și pornire reproductibilă

Necesare: Git, Python 3.12, uv, Node.js 22.12+ și npm. Folosiți un singur
proces Uvicorn. Dintr-un checkout al branch-ului de predare:

```powershell
uv sync --project backend --locked --python 3.12
npm ci --prefix frontend
$env:PARKING_MODE = 'simulation'
$env:PARKING_HARDWARE_ENABLED = 'false'
$env:PARKING_DATABASE_PATH = 'backend/data/demo.sqlite3'
$env:PARKING_ALLOW_ANONYMOUS_SIMULATION = 'false'
$env:PARKING_ADMIN_TOKEN = (& backend/.venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(32))")
uv run --project backend --locked python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Într-un al doilea terminal, din aceeași rădăcină:

```powershell
npm run dev --prefix frontend
```

Deschideți http://127.0.0.1:5173 și introduceți în „Token de acces” valoarea
PARKING_ADMIN_TOKEN din terminalul backendului. Acest token este generat
pentru demonstrația locală; nu se introduce în fișiere VITE_*, surse sau PR.
Configurația completă este în [.env.example](.env.example); fișierul nu se
încarcă automat. Variabilele se setează în mediul procesului. Pentru un
scenariu nou folosiți o cale nouă de bază; resetarea nu există prin API.

În shell POSIX se folosesc export în loc de $env: și
backend/.venv/bin/python în loc de backend/.venv/Scripts/python.exe.
Rolurile viewer/operator/admin și configurația de acces sunt descrise în
[SECURITY.md](SECURITY.md). Health este public; celelalte rute cer token.

## Demonstrație manuală în dashboard

1. Așteptați „Simulare backend”, API conectat și capacitate disponibilă 4.
2. Intrare vehicul → B 101 DEM → Autorizează intrarea. Așteptați sesiunea
   activă și ocuparea unui loc; nu considerați accepted drept trecere.
3. Plată demo. Soldul devine zero și sesiunea devine paid.
4. Autorizează ieșirea. După confirmare, sesiunea dispare din lista curentă,
   iar senzorul și capacitatea revin la liber. Istoricul închis se citește
   separat prin GET /api/v1/sessions; snapshot-ul nu este întregul istoric.
5. Sistem → Simulare senzori → Toate ocupate. Capacitatea devine zero și
   intrarea este indisponibilă. Reveniți la Toate libere.
6. Deconectați S1 din Sistem: locurile 1/2 și capacitatea devin necunoscute.
   Reconectați S1 și așteptați progresul telemetriei. Pierderea G invalidează
   toate căile. Aceste controale există numai în simulare și cer admin.
7. Exportați jurnalul afișat. Exportul dashboard-ului conține numai cele mai
   recente evenimente/comenzi primite, nu pretinde întregul istoric.

Pentru demonstrația restartului, lăsați o sesiune plătită și opriți backend-ul
cu Ctrl+C. Reporniți cu aceeași bază și același token/configurație; după
reconectarea telemetriei sesiunea și plata trebuie păstrate. O comandă sent
întreruptă rămâne incertă: nu se retrimite sub un ID nou și nu se declară
trecerea fără dovadă. Pentru rezultate incerte, UI păstrează ID-ul original
în sessionStorage; tokenul se reintroduce după reload.

## Verificare automată

```powershell
& backend/.venv/Scripts/python.exe -B -m unittest discover -s backend/tests
& backend/.venv/Scripts/python.exe -B backend/scripts/export_contracts.py --check
& backend/.venv/Scripts/python.exe -B backend/scripts/verify_handoff.py
npm test --prefix frontend
npm run build --prefix frontend
```

verify_handoff.py pornește propriul API real pe loopback, pe un port liber,
cu baze și tokenuri temporare. Nu cere un server existent și nu folosește
DB-ul configurat pentru demonstrația manuală. Rulează cele șapte scenarii
din [SCENARIOS.md](SCENARIOS.md), inclusiv restartul aceleiași baze și
comanda incertă fără retrimitere. Opțional, --report cale.json salvează
dovezi fără credențiale. Orice eșec produce exit code nenul.

Pentru verificarea în browser urmați frontend/README.md și npm run test:e2e.
Testele pornesc singure serverele temporare. Pe Windows, mediul trebuie să
permită oprirea proceselor pornite de Playwright. CI execută browserul pe
Ubuntu, iar testele Python pe Ubuntu și Windows.

## Limite de predare

- Plățile sunt simulate; nu există integrare cu un procesator de plăți.
- Tokenurile sunt comune pe rol; nu există conturi individuale sau refresh
  tokens. Pentru acces din rețea se configurează HTTPS și restricțiile de rețea.
- API v1 nu expune reconciliere manuală auditată sau ștergerea bazei.
- Profilul hardware v2.1 nu oferă dovadă de trecere; done al MCU nu încheie
  automat sesiunea. Rezultatul de business rămâne unknown fără dovadă.
- Firmware-ul RTU v1.0 integrat în main nu este compatibil direct cu acest
  profil. Detaliile și verificările de predare sunt în
  [HARDWARE_HANDOFF.md](HARDWARE_HANDOFF.md). Aceasta este o diferență de
  protocol de rezolvat înainte de integrare, nu doar o probă fizică restantă.

Software verificat nu înseamnă sistem fizic validat. Mert consemnează separat
reviziile firmware/backend, configurația, capturile și rezultatele pe placă.
