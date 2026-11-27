# Predare către Mert — validarea hardware

Responsabil pentru verificarea pe placă și port serial: Mert.
Această etapă nu este executată și nu este bifată de testele backend.

## Punctul de pornire

Backend-ul din PR #9 integrat implementează distributed-v2.1, schema 0x0201,
cu șase identități G/S1–S5, observație atomică FC04 de 37 de registre și
bloc FC16 de nouă cuvinte. Manifest:
[contracts/modbus-parking.v2.json](contracts/modbus-parking.v2.json).

Firmware-ul integrat prin PR #8 este RTU v1.0, schema 0x0100, cu FC03/FC06,
o poartă logică partajată și altă hartă de registre. Matricea echipei
[COMPATIBILITATE_BACKEND.md](../docs/firmware/COMPATIBILITATE_BACKEND.md)
documentează incompatibilitatea. Nu activați adaptorul de control backend
ca și cum aceste două profiluri ar fi deja compatibile. Nu există fallback
prin scriere sau conversie implicită a hărții.

Mert trebuie întâi să confirme revizia de protocol vizată împreună cu echipa:
implementarea profilului firmware compatibil sau o adaptare software
versionată, cu reguli de prospețime, idempotentă și dovadă aprobate explicit.
Acest PR nu schimbă protocolul și nu activează actuatorul/buzzerul.

## Ordinea verificărilor și dovezile de păstrat

1. Notați commit-urile backend/firmware, placa și revizia, portul, baud rate,
   paritatea și Unit ID-urile reale. v1.0 documentează 115200 8N1; exemplul
   backend 19200 N nu reprezintă o configurație fizică validată.
2. Urmați verificările electrice și de siguranță din
   [VALIDARE_HARDWARE.md](../docs/firmware/VALIDARE_HARDWARE.md), fără a
   înlocui acel checklist cu o verificare de API health.
3. După alinierea protocolului, verificați întâi numai citirile: identitate,
   rol, schemă, boot, secvență, vârstă, măști și coerența unui singur FC04.
   Salvați cererea/răspunsul brut și decodarea, pe fiecare Unit ID.
4. Verificați deconectarea unei stații și a gateway-ului, reconectarea,
   secvența înghețată, restartul MCU și invalidarea imediată a datelor vechi.
   Nodurile lipsă nu trebuie numărate ca locuri libere.
5. Pentru v2.1, demonstrați FC06 HR4=1 la stația țintă S3/S4, nu doar la G,
   apoi FC16 HR0x0100 cu nouă cuvinte și autorizarea corectă pe bandă.
   Verificați interblocările local, expirarea lease-ului și boot mismatch.
6. Pierdeți controlat răspunsul după executarea comenzii. Backend-ul trebuie
   să citească rezultatul blocului original, fără retrimitere automată sau
   ID înlocuitor. Verificați ecoul complet, nu doar ID-ul numeric.
7. Verificați separat TCP și RTU/USB conform hardware-ului disponibil.
   Testele RTU pe flux TCP din backend nu validează cablarea/driverul VCP.
8. Stabiliți dovada de trecere. Profilul v2.1 actual raportează unavailable:
   actuator done nu finalizează sesiunea și nu eliberează claim-ul.
   Confirmarea fizică necesită un contract nou de dovadă sau reconciliere
   explicită; nu se deduce din vehiclePresent sau poziția barierei.

Pentru fiecare caz se notează: revizii, configurație fără tokenuri, pașii,
rezultatul așteptat/observat, captură brută, verdict și defectul aferent.
După modificarea protocolului se refac testele backend afectate și E2E.

## Configurarea backendului după compatibilizare

Folosiți o bază separată de simulare, PARKING_MODE=hardware și credențiale
conform SECURITY.md. PARKING_HARDWARE_ENABLED rămâne false până la profilul
compatibil; apoi se activează explicit, cu transportul/adresa configurate
conform HARDWARE.md. Health poate fi healthy chiar când toate stațiile sunt
necunoscute. Verdictul hardware se raportează separat în documentația de
firmware și nu este dedus din închiderea predării software.
