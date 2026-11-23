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
