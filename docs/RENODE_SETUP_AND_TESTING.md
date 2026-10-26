# Renode & GDB — Ghid de instalare si testare STM32 Smart Parking

**Proiect:** PSI-2026 / STM32-Smart-Parking  
**Sisteme de operare:** macOS (Apple Silicon) si Windows  
**Tinta:** STM32F429ZITx · STM32CubeIDE · STM32 HAL · Renode 1.17.0  
**Ultima actualizare:** 26 octombrie 2026

## 1. Ce putem testa acum?

Acest ghid permite unui coleg care nu a folosit Renode sa configureze simularea, sa porneasca firmware-ul si sa verifice senzori/LED-uri prin GDB, **fara placa fizica STM32**.

**Testat in proiect:** logica pentru `PARK1` — tranzitia **liber → ocupat → liber**. **Nu sunt inca implementate si verificate aici:** PARK2–PARK4, controlul barierelor, MODBUS RTU, backend-ul sau interfata React. Configurarea pinilor in CubeMX nu inseamna ca logica lor este implementata.

## 2. Instalarea instrumentelor

Avem nevoie de:

- **Git** — https://git-scm.com/downloads
- **STM32CubeIDE** — https://www.st.com/en/development-tools/stm32cubeide.html
- **Renode 1.17.0** — https://github.com/renode/renode/releases/tag/v1.17.0
- **ARM GDB (`arm-none-eabi-gdb`)** — distribuit impreuna cu STM32CubeIDE; nu necesita o instalare separata in acest flux.

### macOS

Cu [Homebrew](https://brew.sh/):

```bash
brew install renode/tap/renode
renode
```

Alternativ, instaleaza pachetul oficial `renode-1.17.0.osx-arm64-portable.dmg` pentru Apple Silicon. Inchide Renode dupa ce ai confirmat ca fereastra Monitor porneste.

### Windows

1. Instaleaza Git si STM32CubeIDE pentru Windows.
2. Descarca `renode-1.17.0.setup.exe` din pagina oficiala Renode 1.17.0.
3. Ruleaza instalarea; selecteaza optiunea pentru PATH daca este disponibila.
4. Porneste **Renode** din Start Menu. Daca instalarea a adaugat comanda in PATH, poti rula `renode` si in PowerShell.

**Important:** folositi aceeasi versiune Renode (1.17.0) pentru rezultate comparabile. Nu instalati un build nightly doar pentru acest tutorial.

## 3. Clonare si import firmware

Repository: https://github.com/PSI-2026/STM32-Smart-Parking

Intr-un terminal (macOS sau PowerShell Windows):

```bash
git clone --branch feature/stm32-firmware https://github.com/PSI-2026/STM32-Smart-Parking.git
cd STM32-Smart-Parking
```

Daca exista deja o copie locala, verificati mai intai modificarile nesalvate (`git status`), apoi:

```bash
git fetch origin
git switch feature/stm32-firmware
git pull --ff-only
```

In **STM32CubeIDE**: **File → Import → Existing Projects into Workspace**. Alegeti directorul:

```text
firmware/STM32_SmartParking/
```

Dupa import, selectati configuratia **Debug** si **Project → Build Project**. Rezultatul dorit:

```text
Build Finished. 0 errors, 0 warnings.
```

Fisierul compilat trebuie sa existe aici:

```text
firmware/STM32_SmartParking/Debug/STM32_SmartParking.elf
```

**ELF-ul este produs local prin build si nu este stocat in Git.** Daca lipseste, compilati din nou. Nu confundati fisierul `.ioc` (configuratie CubeMX) cu fisierul `.elf` (firmware executabil).

## 4. Pregatirea fisierului ELF

Folositi exact **acelasi** fisier ELF pentru Renode si GDB, pentru a pastra simbolurile corespunzatoare codului executat.

### macOS (din radacina repository-ului)

```bash
cp firmware/STM32_SmartParking/Debug/STM32_SmartParking.elf /tmp/smart-parking-v1.elf
ls -lh /tmp/smart-parking-v1.elf
```

### Windows (PowerShell, din radacina repository-ului)

```powershell
Copy-Item .\firmware\STM32_SmartParking\Debug\STM32_SmartParking.elf C:\Users\Public\smart-parking-v1.elf
Get-Item C:\Users\Public\smart-parking-v1.elf
```

## 5. Renode Monitor — pornirea microcontrolerului

Deschideti aplicatia **Renode**. In **fereastra Renode Monitor** (nu in PowerShell, nu in GDB), introduceti **fiecare comanda separat**:

```renode
mach create "STM32_SmartParking"
machine LoadPlatformDescription @platforms/cpus/stm32f429.repl
```

Incarcati imaginea potrivita pentru sistemul utilizat:

**macOS:**

```renode
sysbus LoadELF @/tmp/smart-parking-v1.elf
```

**Windows:**

```renode
sysbus LoadELF @C:/Users/Public/smart-parking-v1.elf
```

Daca pe Windows calea nu este acceptata, confirmati ca fisierul exista si folositi o cale absoluta corecta. Monitor foloseste sintaxa `@<cale>`; evitati sa scrieti calea cu spatii neprotejate.

Porniti serverul GDB:

```renode
machine StartGdbServer 3333
```

Mesajul de succes mentioneaza **portul 3333**. **Pastrati Renode deschis**.

## 6. GDB — conectare si oprire in `main()`

Deschideti **un al doilea terminal**, fara a inchide Renode.

### macOS

```bash
GDB=$(find /Applications/STM32CubeIDE.app/Contents/Eclipse/plugins -name arm-none-eabi-gdb -type f -print -quit)
"$GDB" /tmp/smart-parking-v1.elf
```

Daca `GDB` este gol, localizati aplicatia STM32CubeIDE instalata pe calculator.

### Windows — PowerShell

Cautati executabilul GDB in locul unde a fost instalat STM32CubeIDE. De exemplu, pentru instalarea in `C:\ST`:

```powershell
$gdb = Get-ChildItem 'C:\ST' -Filter arm-none-eabi-gdb.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
$gdb
& $gdb 'C:\Users\Public\smart-parking-v1.elf'
```

Daca `$gdb` este gol, cautati fisierul in directorul real de instalare STM32CubeIDE. Nu continuati pana cand promptul **`(gdb)`** nu apare.

### In GDB (identic pe ambele sisteme)

```gdb
target remote localhost:3333
break main
monitor start
continue
```

Rezultat asteptat: `Breakpoint 1, main()`; in build-ul actual apare in apropierea apelului `HAL_Init()`. Mesajul `Emulation is already started. Ignoring command` este inofensiv.

Apoi stabiliti un breakpoint in ciclul de control PARK1:

```gdb
break HAL_Delay
continue
```

Rezultatul actual asteptat este `HAL_Delay (Delay=50)`. In aceasta pozitie LED-urile au fost deja actualizate pentru iteratia curenta. Daca in viitor apar mai multe apeluri `HAL_Delay`, verificati ca ati oprit executia in bucla corecta.

## 7. Pinii PARK1 si registrele STM32

| Semnal | Pin | Registru | Adresa | Masca |
| --- | --- | --- | --- | --- |
| Senzor PARK1 | **PE2** | GPIOE_IDR | `0x40021010` | `0x04` (bit 2) |
| LED verde | **PE6** | GPIOE_ODR | `0x40021014` | `0x40` (bit 6) |
| LED rosu | **PF6** | GPIOF_ODR | `0x40021414` | `0x40` (bit 6) |

In firmware: **PE2=0 → loc liber**, **PE2=1 → loc ocupat**. Pentru LED-uri, valoarea 1 inseamna iesire activa.

Cititi registrele in **GDB**, cu **Enter dupa fiecare comanda**:

```gdb
x/1wx 0x40021010
x/1wx 0x40021014
x/1wx 0x40021414
```

**Atentie:** verificati doar bitul relevant, nu intreaga valoare hexazecimala a portului; alte pinuri pot avea si ele biti setati.

## 8. Test complet: liber → ocupat → liber

Cele doua ferestre au roluri diferite:

- **Renode Monitor:** simuleaza schimbarea senzorului PE2.
- **GDB:** continua rularea pana la `HAL_Delay(50)` si inspecteaza registrele.

### Test A — loc liber

In **Renode Monitor**:

```renode
sysbus.gpioPortE OnGPIO 2 false
```

In **GDB** (daca este oprit la breakpoint):

```gdb
continue
```

La urmatoarea oprire in `HAL_Delay(50)`, cititi cele trei registre folosind comenzile din sectiunea 7.

**Asteptat:** PE2=0, PE6=1, PF6=0 → **verde pornit, rosu oprit**.

### Test B — masina intra

In **Renode Monitor**:

```renode
sysbus.gpioPortE OnGPIO 2 true
```

In **GDB**:

```gdb
continue
```

La urmatorul breakpoint cititi cele trei registre.

**Asteptat:** PE2=1, PE6=0, PF6=1 → **verde oprit, rosu pornit**.

### Test C — masina pleaca

In **Renode Monitor**:

```renode
sysbus.gpioPortE OnGPIO 2 false
```

In **GDB**:

```gdb
continue
```

Cititi din nou cele trei registre la urmatorul breakpoint.

**Asteptat:** PE2=0, PE6=1, PF6=0 → **verde pornit, rosu oprit**.

### Rezultatele verificate in sesiunea noastra pe macOS

| Etapa | GPIOE_IDR | GPIOE_ODR | GPIOF_ODR | Verdict |
| --- | --- | --- | --- | --- |
| A: Liber | `0x00000040` | `0x00000040` | `0x00000000` | PASS |
| B: Ocupat | `0x00000004` | `0x00000004` | `0x00000040` | PASS |
| C: Liber din nou | `0x00000040` | `0x00000040` | `0x00000000` | PASS |

Acestea sunt rezultate de **simulare Renode/GDB**, nu masuratori ale LED-urilor pe o placa reala.

## 9. Probleme frecvente

| Problema | Ce trebuie verificat |
| --- | --- |
| `No such command or device: sysbus.gpioPort` | Numele complet este **`sysbus.gpioPortE`** pentru portul E. |
| `A syntax error in expression` in GDB | Introduceti comenzile `x/1wx ...` **separat**, nu lipite intr-o singura comanda. |
| `Connection refused` in GDB | Renode ruleaza? Serverul GDB a fost pornit pe portul `3333`? |
| GDB ramane la `Continuing` | Apasati **Ctrl+C** pentru a opri executia si a recupera promptul `(gdb)`. |
| Nu se opreste la `HAL_Delay` | Verificati breakpoint-ul cu `info breakpoints` si ca rulati ELF-ul actualizat. |
| Renode nu gaseste ELF | Verificati calea si faptul ca fisierul a fost copiat dupa ultimul build. |
| `Roboto Mono not available` | Avertisment de font; nu afecteaza testul firmware. |
| `Emulation is already started` | Nu este o eroare: simularea ruleaza deja. |
| Valorile LED nu se schimba | Dupa `OnGPIO`, executati `continue` in GDB si inspectati bitul corect la urmatorul breakpoint. |

## 10. Oprirea testului si buna colaborare

Pentru a termina sesiunea, in GDB:

```gdb
detach
quit
```

Apoi inchideti Renode. Cand codul firmware este modificat, refaceti **Build → copiere ELF → sesiune Renode/GDB noua**.

In echipa:

- Folositi branch-uri de functionalitate si Pull Request; nu faceti push direct pe `main`.
- Nu introduceti in Git fisierele compilate `Debug/`, `.elf` sau `.o`.
- Pentru codul generat de CubeMX, modificati numai zonele `USER CODE BEGIN/END`.
- Notati pentru fiecare test versiunea Renode, commit-ul Git, sistemul de operare si rezultatele PASS/FAIL.
- Nu confundati testele din simulare cu validarea pe hardware fizic.

## 11. Surse oficiale

- [Renode — repository, pachete si instalare](https://github.com/renode/renode)
- [Renode — versiunea 1.17.0](https://github.com/renode/renode/releases/tag/v1.17.0)
- [Renode Documentation](https://renode.readthedocs.io/)
- [STM32CubeIDE](https://www.st.com/en/development-tools/stm32cubeide.html)
