# Matrice frontend → API v1

Sursă inspectată: `frontend/src/api/types.ts`, commit
`5972a3e4beeeaaf52c062f684cc55d5074d20165`, branch
`feature/frontend-dashboard`. Copia din `references/frontend-types.ts`
permite verificarea fără operații Git. Tabelul acoperă fiecare câmp din
acea sursă. Este compatibilitate de contract prin inspecție, nu test E2E.

| Tip / câmpuri frontend | Contract backend / adaptare necesară |
| --- | --- |
| NodeId: G,S1–S5 | Identic. |
| Transport: TCP,USB | Identic; selectarea prin acțiune este doar demo. |
| BarrierId: entry,exit | Identic. |
| SlotState: free,occupied,unknown | Tip derivat UI; occupied=null sau quality!=valid → unknown. |
| CommandStatus: accepted,executing,done,rejected,unknown | Păstrate; adăugate expired și failed. |
| Station.id | Identic. |
| Station.role: string | Restrâns la gateway,slots,entry,exit,environment. |
| Station.online: boolean | Identic; nu înlocuiește quality. |
| Station.updatedAt: number | Milisecunde Unix UTC; acum nullable. |
| Station — câmpuri noi | quality, ageMs nullable, schemaVersion nullable, bootEpoch nullable, sampleSequence nullable. |
| ParkingSlot.id: number | Întreg 1–4. |
| ParkingSlot.nodeId: S1,S2 | Identic; 1/2→S1, 3/4→S2. |
| ParkingSlot.occupied: boolean | boolean sau null; null nu înseamnă liber. |
| ParkingSlot.sessionId: string/null | Identic; asocierea nu se inventează din senzor. |
| ParkingSlot — câmpuri noi | quality, updatedAt nullable, ageMs nullable. |
| Barrier.id,nodeId | Identice; entry→S3, exit→S4. |
| Barrier.state | Stările existente păstrate; adăugat UNKNOWN. |
| Barrier.obstacle,vehiclePresent: boolean | Devin nullable când datele nu sunt valide. |
| Barrier.feedback: estimated | Adăugate measured și unknown. |
| Barrier — câmpuri noi | quality, updatedAt nullable, ageMs nullable. |
| ParkingSession.id,plate | Nume identice; ID restrâns la alfabetul contractului; plate max.20 caractere. |
| ParkingSession.slotId: number | 1–4 sau null. |
| ParkingSession.enteredAt: number | Milisecunde Unix UTC sau null înainte de confirmare. |
| ParkingSession.exitedAt: number/null | Aceleași unități; numai completed poate avea valoare. |
| ParkingSession.status: active,paid,completed | Păstrate; adăugate pending_entry,pending_exit,cancelled. |
| ParkingSession.hourlyRateBani,amountDueBani,paidBani | Întregi nenegativi în bani; amountDue este soldul rămas, nu costul total înainte de plată. |
| ParkingEvent.id,at,message | Identice; at în milisecunde Unix UTC. |
| ParkingEvent.level: info,success,warning | Păstrate; adăugat error. |
| ParkingEvent — câmpuri noi | code; nodeId,sessionId,commandId opționale/nullable pentru corelare. |
| CommandResult.commandId,status,message | Nume păstrate; vezi extinderea CommandStatus. |
| CommandResult — câmpuri noi | createdAt,updatedAt în milisecunde; sessionId și error nullable. |
| ParkingAction enter/plate | Identic structural; plate se normalizează înainte de deduplicare. |
| ParkingAction pay/sessionId; exit/sessionId | Identice structural. |
| ParkingAction set-slot-sensor/slotId/occupied | Identic, numai simulare. |
| ParkingAction set-all-slot-sensors/occupied | Identic, numai simulare. |
| ParkingAction set-node-online/nodeId/online | Identic, numai simulare. |
| ParkingAction set-obstacle/barrierId/active | Identic, numai simulare. |
| ParkingAction set-barrier-presence/barrierId/present | Identic, numai simulare; prezența nu confirmă trecerea. |
| ParkingAction set-transport/transport | Identic, numai simulare. |
| ParkingSnapshot.mode: simulation | Adăugat hardware. |
| ParkingSnapshot.transport,updatedAt,hourlyRateBani | Nume păstrate; unități conform celor de mai sus. |
| ParkingSnapshot.stations,slots,barriers | Toate elementele incluse; tipurile și nullabilitatea se actualizează. |
| ParkingSnapshot.sessions | Numai sesiuni neînchise; istoricul este paginat separat. |
| ParkingSnapshot.events,commands | Cel mult 50 recente în fiecare listă; istoricul evenimentelor este paginat. |
| ParkingSnapshot — câmpuri noi | contractVersion, staleAfterMs, capacity. Disponibilitatea se citește din capacity.available, nu doar din locurile fizic libere. |
| ParkingApi.getSnapshot(): ParkingSnapshot | Rămâne sincron prin cache-ul adaptorului HTTP. La start, cache explicit necunoscut, nu patru locuri libere. |
| ParkingApi.subscribe(listener): unsubscribe | Notificare după actualizarea cache-ului prin polling. |
| ParkingApi.execute(commandId,action): Promise<CommandResult> | POST /commands; rezultatul inițial accepted nu finalizează operația în UI. Se urmărește ID-ul prin polling. |
| ParkingApi.refresh(): void | Declanșează fetch asincron și notificare; adaptorul gestionează erorile. |
| ParkingApi.reset(): void | Fără echivalent API v1; buton dezactivat în integrarea HTTP, nu șterge datele persistente. |

Necesar pentru integrare: actualizarea tipurilor UI, adaptarea afișării
necunoscut/pending, folosirea capacității cu rezervări și înlocuirea mock-ului
prin adaptor HTTP. Nici TypeScript structural compatibility, nici
compatibilitatea binară integrală cu demo-ul nu sunt revendicate.

## Implementarea adaptorului HTTP

Checkout-ul include acum sursa frontend de la revizia de mai sus și
adaptările descrise în tabel. Instanța implicită ParkingApi este HTTP;
mock-ul este păstrat pentru teste. Metodele interfeței rămân aceleași,
iar reset aruncă explicit o eroare și este dezactivat în UI.

Tokenul este introdus la rulare, trimis ca Bearer și ținut doar în memorie.
Răspunsurile sunt validate folosind contracts/openapi.v1.json. Tipurile UI
permit câteva câmpuri opționale pentru mock; acest lucru nu relaxează
validarea JSON a adaptorului HTTP.

Cache-ul inițial este necunoscut, modul poate fi necunoscut până la prima
citire, iar validitatea este evaluată cu ageMs și timp monoton, nu prin
compararea ceasului browserului cu cel al backendului. Cererile de polling
nu se suprapun. execute urmărește accepted/executing până la rezultat sau
deadline. Un rezultat incert păstrează ID-ul și acțiunea în sessionStorage;
UI permite reluarea aceleiași cereri, fără generarea unui ID nou.

Controalele demo sunt dezactivate/ascunse în hardware. Sesiunile pending,
locurile neatribuite și valorile null sunt afișate explicit. Snapshot-ul
conține doar sesiunile neînchise și evenimente/comenzi recente; dashboard-ul
nu pretinde că a încărcat istoricul complet.

Verificarea E2E este în frontend/e2e, cu browser, Vite și FastAPI reale,
pe baze SQLite temporare. Aceasta este distinctă de validarea STM32/serial.
