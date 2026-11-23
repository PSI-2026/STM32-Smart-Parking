# Hartă de registre MODBUS RTU v1.0

Transport inițial: USART1 prin ST-LINK VCP, 115200 baud, 8N1, slave ID 1 implicit. Fiecare registru are 16 biți, octetul superior primul în PDU; CRC16 MODBUS se transmite octet inferior apoi superior. Adresele de mai jos sunt adrese PDU **zero-based**, nu etichete 4xxxx. Sunt implementate funcțiile 03 (citire holding) și 06 (scriere registru). ID 0/broadcast și alte ID sunt ignorate. Cadrele cu CRC invalid sunt ignorate; funcțiile/adresele/valorile invalide primesc excepție MODBUS 01/02/03.

| Adresă | Acces | Semnificație |
|---|---|---|
| 0x0000 | R | ID nod |
| 0x0001 | R | versiune protocol 0x0100 |
| 0x0002 | R | sănătate: 1 normal, 2 defect poartă |
| 0x0003 | R | P01 fizic, bit 0; validitatea se citește din 0x0005 |
| 0x0004 | R | ocupare agregată locală, biții 0–3 |
| 0x0005 | R | biți cunoscuți, 1 = stare validă |
| 0x0006 | R | număr de locuri libere cunoscute; folosiți numai dacă 0x0005 = 0xF |
| 0x0007 | R | stare poartă: 0 închisă, 1 așteaptă trecere, 2 obstrucție, 3 așteaptă eliberare, 4 defect |
| 0x0008 | R | direcție activă: 0 niciuna, 1 intrare, 2 ieșire |
| 0x0009 | R | defect senzor bit 0; ciclu abandonat bit 1 |
| 0x000A | R | comunicație activă, 1 dacă a sosit un cadru valid în ultimele 5 s |
| 0x000B | R | ultima secvență de comandă acceptată |
| 0x000C | R | contor de cicluri finalizate, nu confirmare imediată a comenzii |
| 0x000D | R | ultimul număr de eveniment |
| 0x000E | R | ultimul tip de eveniment |
| 0x000F | R | rezultat comandă: 0 refuz, 1 acceptat, 2 duplicat |
| 0x0010 | R | coadă evenimente suprascrisă de la restart, 1 = da |
| 0x0020–0x002F | R | 8 perechi `(număr, tip)`, de la cel mai recent la cel mai vechi |
| 0x0100 | W | secvență nenulă, crescătoare modulo 65536, pentru comandă sau actualizare simulată |
| 0x0101 | W | 1 cerere intrare, 2 cerere ieșire |
| 0x0102 | W | mască ocupare simulată; P01 hardware nu poate fi setat |
| 0x0103 | W | mască validitate simulată; aplică simultan datele din 0x0102 |
| 0x0104 | W | trecere simulată: 0 liber, 1 obstrucție; respinsă în mod fizic |
| 0x0105 | W | 0xA55A confirmare reset defect, numai în mod simulare și fără obstrucție |

Tipuri eveniment: 1 cerere deschidere, 2 deschisă, 3 trecere, 4 închisă, 5 intrare finalizată, 6 ieșire finalizată, 7 intrare refuzată, 8 defect senzor, 9 defect comunicație, 10 restart, 11 ciclu abandonat. Numerele evenimentelor și contoarele sunt `uint16_t` și se pot relua de la zero după restart; backendul detectează restartul prin evenimentul 10 și identifică separat fiecare sesiune de pornire. Coada are 8 evenimente; citirea se recomandă la cel mult 1 s. Nu există jurnal persistent pe MCU.

Exemplu: masterul scrie 0x0100 = 41, 0x0102 = 0x000A (P02 și P04 ocupate), apoi 0x0103 = 0x000E (P02–P04 cunoscute). Dacă P01 este liber, 0x0004 = 0x000A, 0x0005 = 0x000F și 0x0006 = 2. Actualizarea expiră după 5 s. Pentru intrare, masterul scrie 0x0100 = 42 și 0x0101 = 1, apoi urmărește 0x000C și evenimentele 3/5. Repetarea comenzii cu secvența 42 nu pornește alt ciclu.

Pentru fiecare actualizare simulată, masterul scrie mai întâi o secvență nouă la 0x0100, apoi 0x0102 și 0x0103. Repetarea aceleiași secvențe nu reîmprospătează temporizatorul; secvențele vechi sunt respinse. Perechea de scrieri a simulării nu este atomică la nivel de cadru; registrul 0x0103 este punctul de aplicare. Masterul trebuie să serializeze cererile pentru fiecare nod. Versiunile viitoare pot adăuga registre fără a schimba adresele de mai sus.
