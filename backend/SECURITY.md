# Acces API

API-ul folosește tokenuri Bearer configurate pe server, cu trei roluri.
Nu există token implicit, cont demo sau secret inclus în frontend.

| Rol / variabilă | Permisiuni |
| --- | --- |
| viewer / PARKING_VIEWER_TOKEN | Snapshot, sesiuni, evenimente și rezultatele comenzilor. |
| operator / PARKING_OPERATOR_TOKEN | Citire și enter/pay/exit. |
| admin / PARKING_ADMIN_TOKEN | Citire, operații de parcare și controale demo în simulation. |

Configurați doar rolurile necesare. Tokenurile trebuie să fie distincte,
de minimum 32 de caractere fără spații; se recomandă generarea aleatoare.
În PowerShell, după instalarea dependențelor:

```powershell
$env:PARKING_ADMIN_TOKEN = (& backend/.venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(32))")
uv run --project backend --locked uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Introduceți tokenul din mediul serverului în câmpul „Token de acces” al
dashboard-ului. Frontend-ul îl ține numai în memorie, nu în bundle, fișiere
Vite sau browser storage. Pentru clienți HTTP folosiți antetul
`Authorization: Bearer <token>`, fără token în URL. `/docs` permite Authorize.

Health rămâne public și verifică numai serviciul HTTP. Restul rutelor sunt
protejate implicit. Fără configurarea vreunui token răspund 503; un token
lipsă sau greșit când accesul este configurat primește 401 cu
WWW-Authenticate: Bearer. Un rol insuficient primește 403. Aceste refuzuri
nu rezervă ID-ul comenzii, nu admit comenzi și nu emit MODBUS.

Modul hardware nu permite acces anonim. Chiar admin primește un refuz
persistent SIMULATION_ONLY pentru comenzile demo admise în hardware.
Pentru dezvoltare locală exclusiv în simulare există opțiunea explicită
`PARKING_ALLOW_ANONYMOUS_SIMULATION=true`; aceasta acordă rol admin fără
token și nu se folosește pentru acces partajat. Configurația o respinge
în hardware. Testele vechi de business activează explicit acest profil;
testele de securitate verifică profilul protejat implicit.

Rulați implicit pe loopback. Pentru acces din alt calculator, terminați
HTTPS într-un reverse proxy și limitați accesul la rețeaua proiectului;
Bearer nu criptează conexiunea. Tokenurile sunt credențiale comune pe rol,
nu identități individuale: nu oferă conturi, audit pe utilizator sau refresh
tokens. Revocarea/rotația se face prin schimbarea configurației serverului
și restart. Nu publicați tokenurile, bazele locale sau antetele Authorization.
