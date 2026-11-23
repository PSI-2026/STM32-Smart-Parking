# Remedieri pentru feedbackul PR #9

Acest document mapează cerințele review-ului GitHub din 23 noiembrie 2026
la modificările locale propuse pentru următoarea rundă de review.

| Feedback | Modificare | Verificare |
| --- | --- | --- |
| Separare layered/MVC | Controllers pentru HTTP/erori/acces, services pentru aplicație, repositories pentru SQL, contracts pentru scheme; main doar configurează lifecycle-ul. | Teste HTTP și izolarea a două aplicații. Vezi ARCHITECTURE.md. |
| ParkingService prea concentrat | Fațadă plus cinci servicii specializate, tarif comun, 60 de operații SQL denumite și paginare în repository. | Aceleași teste de business/concurență/rollback/restart; tranzacția rămâne deținută de operația de aplicație. |
| Autentificare/autorizare | Bearer cu viewer/operator/admin, acces protejat implicit, refuzuri înainte de admitere și niciun mod anonim hardware. | test_security.py; OpenAPI declară security și 401/403. Vezi SECURITY.md. |
| CI backend | .github/workflows/backend.yml: teste Python pe Ubuntu și Windows, export --check, teste/build frontend și E2E Chromium cu API real. | Comenzile se rulează local; execuția pe runner-ele GitHub va putea fi confirmată numai după publicare. |
| Integrare/documentație | ParkingApi HTTP cu polling, validare după OpenAPI, date necunoscute, comenzi persistente și autentificare runtime; teste de browser separate. | Testele E2E pornesc React/Vite, FastAPI și baze temporare reale, inclusiv modul hardware fără dispozitiv. |

Implementarea MODBUS nu echivalează cu validarea STM32. Testele transportului
folosesc servere locale și cadre TCP/RTU; testele de browser folosesc simulatorul
de backend sau hardware fără adaptor activ. Portul serial fizic, rutarea,
lease-ul, atomicitatea firmware și pierderea răspunsului după execuția fizică
rămân de validat pe dispozitiv conform HARDWARE.md.

Nu se declară CI verde pe GitHub sau validare fizică înainte de executarea lor.
Schimbările sunt publicate direct în PR #9 pentru review-ul colegului,
conform strategiei actualizate a echipei. Verificările locale nu înlocuiesc
review-ul sau validarea hardware.
