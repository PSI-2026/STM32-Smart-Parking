# Backend STM32 Smart Parking

Backend Python + FastAPI, cu API HTTP, persistență SQLite și worker pentru
regulile parcării. Simulatorul complet și comunicația STM32 urmează;
fără adaptor, datele parcării sunt necunoscute.

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

## Integrare frontend

Compatibilitatea contractului a fost verificată prin inspecția branch-ului
`feature/frontend-dashboard`, la commit-ul
`5972a3e4beeeaaf52c062f684cc55d5074d20165`:

- [frontend/vite.config.ts](https://github.com/PSI-2026/STM32-Smart-Parking/blob/5972a3e4beeeaaf52c062f684cc55d5074d20165/frontend/vite.config.ts)
  transmite `/api` către `BACKEND_URL`, implicit `http://127.0.0.1:8000`.
- [frontend/src/api/backendHealth.ts](https://github.com/PSI-2026/STM32-Smart-Parking/blob/5972a3e4beeeaaf52c062f684cc55d5074d20165/frontend/src/api/backendHealth.ts)
  apelează `/api/v1/health` și cere `status: "healthy"`,
  `service: "smart-parking-backend"` și o versiune text nevidă.
- [frontend/scripts/test-backend.mjs](https://github.com/PSI-2026/STM32-Smart-Parking/blob/5972a3e4beeeaaf52c062f684cc55d5074d20165/frontend/scripts/test-backend.mjs)
  verifică acest contract prin HTTP, prin proxy-ul frontend.

Răspunsul backend-ului respectă aceste cerințe. Codul frontend nu este inclus
în checkout-ul acestui branch; verificarea contractului prin inspecție nu
înlocuiește rularea testului de integrare cu ambele servere pornite.

## Fișiere și stadiu

- `app/main.py`: aplicația FastAPI, lifespan și rutele API v1.
- `pyproject.toml`: versiunea Python acceptată și dependențele directe.
- `uv.lock`: versiunile rezolvate ale dependențelor; se păstrează în Git.
- [contracts/README.md](contracts/README.md): contractele țintă API și MODBUS,
  diferențele față de frontend-ul demo și comenzile de generare/verificare.
- `app/contracts/`: modele validate; `contracts/openapi.v1.json` descrie
  rutele implementate și contractele de integrare.
- [BUSINESS.md](BUSINESS.md): serviciul tranzacțional din pasul 3,
  recuperarea după restart și limitele de integrare cu simulatorul/hardware-ul.
- [API.md](API.md): configurația, rutele HTTP, worker-ul și verificarea pasului 4.

Fișierele locale `package.json`, `package-lock.json` și `tsconfig.json`
provin din pregătirea anterioară Node.js și nu sunt folosite de acest backend.
Nu include în commit medii virtuale sau fișiere `.env` cu valori locale.
