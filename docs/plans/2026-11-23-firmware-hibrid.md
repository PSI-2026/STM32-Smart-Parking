# Audit și plan de implementare firmware hibrid

## Audit inițial

- `origin/main` la `792d8bc`; ramura de teste adaugă un commit (`d81447f`). Ramura de lucru pornește din aceasta pentru a păstra suita nativă. Patru fișiere CubeIDE neversionate rămân neatinse.
- Există detectoare GPIO, patru locuri fizice presupuse și două bariere logice. Testele existente verifică parcarea și întârzierea de 500 ms a barierei. USART1 este configurat pe PA9/PA10 către ST-LINK.
- Lipsesc sursele simulate, o singură poartă cu arbitrare, confirmarea evenimentelor, buzzerul și un slave MODBUS. Backendul nu are încă un contract MODBUS integrat în ramura curentă.
- PE7/8/11/12 sunt configurate ca intrări, în vecinătatea magistralei SDRAM pe PE9/10/13–15. Fără schemă și cablare verificate, nu vor controla siguranța porții.

## Decizii de arhitectură și analiză inginerească

1. P01 are sursă GPIO; P02–P04 au sursă backend. Inițial sunt necunoscute. Datele simulate expiră, iar intrarea se refuză dacă oricare loc este necunoscut.
2. O singură mașină de stare arbitrează direcția. Comenzile concurente sunt refuzate; retransmisia aceluiași număr de secvență este idempotentă. Ieșirea nu depinde de capacitate.
3. În mod `SIMULATION`, trecerea poate fi injectată prin MODBUS. În `HARDWARE`, numai senzorul fizic valid poate confirma trecerea. Niciun actuator fizic nu este activ implicit.
4. Poarta așteaptă trecerea maximum 30 s, apoi intră în defect cu poarta logic deschisă; nu comandă o închidere forțată. Obstrucția reîncepe intervalul de eliberare de 500 ms. Aritmetica timpului folosește scădere `uint32_t`.
5. La pierderea comunicației, datele backend devin necunoscute și intrările noi sunt refuzate. Un ciclu activ își păstrează siguranța locală. Resetul defectului cere comandă explicită și semnal liber.
6. Evenimentele sunt compactate într-un tip și un contor monoton. Backendul citește secvența și înregistrează schimbările; istoria completă rămâne în FastAPI.

## Ordine de implementare

1. Nucleu portabil: parcare hibridă, poartă, buzzer, evenimente.
2. Registre și cadru MODBUS cu validare strictă, apoi transport USART1 cu recepție fără blocare.
3. Integrare în `main.c`, dezactivarea intrărilor fictive și a pinilor de poartă nevalidați.
4. Teste native, sanitizatoare, analiză statică, compilare STM32, documentație și revizie finală.

## Riscuri și limite

Senzorul de prezență, senzorul de trecere, actuatorul și buzzerul nu au conexiuni electrice confirmate. Modul fizic rămâne dezactivat. USART1 este rutat în configurație către ST-LINK, dar funcționarea VCP trebuie verificată pe placa reală. Orice integrare mecanică cere validarea schemei, tensiunilor, curentului, poziției fail-safe și procedurii de oprire de urgență.
