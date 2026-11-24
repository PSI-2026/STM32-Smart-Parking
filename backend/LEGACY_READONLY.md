# STM32 v1.0: diagnostic USB/RTU numai pentru citire

Mert a verificat placa STM32F429Discovery prin ST-LINK VCP la **115200 8N1**.
FC03, Unit ID 1, offset 0, count 6 a întors `[1,256,1,0,0,1]`.
FC04 pentru profilul distribuit nu este suportat; Unit ID 247 nu a răspuns.
Rezultatul este în [PR #13](https://github.com/PSI-2026/STM32-Smart-Parking/pull/13#issuecomment-7109112036).

Profilul `hybrid-v1-readonly` citește exact cele șase registre, fără detecție
automată, scanare de noduri sau conversie la topologia distribuită v2.1.
Este un profil separat de diagnostic, nu un adaptor pentru accesul în parcare.

## Pornire din rădăcina repository-ului, în PowerShell

Oprește alte aplicații care folosesc portul serial și alege portul real al plăcii.
Folosește o bază nouă, separată de simulare și de profilul distribuit.
Variabilele sunt citite din proces; fișierele `.env` nu sunt încărcate automat.

```powershell
$env:PARKING_MODE = 'hardware'
$env:PARKING_TRANSPORT = 'USB'
$env:PARKING_HARDWARE_PROFILE = 'hybrid-v1-readonly'
$env:PARKING_HARDWARE_ENABLED = 'true'
$env:PARKING_DATABASE_PATH = 'backend/data/legacy-readonly.sqlite3'
$env:PARKING_MODBUS_SERIAL_PORT = 'COM3' # înlocuiește cu portul real
$env:PARKING_MODBUS_BAUDRATE = '115200'
$env:PARKING_MODBUS_PARITY = 'N'
$env:PARKING_LEGACY_UNIT_ID = '1'
$env:PARKING_LEGACY_POLL_INTERVAL_SECONDS = '0.5'
$env:PARKING_LEGACY_STALE_AFTER_MS = '2000'
$env:PARKING_VIEWER_TOKEN = uv run --project backend python -c "import secrets; print(secrets.token_hex(32))"
uv run --project backend uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Păstrează tokenul în sesiunea locală și introdu-l în formularul de acces al
frontend-ului, pornit conform [instrucțiunilor sale](../frontend/README.md).
Alternativ, citește `GET /api/v1/diagnostics/legacy` cu antetul
`Authorization: Bearer <token>`. Health rămâne public.

## Semantica observației

| Registru | Interpretare |
| --- | --- |
| HR0 | Unit ID; trebuie să corespundă configurației |
| HR1 | versiune 0x0100 (256) |
| HR2 | sănătate raportată: 1 normal, 2 defect barieră |
| HR3 | ocuparea fizică P01: 0/1 |
| HR4 | mască ocupare; bitul 0 trebuie să coincidă cu HR3 |
| HR5 | mască validitate; numai bitul 0 este folosit pentru P01 |

`quality: reported` înseamnă răspuns recent și bitul P01 cunoscut.
`occupied` este `false` sau `true` doar în acest caz. La timeout, CRC invalid,
identitate incompatibilă, bit necunoscut sau expirare devine `null`.
Vârsta include durata citirii și timpul monoton scurs de la răspuns.
**Aceasta dovedește numai comunicația recentă**: firmware-ul nu furnizează
boot, secvență de achiziție sau vechimea măsurătorii. Repetarea unui răspuns
nu poate demonstra că senzorul a fost achiziționat din nou.

Endpoint-ul citește cache-ul din memorie; cererile HTTP nu declanșează I/O serial.
Frontend-ul afișează o cartelă P01 separată și invalidează local răspunsul expirat.
P02–P04, capacitatea și barierele din snapshot-ul distribuit rămân necunoscute.
Nu se creează sesiuni și nu se confirmă treceri.

Worker-ul emite numai **FC03 / offset 0 / count 6**, la Unit ID configurat.
Nu pornește worker-ul de business sau adaptorul v2.1 și nu emite FC04, FC06 ori
FC16. Un filtru al PDU-urilor refuză alte funcții la ieșire. Toate comenzile HTTP,
inclusiv plata și demo, sunt refuzate cu 403 înainte de admitere.
Citirea poate totuși actualiza watchdog-ul de comunicație din firmware.
Profilul se leagă de baza SQLite: schimbarea profilului pe aceeași bază este
refuzată; o bază cu sesiuni, comenzi sau telemetrie distribuită nu poate fi convertită la v1 diagnostic.

## Validare

Testele software folosesc vectorul verificat de Mert, clientul serial configurat,
cadre RTU reale peste un flux TCP local (inclusiv CRC invalid), API autentificat
și izolarea față de capacitate și comenzi. Testul UI cu răspuns HTTP explicit
simulat verifică afișarea și indisponibilitatea; nu reprezintă un test pe placă.

Mert trebuie să verifice noua versiune pe portul fizic: P01 liber → ocupat → liber,
deconectare USB → necunoscut, reconectare → raportat și absența scrierilor MODBUS.
Compatibilitatea read-only pe placa reală rămâne de confirmat după această schimbare.
Profilul distribuit v2.1 rămâne implicit și necesită firmware-ul corespunzător.
