# Smart Parking — frontend

Prima versiune a interfeței Studentului 3: React + TypeScript + Vite, cu un adaptor de backend simulat. Interfața este în română și funcționează fără STM32, Renode, backend sau serviciul Python pornit.

## Pornire

Este necesar Node.js 22.12+ (verificare locală cu Node.js 24.11.1).

```sh
cd frontend
npm ci
npm run dev
```

Deschide `http://127.0.0.1:5173`. Portul este fix: dacă este ocupat, oprește procesul care îl folosește sau modifică `vite.config.ts`.

```sh
npm test
npm run build
npm run preview
```

Pe Windows, dacă PowerShell alege un `npm.ps1` nefuncțional, folosește `npm.cmd ci` și `npm.cmd run dev`. Nu este necesară modificarea politicii PowerShell. În cazul unei instalări Node incomplete, repară instalarea Node/npm înainte de utilizare.

## Ce poți demonstra

1. La pornire sunt două vehicule fictive: B 101 DEM în P01 (neplătit) și CJ 24 DEM în P03 (plătit în simulator).
2. Alege **Intrare vehicul**, introdu `B 123 DEM` și confirmă. Simulatorul alocă primul loc liber și actualizează sesiunea, ocuparea și bariera S3. Bariera se închide automat după animația simulată.
3. Alege **Plată demo** pentru o sesiune neplătită. Plata este înregistrată o singură dată, inclusiv dacă operația se repetă. Plata singură nu eliberează locul și nu deschide ieșirea.
4. Alege **Autorizează ieșirea** pentru o sesiune plătită. Simulatorul deschide S4, încheie sesiunea și simulează eliberarea senzorului. În **Toate sesiunile** vezi și sesiunile încheiate.
5. În **Diagnostic**, deconectează S1. P01/P02 devin necunoscute; nu sunt numărate ca libere sau ocupate. Intrările și ieșirile noi sunt suspendate până la recuperarea datelor.
6. Deconectează G: toate locurile și barierele devin necunoscute, iar operațiile de parcare sunt blocate. Reconectează G pentru reluarea observațiilor simulate.
7. Activează un obstacol la ieșire. S4 intră în interblocare, iar ieșirea este blocată chiar dacă sesiunea este plătită.
8. În **Jurnal**, exportă evenimentele și rezultatele comenzilor în JSON. Exportul este marcat `simulation`.
9. În **Parcare**, apasă **Simulare senzori**, lângă schemă. Panoul lateral permite comutarea P01–P04: **ON** înseamnă vehicul detectat, **OFF** înseamnă senzor liber. **Toate libere** / **Toate ocupate** modifică toate cele patru intrări. Fiecare schimbare este jurnalizată. Închide panoul cu X sau Escape; focalizarea revine la butonul de deschidere. Aceleași controale sunt disponibile și în **Diagnostic**.

Pagina **Parcare** afișează un singur rezumat al locurilor libere, ocupate și necunoscute. Numărul sesiunilor active, încasările simulate și tariful sunt disponibile în **Sesiuni**. Antetul afișează o singură etichetă **Mod simulare**; versiunea demo și bannerul repetitiv au fost eliminate.

Controalele senzorilor nu creează sesiuni, nu înregistrează plăți și nu închid sesiuni. Dacă eliberezi senzorul unui loc cu sesiune activă, asocierea rămâne până la ieșirea autorizată. O intrare nouă primește un loc cu senzor liber și fără sesiune asociată. Selectarea unui loc cu sesiune deschide sesiunea respectivă, chiar dacă senzorul a fost eliberat manual; un vehicul detectat fără sesiune este indicat explicit.

Poți modifica senzorii și cu stația sau gateway-ul deconectat. Poziția ON/OFF este păstrată în simulator; starea observată rămâne **Necunoscut** până la reconectare. Informațiile de conectivitate și vechime nu sunt resetate prin acționarea senzorilor.

**Resetează demo** cere confirmare și reface datele inițiale. Starea este păstrată numai în memoria paginii; reîncărcarea o resetează. Nu există tranzacții reale, persistență sau conexiuni de transport reale. Alegerea TCP/USB schimbă numai profilul simulatorului.

## Organizare și integrare cu Studentul 2

```text
src/
  api/
    types.ts             contractul intern al UI
    selectors.ts         disponibilitate, vechime și ocupare validă
    mockParkingApi.ts    serverul simulat, fără dependență de React
    index.ts             adaptorul ales
  components/            formular acces, simboluri, panou de simulare senzori
  hooks/useParking.ts    abonare la snapshot și heartbeat demo
  lib/format.ts          afișarea sumelor și duratelor
  App.tsx                paginile dashboard-ului
  styles.css             layout adaptabil desktop/mobil
  theme.css              paleta albastră și culorile interfeței
```

UI consumă interfața `ParkingApi`, nu registre MODBUS sau GPIO. Adaptorul expune snapshot, abonare, comenzi cu ID, actualizare și reset demo. Datele includ nodul sursă, conectivitatea, momentul ultimei observații și starea comenzilor. Observațiile mai vechi de 2000 ms sunt tratate ca necunoscute. Pragul este propus în documentația proiectului și trebuie reconfirmat la integrare.

Pentru adaptorul HTTP real trebuie convenite împreună: schema și versiunea API, URL-ul backend-ului, datele temporale/calitatea, citire periodică sau push, codurile erorilor și traseul comenzilor `accepted → executing → done/rejected/unknown`. Niciun endpoint al backend-ului Node nu este presupus implementat în această versiune. `GET /snapshot` din arhitectură descrie interfața propusă Node–Python; nu este revendicat aici ca endpoint Node–React existent.

Taxa afișată vine din snapshot. Calculul se află exclusiv în adaptorul simulat: 5 RON/oră începută, cost zero la durată zero, tarif salvat per sesiune, sumă înghețată la plata simulată. Backend-ul real va avea autoritatea asupra tarifului, sesiunilor și autorizațiilor de ieșire. Adaptorul real nu trebuie să recalculeze autoritar aceste valori în browser.

Poziția barierei este etichetată **estimată**. În demo, ieșirea și eliberarea senzorului sunt combinate pentru a demonstra fluxul; pe hardware, execuția comenzii, senzorul și închiderea sesiunii trebuie corelate ca evenimente distincte. Nu există feedback mecanic sau autorizații reale cu TTL în acest frontend.

## Verificări și limite

Testele Vitest verifică logica de simulare: date necunoscute/vechi, pierderea gateway-ului, limitele tarifului, plata idempotentă, ieșirea fără plată, ID-uri duplicate, capacitatea maximă, interblocări, reset în timpul execuției și injecția manuală a senzorilor independent de sesiuni. Aceste teste sunt probe software, nu dovezi pentru protocoale, OPC UA sau hardware.

Verificare locală la 9 noiembrie 2026:

- `npm.cmd run build`: compilarea TypeScript și build-ul Vite au reușit.
- `npm.cmd test`: 29 de teste au trecut, inclusiv acționarea manuală, comenzile pentru toți senzorii, injecția offline și protejarea sesiunilor asociate.
- Browser: intrare → plată simulată → ieșire; căutare fără rezultate; S1 deconectat → două locuri necunoscute; G deconectat → patru locuri necunoscute; obstacol → ieșire blocată; reset confirmat; export JSON descărcat.
- Panoul de senzori: comutare individuală, toate locurile ocupate/libere, sesiuni păstrate, vehicul fără sesiune explicat, modificare cu S1 deconectat și observație recuperată la reconectare. Comutarea din tastatură și afișarea la 390 px au fost verificate.
- Interfața simplificată: o singură etichetă „Mod simulare”, rezumat compact inclusiv pentru date necunoscute, încasări în Sesiuni, senzori deschiși din Parcare. Panoul lateral a fost verificat cu Escape și X, revenirea focalizării la buton și închidere vizibilă după derulare pe mobil.
- Afișare verificată la lățimi de 390 și 1440 px; pe telefon, tabelul are derulare orizontală în interiorul panoului. Pagina nu depășește lățimea ecranului în scenariile verificate.
- Consola browserului nu a raportat erori sau avertismente în fluxurile executate.

OPC UA, codec-ul ASCII, jurnalizarea embedded și testele industriale din rolul Studentului 3 rămân lucrări separate. Această etapă acoperă frontend-ul și contractul său intern de integrare.
