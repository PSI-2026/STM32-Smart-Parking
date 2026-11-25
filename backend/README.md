# Backend STM32 Smart Parking

Pentru placa cu firmware v1.0 verificată de Mert, vezi profilul separat
[USB/RTU numai pentru citire](LEGACY_READONLY.md). Acesta afișează P01 fizic
fără să activeze accesul, sesiunile sau capacitatea distribuită v2.1.

Backend Python + FastAPI, cu API HTTP, persistență SQLite și simulator
persistent pentru fluxul complet intrare/plată/ieșire. Pornește implicit
în simulare; adaptoarele MODBUS TCP și RTU sunt disponibile opțional.
Compatibilitatea cu firmware-ul STM32 necesită validare pe dispozitiv.

## Cerințe

- Python 3.12 sau mai nou.
- [uv](https://docs.astral.sh/uv/) pentru mediul virtual și dependențele fixate în `uv.lock`.

## Instalare și pornire

Din rădăcina repository-ului, pe Windows (PowerShell), Linux sau macOS:

```sh
uv sync --project backend --frozen --python 3.12
uv run --project backend --frozen python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Nu este necesară activarea manuală a mediului virtual. `uv` utilizează
`backend/.venv`. Oprește serverul cu `Ctrl+C`. Pentru dezvoltare, din rădăcina
repository-ului adaugă `--reload --reload-dir backend/app` la comanda de pornire.

Alternativ, din directorul `backend`:

```sh
uv sync --frozen --python 3.12
uv run --frozen python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Din directorul `backend`, opțiunile pentru dezvoltare sunt
`--reload --reload-dir app`.

## Verificare

Deschide `http://127.0.0.1:8000/api/v1/health`. Răspunsul așteptat este:

```json
{"status":"healthy","service":"smart-parking-backend","version":"0.1.0"}
```

În PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

Documentația interactivă este disponibilă la `http://127.0.0.1:8000/docs`,
iar schema OpenAPI la `http://127.0.0.1:8000/openapi.json`.

Endpoint-ul health confirmă numai funcționarea serviciului HTTP. Nu verifică
STM32, MODBUS sau o bază de date. Pornirea nu necesită hardware, frontend,
Node.js ori un fișier `.env`.

## Acces și integrare frontend

API-ul este protejat implicit. Health rămâne public; pentru snapshot,
sesiuni, evenimente și comenzi configurați credențialele din
[SECURITY.md](SECURITY.md). Nu există token implicit. Fără configurare,
rutele protejate răspund 503; autentificarea greșită primește 401, iar
rolul insuficient 403. Profilul anonim de dezvoltare trebuie activat
explicit și nu este permis în hardware.

Frontend-ul este inclus în checkout și folosește adaptorul HTTP ParkingApi,
cu polling, validare după schema OpenAPI și token introdus la rulare.
[Instrucțiuni frontend](../frontend/README.md). Testele Playwright pornesc
frontend și backend reale pe baze temporare, verifică fluxul de parcare,
modul hardware fără dispozitive și un răspuns pierdut la comandă.

[ARCHITECTURE.md](ARCHITECTURE.md) descrie controller-ele, serviciile,
repository-ul și tranzacțiile. [PR9_REMEDIATION.md](PR9_REMEDIATION.md)
mapează remedierea feedbackului de review. Workflow-ul Backend CI rulează
testele Python și verificarea contractelor, plus build/teste/E2E frontend.
Existența workflow-ului nu înseamnă că a rulat deja pe GitHub.

## Fișiere și stadiu

- `app/main.py`: configurarea aplicației FastAPI, lifespan și pornirea worker-elor.
- `app/controllers/`: rutele HTTP API v1, dependența către serviciu și tratarea erorilor HTTP.
- `app/services/`: fațada aplicației, servicii specializate și politica de tarifare, independente de FastAPI.
- `app/repositories/`: operațiile SQLite ale serviciilor, fără commit-uri proprii.
- `app/parking.py`: importuri de compatibilitate către serviciu; nu dublează implementarea.
- `pyproject.toml`: versiunea Python acceptată și dependențele directe.
- `uv.lock`: versiunile rezolvate ale dependențelor; se păstrează în Git.
- [contracts/README.md](contracts/README.md): contractele țintă API și MODBUS,
  diferențele față de frontend-ul demo și comenzile de generare/verificare.
- `app/contracts/`: modele validate; `contracts/openapi.v1.json` descrie
  rutele implementate și contractele de integrare.
- [BUSINESS.md](BUSINESS.md): serviciul tranzacțional din pasul 3,
  recuperarea după restart și limitele de integrare cu simulatorul/hardware-ul.
- [API.md](API.md): configurația, rutele HTTP, worker-ul și verificarea pasului 4.
- [SIMULATOR.md](SIMULATOR.md): scenariul complet, controalele și persistența pasului 5.
- [HARDWARE.md](HARDWARE.md): configurarea TCP/RTU, polling-ul și limitele profilului v2.1.

Fișierele locale `package.json`, `package-lock.json` și `tsconfig.json`
provin din pregătirea anterioară Node.js și nu sunt folosite de acest backend.
Nu include în commit medii virtuale sau fișiere `.env` cu valori locale.
