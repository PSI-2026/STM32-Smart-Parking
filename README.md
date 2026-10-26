# STM32 Smart Parking

Sistem inteligent de parcare bazat pe STM32F429 si protocolul MODBUS RTU.

**Disciplina:** Proiectarea Sistemelor Inglobate  
**Organizatie:** PSI-2026  
**Echipa:** 2 studenti  
**Platforme:** macOS si Windows  
**Stadiu:** In dezvoltare

## 1. Descriere

Proiectul urmareste implementarea si simularea unui sistem de parcare cu patru locuri monitorizate individual, doua bariere automate si un sistem de gestionare a platilor.

Microcontrolerul STM32F429 va gestiona senzorii si dispozitivele de control, comunicand cu aplicatia PC prin MODBUS RTU.

## 2. Functionalitati propuse

- Detectarea ocuparii a patru locuri de parcare.
- Semnalizare cu LED rosu si verde pentru fiecare loc.
- Controlul a doua bariere prin servomotoare.
- Monitorizarea numerelor de inmatriculare.
- Calculul duratei si taxei de parcare.
- Simularea confirmarii platii.
- Comunicatie MODBUS RTU Master-Slave.
- Inregistrarea evenimentelor sistemului.
- Interfata grafica pentru monitorizare si control.

## 3. Tehnologii

| Componenta | Tehnologie |
| --- | --- |
| Microcontroler | STM32F429, ARM Cortex-M4 |
| Firmware | C, STM32 HAL |
| IDE | STM32CubeIDE |
| Simulare | Renode |
| Comunicare | MODBUS RTU |
| Backend | Node.js, TypeScript |
| Frontend | React, TypeScript, Vite |
| Versionare | Git si GitHub |

## 4. Structura proiectului

- `firmware/` - codul sursa STM32 si configuratia perifericelor.
- `simulation/renode/` - configuratii si scenarii de simulare.
- `backend/` - MODBUS Master, sesiuni si plati.
- `frontend/` - interfata grafica a parcarii.
- `docs/` - documentatie tehnica.
- `.github/workflows/` - automatizarea testelor si build-urilor.

## 5. Arhitectura

Frontend React
    |
    v
Backend Node.js (MODBUS Master)
    |
    v
Comunicatie MODBUS RTU prin UART simulat
    |
    v
Renode + STM32F429 (MODBUS Slave)
    |
    v
Senzori, LED-uri si bariere virtuale

## 6. Organizarea echipei

### Studentul 1 - Embedded Systems

- Configurarea microcontrolerului.
- Implementarea firmware-ului STM32.
- Controlul senzorilor, LED-urilor si barierelor.
- Implementarea MODBUS Slave.
- Testarea firmware-ului in Renode.

### Studentul 2 - Software Development

- Dezvoltarea backend-ului.
- Implementarea MODBUS Master.
- Dezvoltarea interfetei grafice.
- Gestionarea vehiculelor si platilor.
- Implementarea jurnalizarii.

Integrarea, testarea finala si documentatia sunt responsabilitati comune.

## 7. Dezvoltare colaborativa

Repository-ul este organizat pentru dezvoltare pe macOS si Windows.

Reguli generale:

1. Fiecare functionalitate se dezvolta intr-un branch separat.
2. Modificarile se integreaza prin Pull Request.
3. Nu se includ fisiere generate de compilare.
4. Configuratiile comune sunt versionate in Git.
5. Codul nou trebuie testat inainte de integrare.

## 8. Etape de dezvoltare

- [ ] Configurarea mediului de dezvoltare.
- [ ] Implementarea senzorilor si LED-urilor.
- [ ] Implementarea controlului barierelor.
- [ ] Implementarea MODBUS RTU.
- [ ] Integrarea simulatorului Renode.
- [ ] Dezvoltarea backend-ului.
- [ ] Dezvoltarea interfetei grafice.
- [ ] Implementarea sistemului de plata simulata.
- [ ] Testare si documentatie finala.

## 9. Observatii

Plata va fi simulata, fara tranzactii bancare reale.

Recunoasterea automata a numerelor de inmatriculare prin camera reprezinta o extensie optionala.

Proiectul va urmari cerintele disciplinei privind comunicatia MODBUS, achizitia de date, controlul si jurnalizarea.
