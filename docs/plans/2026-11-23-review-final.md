# Revizie finală firmware hibrid

## Corectitudinea și siguranța

- Cererile simultane folosesc o singură mașină de stare; cea conflictuală este refuzată. Secvențele acceptate și refuzate sunt memorate pentru a preveni execuția unui retry vechi.
- Capacitatea necunoscută sau expirată refuză intrarea. Ieșirea nu depinde de capacitate. Pierderea comunicației invalidează imediat sursele backend.
- Confirmarea trecerii precedă 500 ms de semnal liber continuu. Reapariția obstacolului anulează intervalul. Calculul intervalelor este sigur la wraparound `uint32_t`.
- Expirarea ciclului de 30 s produce defect distinct, fără comandă mecanică de închidere. În mod fizic, injecția simulată produce defect. Modul fizic nu este conectat în runtime.
- Lungimile cadrelor și răspunsurilor MODBUS sunt limitate la 256 B; CRC, funcția, adresa, valoarea și ID sunt validate. Scrierile nu ating direct GPIO. Evenimentele au număr, coadă fixă de opt și indicator de suprascriere.
- Bufferul UART este copiat cu întreruperile dezactivate; procesarea și răspunsul rulează în bucla principală. TIM3/TIM4 sunt păstrate, dar nu sunt necesare noului flux.

## Probleme confirmate și rezolvate

1. PE7/8/11/12 erau intrări de poartă peste date SDRAM; `.ioc`, `main.h` și inițializarea GPIO le-au revenit la FMC AF12.
2. Comenzi duplicate refuzate puteau fi executate ulterior; rezultatul ultimei secvențe este acum stabil.
3. O actualizare simulată repetată putea extinde valabilitatea; actualizările cer secvență nouă și expiră după 5 s.
4. Timeoutul de trecere era raportat ca defect de senzor; are acum bit și eveniment distinct.

## Limite deschise

- Nu există senzor de trecere, actuator, buzzer sau al doilea STM32 validat fizic. Modul fizic rămâne indisponibil în `main.c`.
- Butonul USER folosit pentru P01 nu are filtrare de contact; integrarea unui senzor real cere polaritate și debounce validate.
- Regenerarea proiectului CubeIDE este necesară pentru ca listele de surse Debug/Release să includă automat modulele noi. Makefileurile generate cu GCC 14.3 folosesc un flag respins de GCC 15.3 local.
- Backendul FastAPI nu este încă integrat la nivel de master MODBUS în această ramură. Contractul este documentat; nu s-au modificat backendul sau frontendul.
- Testul Renode nu are un scenariu `.resc` în depozit; nu s-a raportat validare Renode.

`make -C firmware/tests check` trece. Compilarea și legarea Debug/Release pentru STM32 trec cu obiectele noi incluse explicit. Validarea pe placă rămâne obligatorie înainte de activarea fizică.
