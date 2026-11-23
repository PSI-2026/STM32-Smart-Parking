# Scenarii critice și dovezi

Scenariile de mai jos sunt verificări software. Testele hardware reale sunt
predate separat lui Mert. Comenzile se rulează conform [HANDOFF.md](HANDOFF.md).

| Scenariu | Criteriu | Dovadă automată |
| --- | --- | --- |
| Autentificare și rol | Fără token: 401; viewer nu scrie: 403; ID-ul nu este rezervat. | test_security.py; verify_handoff.py: authentication-before-admission. |
| Intrare/plată/ieșire | Sesiunea și ocuparea se schimbă numai după dovadă; la ieșire senzorul revine liber. | test_simulator.py: test_timed_entry_payment_exit_and_persistent_physical_state; verify_handoff.py: entry-payment-exit-and-replay; frontend/e2e/parking.spec.ts. |
| Parcare plină | Ultima capacitate nu se dublează; a cincea intrare este refuzată. | test_simulator.py: test_full_parking_rejects_fifth_vehicle_and_replay_never_adds_a_car; verify_handoff.py: full-parking. |
| Intrări simultane | Verificarea capacității și claim-ul sunt atomice, fără suprarezervare. | test_parking.py: test_concurrent_admission_processing_and_payment verifică exact ultima capacitate; verify_handoff.py: simultaneous-entries verifică și accesul HTTP concurent. |
| Plată repetată | Replay și o altă cerere de plată nu taxează din nou sesiunea. | test_parking.py: test_duplicate_plate_and_parallel_payments; verify_handoff.py: entry-payment-exit-and-replay. |
| Ieșire neplătită | PAYMENT_REQUIRED persistent; plata ulterioară nu transformă replay-ul refuzului în autorizare. | test_parking.py: test_unpaid_exit_cannot_be_revived_by_replay_after_payment; verify_handoff.py: entry-payment-exit-and-replay. |
| Timeout după trimitere | Fără dovadă nu se consumă claim-ul și nu se emite automat un nou FC16. | test_modbus.py: test_lost_write_response_reconciles_without_resend (TCP și ADU RTU); verify_handoff.py: client-timeout-and-restart-without-resend; E2E răspuns POST pierdut. |
| Nod sau gateway indisponibil | Date null/UNKNOWN, capacitate necunoscută, fără locuri libere inventate. | test_modbus_history.py; test_simulator.py: test_node_loss_and_gateway_loss_publish_unknown_until_reconnected; verify_handoff.py: unavailable-node-and-gateway. |
| Restart | Păstrează plata, sesiunea și idempotenta; sent incert nu este retrimis; prepared netrimis se recuperează separat. | test_parking.py, test_simulator.py; verify_handoff.py: restart-preserves-session-payment-and-replay și client-timeout-and-restart-without-resend. |
| Prospețime/boot/wrap | Cache-ul nu redevine valid dintr-un boot depășit sau candidat expirat. | test_modbus_history.py, inclusiv invalidarea imediată a cache-ului și persistarea primului cadru din boot nou. |
| Contract HTTP și erori | Aliasuri stricte, erori uniforme, 202 nou/200 replay/409 conflict; UTF-8 invalid 422 și 405 păstrează Allow. | test_api.py, test_contracts.py, export_contracts.py --check. |

Suita unitară are cazuri mai precise decât demonstrația HTTP. De exemplu,
două intrări HTTP pot fi serializate de server și pot reuși succesiv;
demonstrația nu cere artificial refuzul uneia dacă există capacitate.
Testul dedicat ultimei capacități verifică exact un singur claim și sesiune.

Client timeout din script înseamnă că aplicația nu primește dovada în
fereastra observată. Testul MODBUS separat pierde răspunsul după FC16.
Niciunul nu este prezentat drept probă de timeout fizic pe STM32.

Raportul verificării curate și versiunile folosite sunt în
[validation/step8.json](validation/step8.json). Rularea CI a noului PR este
o dovadă separată, verificabilă pe GitHub după publicare.
