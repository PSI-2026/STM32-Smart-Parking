# Straturile backendului

Fluxul unei cereri este `controller → ParkingService → serviciu specializat
→ repository`, cu DTO-urile validate în `app/contracts/`. Simulatorul și
worker-ul hardware folosesc aceeași fațadă de aplicație, fără HTTP intern.

| Componentă | Responsabilitate |
| --- | --- |
| app/main.py | Composition root: configurație, lifespan, instanțe și worker-e. |
| app/controllers/parking.py | APIRouter și controller-ele celor șapte operații HTTP. |
| app/controllers/errors.py | Erori HTTP uniforme și politica no-store. |
| app/controllers/security.py | Autentificare Bearer și autorizarea acțiunilor. |
| app/contracts/ | Stratul de scheme API/firmware; sursa artefactelor generate. |
| app/services/parking.py | Fațadă stabilă și context comun: baza, ceasurile, configurația, repository și serviciile. |
| app/services/commands.py | Admitere idempotentă, tranziții, procesare și selecția cozii. |
| app/services/sessions.py | Sesiuni, plata simulată și verificarea contradicțiilor unei sesiuni. |
| app/services/access.py | Pregătire, dispatch, rezultate MCU, dovezi de trecere și recuperare. |
| app/services/telemetry.py | Capacitate, calitatea cache-ului și transferul claim-urilor către ocupare. |
| app/services/queries.py | Snapshot, evenimente, interogări și paginare. |
| app/services/common.py | Erori de aplicație, valoarea admiterii și politica de tarifare. |
| app/repositories/parking.py | Operații SQLite denumite; nu decide reguli de business și nu face commit. |
| app/storage.py | Schema, migrări, conexiuni și unitatea de lucru SQLite cu savepoint-uri. |
| app/telemetry.py, observations.py | Normalizare și istoric de prospețime/identitate, în tranzacția apelantului. |
| app/modbus.py, hardware.py, simulator.py | Transport fizic, coordonare hardware și dispozitiv virtual persistent. |

Router-ul și controller-ele sunt colocate deoarece rutele sunt subțiri;
schemele existente rămân în contracts, nu sunt duplicate într-un alt director.
`app/parking.py` reexportă obiectele existente pentru compatibilitatea
importurilor. Nu mai conține reguli de parcare sau o a doua implementare.

Serviciile sunt compuse explicit de fațadă. Ele folosesc același context și
apelează colaboratorii prin fațadă pentru a păstra injecția din teste și
compatibilitatea worker-elor. Repository-ul primește conexiunea deschisă de
operația de aplicație. Nu deschide conexiuni proprii, nu face commit/rollback
și nu fragmentează o operație în tranzacții pe serviciu.

Astfel, verificarea capacității, sesiunea, claim-ul și maparea MCU rămân
atomice. Același lucru se aplică dovezii de trecere și transferului ocupării.
BusinessFault revine în HTTP numai prin controller; serviciile nu importă
FastAPI/Starlette și nu construiesc răspunsuri HTTP.

SQL-ul din operațiile de business a fost extras în repository. Infrastructura
istoricului de telemetrie și simulatorul au propriile operații SQL de stare;
acestea folosesc unitatea de lucru comună și nu execută I/O fizic în tranzacții.

Testele existente de concurență, rollback injectat, restart, deduplicare,
contradicții și timeout protejează această delimitare. Testele HTTP verifică
și două aplicații cu servicii/configurații/baze independente.
