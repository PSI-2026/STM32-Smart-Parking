# Validare hardware necesară

Acest firmware **nu este pregătit pentru acționarea fizică a unei bariere**. Rezultatele existente sunt teste pe host și compilare pentru MCU, nu probe pe placă.

## Checklist pe STM32F429I-DISCOVERY

1. Citiți revizia inscripționată pe placă și comparați schema corespunzătoare cu [schema oficială MB1075](https://www.st.com/resource/en/schematic_pack/mb1075-f429i-b01_schematic.pdf). Confirmați legăturile ST-LINK VCP PA9/PA10 și eventualele punți de lipire.
2. Alimentați numai placa, fără actuator. Confirmați că PE7/8/11/12 sunt FMC, LCD și SDRAM rămân funcționale, iar SWD nu este afectat.
3. Apăsați B1 și confirmați schimbarea P01 și LD3. Verificați polaritatea reală și stabilitatea contactului; adăugați debounce dacă este necesar.
4. Deschideți VCP la 115200 8N1. Verificați ID, CRC, citiri, excepții, timeout și recepția cadrelor consecutive la distanța minimă MODBUS.
5. Simulați P02–P04, confirmați expirarea la 5 s și refuzul intrării când starea este necunoscută.
6. Cu poarta încă doar logică, confirmați două direcții, dubluri, trecere, obstacol reapărut, fault și reset. Verificați jurnalul FastAPI prin numerele de eveniment.
7. Înainte de mod fizic: alegeți un senzor de trecere accesibil electric, circuit de oprire de urgență, contacte limită, driver de actuator, alimentare separată, protecții și stare mecanică sigură la pierderea alimentării. Măsurați semnalele și verificați timpii cu osciloscop sau analizor logic.
8. Pentru buzzer, identificați tipul activ/pasiv, tensiunea, curentul și driverul; nu conectați direct o sarcină necunoscută la GPIO.
9. Pentru al doilea STM32, testați ID 2 separat și apoi pierderea unuia dintre noduri. Nu calculați locurile offline drept libere.

Niciunul dintre pașii de mai sus nu a fost raportat ca realizat pe placă. Activarea actuatorului și a buzzerului rămâne blocată până la verificarea electrică și mecanică.
