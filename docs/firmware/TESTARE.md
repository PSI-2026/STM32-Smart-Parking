# Testare software

| Nivel | Comandă | Rezultat 2026-11-23 |
|---|---|---|
| Teste native, ASan, UBSan, analiză | `make -C firmware/tests check` | trecut; avertismente clang-tidy documentate |
| Cross build Debug | GCC ARM 15.3, compilare C11 cu `-Wall -Wextra -Werror` și link cu obiectele CubeIDE | ELF legat; text 20.948 B, bss 2.428 B |
| Cross build Release | aceeași verificare cu `-Os` | ELF legat; text 11.288 B, bss 2.428 B |
| Renode | scenariu hardware-specific neintegrat | neexecutat pentru noul protocol |
| Placă fizică | test manual | neexecutat |

Testul nativ nou acoperă ocuparea mixtă, necunoscută și expirată, poarta unică, cereri duplicate/conflictuale, expirarea ciclului, reapariția obstacolului, depășirea contorului de timp, buzzerul, CRC, ID nod și excepții MODBUS. Testele istorice rămân în suită și rulează separat.

Buildurile CubeIDE generate nu includ automat fișierele C noi până la regenerarea proiectului în IDE. La verificarea locală, obiectele noi au fost compilate separat și adăugate la link prin `USER_OBJS`, apoi toate fișierele modificate au fost compilate din nou cu `-Werror` și legate cu obiectele CubeIDE. Toolchainul instalat, GCC 15.3, nu acceptă `-fcyclomatic-complexity` din makefileurile generate pentru 14.3; flagul a fost eliminat numai temporar din fișierele de build ignorate și apoi restaurat. Un build curat din IDE cu regenerarea listei de surse rămâne necesar.

`clang-tidy` a raportat în principal parametri numerici adiacenți care pot fi inversați și identificatorul rezervat `__MAIN_H` din headerul generat. Nu au apărut erori de analiză care să oprească `check`. Tratați aceste avertismente la următoarea refactorizare a API-ului.

## Regresii adaugate la review-ul PR #8

`test_hybrid.c` verifica acum buffer-ele de raspuns cu capacitati 0..8, lipsa
scrierilor si a comenzilor de poarta cand confirmarea nu incape, doua cadre
RTU consecutive cu pauza de 1750 us fara procesare intermediara, pragul de
1749/1750 us, pauze interne invalide, erori UART, cadre supradimensionate,
saturarea cozii si revenirea la zero a contorului. Frecventa reala de 25 MHz
este verificata separat prin scalarea pragurilor de timp.

Noul modul `modbus_rtu_rx.c` participa la testele native, ASan, UBSan si analiza
statica din Makefile. Dimensiunile ELF si RAM din tabelul initial preced aceste
remedieri; este necesar un nou build CubeIDE pentru valorile finale si un test
pe placa pentru temporizarea UART/DWT. Testele host nu confirma transportul
fizic.