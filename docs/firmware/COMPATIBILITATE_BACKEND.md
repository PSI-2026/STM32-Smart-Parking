# Compatibilitate firmware și backend

Această matrice compară firmware-ul MODBUS RTU v1.0 din `origin/main` la
`6acd3b1` cu profilul distribuit v2.1 descris de contractul backend de pe
`origin/feature/backend-complete`. Analiza este read-only pentru ramura
backend; niciun fișier din PR #9 nu a fost modificat. Contractul v2.1 este
țintă software, nu dovadă de suport sau validare pe placa STM32.

**Notă privind versiunile analizate:** Commit-ul `792d8bc`, menționat în planul
inițial, reprezintă starea repository-ului înainte de integrarea PR #7 și PR #8.
Matricea de mai jos folosește intenționat commit-ul `6acd3b1`, starea firmware-ului
după integrarea PR #8, care include implementarea MODBUS RTU v1.0 analizată aici.
Cele două commit-uri descriu etape diferite ale dezvoltării; comparația rămâne
ancorată la `6acd3b1` și nu este contradictorie cu referința istorică `792d8bc`.

| Domeniu | Firmware v1.0 implementat | Backend v2.1 vizat | Compatibilitate |
|---|---|---|---|
| Topologie | Un STM32, ID implicit 1; poate fi construit cu alt ID. P01 este intrarea fizică, P02–P04 sunt valori primite de la backend. O singură poartă logică partajată. | Gateway G (247), stații S1–S5 (1–5); S1/S2 raportează parcarea, S3/S4 sunt bariere separate, S5 identitate de nod. | Incompatibilă: un nod cu o poartă nu reprezintă cele șase roluri distribuite. |
| Funcții MODBUS | FC03 citește registre Holding; FC06 scrie un singur registru Holding. | FC04 citește registre Input; FC06 reînnoiește lease-ul la nodul țintă; FC16 scrie atomic blocul de comandă. | Incompatibilă: firmware-ul nu implementează FC04 sau FC16. |
| Telemetrie și hartă | Registre v1.0 la `0x0000–0x0010` și jurnal volatil compact la `0x0020–0x002F`. Valorile se citesc în FC03; citiri separate nu sunt o mostră atomică. | Identitate FC04 la offset 0, 3 registre; observație FC04 atomică la IR `0x0300`, 37 registre. Include schema, rol, boot epoch, secvență, vârstă, validitate, payload și ultimul rezultat de comandă. | Incompatibilă: adresele, obiectele de date și garanțiile de coerență diferă. |
| Comandă | FC06 la HR `0x0100` setează secvența u16; `0x0101` cere direcția; simularea folosește scrieri separate la `0x0102–0x0104`. FC06 `0x0105` resetează defectul numai în simulare. | FC16 la HR `0x0100–0x0108` transmite ID u32, operație, TTL, autorizare și boot epoch; FC06 la HR `0x0004` reînnoiește lease-ul de control. | Incompatibilă: formatul, atomicitatea, lățimea secvenței și mecanismul de autorizare diferă. |
| Confirmare | Răspunsul FC06 confirmă acceptarea scrierii. Registrele și evenimentele indică progres local ulterior; FC06 nu dovedește trecerea vehiculului. | Rezultatul este demonstrat printr-o înregistrare atomică ce trebuie să corespundă nodului, boot-ului, ID-ului și tuturor celor nouă cuvinte FC16. Trecerea este o dovadă separată, indisponibilă în modul hardware v2.1. | Incompatibilă: firmware-ul v1.0 nu păstrează dovada de comandă corelată cerută de v2.1. |
| Prospețime și restart | Comunicația devine activă după un cadru valid și expiră după 5 s. Datele simulate au timeout local. Nu există boot epoch sau secvență de achiziție persistentă. | Backend-ul verifică vârsta mostrei, progresul secvenței, boot epoch și calea prin gateway; datele vechi sau incoerente devin necunoscute. | Incompatibilă pentru validarea prospețimii și recuperarea după restart. |
| Stare de siguranță | Validarea capacității și interblocările porții sunt locale. Configurația curentă pornește poarta în `GATE_SIMULATION`; ieșirile fizice pentru actuator și buzzer nu sunt activate. | Politica v2.1 cere lease verificat local pentru deschidere, interblocare locală și raportarea separată a rezultatului actuatorului. Contractul nu permite ca backend-ul să substituie logica locală de siguranță. | Doar unele principii sunt compatibile; topologia și semantica de control nu sunt. |
| Evenimente și istoric | Coada volatilă păstrează până la 8 evenimente, cu numere u16 și fără persistență MCU. | Backend-ul corelează comenzile persistente și dovezile; păstrează istoricul aplicației și tratează lipsa dovezii ca rezultat necunoscut. | Incompatibilă fără adaptor versionat și reconciliere explicită. |

## Decizie de integrare

Backend-ul v2.1 nu poate trimite comenzi hardware către firmware-ul v1.0 în
siguranță. Nu se face autodetectare prin scriere, fallback la harta v1.0 sau
reducere tacită a contractului. Până la o implementare firmware v2.1 și
validarea ei, transportul hardware trebuie să rămână dezactivat sau să
refuze pornirea cu o eroare de incompatibilitate. O integrare simulată poate
folosi adaptorul de simulare deja prevăzut, cu sursa și dovezile marcate
explicit ca simulare.

Următorul pas de firmware este definirea și testarea unei revizii de protocol
versionate, apoi implementarea minimă necesară pentru identitate, mostre
atomice, freshness și rezultate de comandă. Acel pas trebuie tratat separat
de stabilizarea v1.0 și nu este inclus aici.
