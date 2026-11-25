# Alocarea pinilor și cablarea

| Semnal | Pin | Stare | Motiv / conexiune |
|---|---|---|---|
| P01 laborator | PE2 / PARK1_SENSOR | intrare digitală activă pe LOW | Tracking OUT → PE2, VCC → 3V3, GND comun |
| Indicator P01 | PG13 / LD3 | configurat | LED existent; aprins = ocupat |
| Indicator poartă | PG14 / LD4 | configurat | LED existent; aprins = deschis/defect |
| MODBUS local | PA9 TX, PA10 RX / USART1 | configurat, VCP nevalidat fizic | ST-LINK/V2-B, 115200 8N1 |
| SDRAM D4, D5, D8, D9 | PE7, PE8, PE11, PE12 | corectat la FMC AF12 | nu sunt senzori de poartă |
| SDRAM restul datelor/comenzilor | PE9/10/13–15, PD0/1/8–10/14/15, PF0–5/11–15, PG0/1/4/5/8/15, PB5/6, PC0 | păstrat | funcțiile FMC existente |
| LCD și periferice de placă | LTDC, SPI5, I2C3, USB, SWD | păstrat | fără realocare |
| P02–P04 | niciun pin | backend | simulare explicită, fără senzori ficționali |
| Senzor trecere poartă | nealocat | propus | selectare după verificarea schemei și a conectorului |
| Actuator poartă | nealocat | blocat | driver, alimentare separată, limite și interblocare obligatorii |
| Buzzer activ/pasiv | nealocat | dezactivat | verificați tensiune, curent și necesitatea tranzistorului |

Configurația CubeMX încă păstrează etichetele GPIO istorice pentru P01–P04 și LEDurile externe în alte locuri, însă noua buclă nu citește P02–P04 și nu le comandă LEDurile. Aceste definiții sunt moștenite; trebuie eliminate din proiectul CubeMX după validarea reviziei exacte a plăcii și a oricărei cablări deja montate. Nu conectați senzori pe PE7/8/11/12: sunt linii de date SDRAM.

Pentru testul P01, apropiați o suprafață reflectorizantă de senzor și verificați activarea LD3 și a bitului 0 din registrul MODBUS `0x0003`. Îndepărtați suprafața pentru a verifica revenirea la liber. Pentru RS-485 viitor, folosiți transceiver de 3,3 V compatibil, terminare și polarizare dimensionate pentru magistrală și control DE/RE pe un pin disponibil verificat. Niciun GPIO nu trebuie să alimenteze direct un motor, servo sau buzzer cu sarcină necunoscută.

Surse: [schema oficială MB1075](https://www.st.com/resource/en/schematic_pack/mb1075-f429i-b01_schematic.pdf) și [pagina oficială STM32F429I-DISCOVERY](https://www.st.com/en/evaluation-tools/32f429idiscovery.html). Revizia fizică trebuie comparată cu schema corespunzătoare înainte de cablare.
