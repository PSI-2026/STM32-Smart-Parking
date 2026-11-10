# STM32 Smart Parking

Sistem inteligent de parcare bazat pe STM32F429 si protocolul MODBUS RTU.

**Disciplina:** Proiectarea Sistemelor Inglobate  
**Organizatie:** PSI-2026  
**Platforme:** macOS si Windows  
**Stadiu:** In dezvoltare
**Echipa:** 3 studenti

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

Proiectul este dezvoltat de o echipa formata din **3 studenti**, cu responsabilitati distribuite pe trei domenii principale.

### Embedded Systems & Firmware

- Configurarea microcontrolerului STM32F429.
- Implementarea firmware-ului in limbajul C.
- Gestionarea senzorilor, LED-urilor si servomotoarelor.
- Implementarea protocolului MODBUS RTU Slave.
- Simularea si depanarea firmware-ului folosind Renode si GDB.

### Backend & Communication

- Dezvoltarea serverului Node.js si TypeScript.
- Implementarea comunicatiei MODBUS RTU Master.
- Gestionarea sesiunilor de parcare si a vehiculelor.
- Calcularea duratei si a taxelor de parcare.
- Implementarea sistemului de plata simulata si a jurnalizarii evenimentelor.

### Frontend & Dashboard

- Dezvoltarea interfetei web folosind React si TypeScript.
- Realizarea reprezentarii grafice a parcarii.
- Afisarea starii locurilor de parcare in timp real.
- Dezvoltarea interfetei pentru vehicule, bariere si plati.
- Integrarea interfetei cu API-ul backend.

### Responsabilitati comune

Toti membrii echipei participa la integrarea componentelor, testare, documentatie, code review si solutionarea problemelor tehnice.

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
