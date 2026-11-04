# 12 Crash en heartbeat

Status: dicht
Blocked by: 11
Niet tegelijk met: –

## Wat

Een crash en een kapotte heartbeat laten een regel en zo nodig een melding achter.

- **`report_crash(exc)`** in `src/faults.py`, aangeroepen door een `sys.excepthook` die wordt geïnstalleerd zodra de meldfunctie bestaat:
  - schrijft `bot_crashed`. Een `NetworkError` of `TimedOut` van Telegram is een Storing (WARNING, alleen `exc_type` en de tekst). Al het andere is een Bug (ERROR, met `exc` en een eigen Code).
  - draait `report()` in een nieuwe event loop (`asyncio.run`), met een nieuwe `Bot` en een timeout van 5 seconden. Een Bug wordt afgeremd per handtekening, dus een crashlus geeft één melding per 24 uur. Bij een Storing van Telegram telt hij alleen de poging.
  - geeft daarna de exceptie door aan de standaard hook, zodat hij ook in het journal staat.
- **`guard_task(coro_fn)`** voor de heartbeat: een exceptie is een Bug buiten een Interactie, met een eigen Code. Daarna start de heartbeat na 60 seconden opnieuw.
- **Mislukte heartbeats** (`OSError`, `asyncio.TimeoutError`) zijn pogingen van een Storing van `fallback`, met korte regels na de eerste. Een geslaagde heartbeat roept `faults.ok("fallback")` aan. De oude logica (de 1e en elke 30e poging, en "recovered after N failures") verdwijnt.
- **`HEARTBEAT_TARGET_HOST` niet ingesteld** blijft een logregel. Een verkeerde `HEARTBEAT_TARGET_PORT` is een Inrichtingsfout.
- **`_post_stop`** slikt een exceptie van de heartbeat niet meer stil in.

## Spec

- [4. Regels van buiten de eigen code](../spec.md#4-regels-van-buiten-de-eigen-code), punt 3 en 5
- [Bugs](../spec.md#bugs), punt 11
- [De meldfunctie](../spec.md#de-meldfunctie), punt 10
- [De Interactie en de wrappers](../spec.md#de-interactie-en-de-wrappers), punt 19

## Klaar als

- [x] Tests:
  - `report_crash` voor een Bug en voor een Storing van Telegram
  - de heartbeat start na 60 seconden opnieuw (met een nep-`sleep`)
- [ ] Op dev: een geforceerde crash na de start geeft `bot_crashed` in het logbestand, één admin-melding, en de traceback in het journal.

## Aanwijzingen

- `run_polling` sluit bij het stoppen zijn event loop (`close_loop=True`). Daarom heeft `report_crash` een nieuwe loop nodig.
- systemd herstart de bot na 10 seconden (`files/plex-download-bot.service`).
- De heartbeat staat in `_heartbeat_loop` (`src/bot.py:424`), gestart met `asyncio.create_task` op r. 317. Live gaat hij elke 5 seconden.

## Besluiten bij de uitvoering

Genomen op 2026-11-04. De eerste twee zijn na de review voorgelegd en besloten op 2026-11-04, en bijgewerkt in de spec ([4. Regels van buiten de eigen code](../spec.md#4-regels-van-buiten-de-eigen-code), punt 3, [De meldfunctie](../spec.md#de-meldfunctie), punt 10, en [De Interactie en de wrappers](../spec.md#de-interactie-en-de-wrappers), punt 19):

- **De timeout van 5 seconden** geldt per stap van een request van de nieuwe `Bot`: wachten op een verbinding, verbinden, schrijven en lezen. Een time-out is zo een gewone poging van een Storing van Telegram, en de melding wordt teruggenomen zoals elke melding die niet aankomt, dus de volgende crash stuurt hem alsnog. Eén keer versturen kan zo zo'n 15 seconden duren. Een harde grens om het hele rapport (`asyncio.wait_for`) zou midden in het versturen kunnen afbreken: dan telt de Bug als gemeld, terwijl de melding niet aankwam.
- **De indeling van een crash en van een exceptie in de heartbeat** is die van de wrappers (`as_fault` in `src/faults.py`, ook gebruikt door `guard` en `guard_job`): een Fault houdt zijn soort, `NetworkError`, `TimedOut` en `RetryAfter` van Telegram zijn een Storing, en de rest is een Bug. Een crash door een Bug heet "The bot crashed", een exceptie in de heartbeat "Unexpected exception".
- **De nieuwe `Bot`**: `TelegramOut.on_new_bot` opent de verzendfunctie op een nieuwe `Bot`, met één `TelegramRequest` voor beide (hij pollt nooit), en sluit die daarna. De meldfunctie krijgt hem mee bij het aanmaken (`new_send`), zodat `report_crash(exc)` de interface van de spec houdt. `report_crash` maakt ook een nieuwe lock, omdat de oude aan de gesloten event loop kan vastzitten.
- **De excepthook** geeft alleen een `Exception` aan `report_crash`: een `KeyboardInterrupt` is geen crash. Mislukt het melden zelf, dan komt er een ERROR-regel "could not report the crash" en gaat de crash toch naar de standaard hook.
- **De heartbeat**: een mislukte heartbeat is een poging van een Storing van `fallback`, "The fallback host is not responding", met de exceptie als oorzaak. Een `HEARTBEAT_TARGET_PORT` die geen getal van 1 tot en met 65535 is, is een Inrichtingsfout (`fallback`, `setting`, `HEARTBEAT_TARGET_PORT`) met `Continued: the bot runs without a heartbeat`. Een goede poort roept `faults.fixed` aan. Zonder `HEARTBEAT_TARGET_HOST` staat de heartbeat bewust uit, dus dat is een INFO-regel "heartbeat off: HEARTBEAT_TARGET_HOST is not set" (was een warning).
- **`_post_stop`**: `guard_task` meldt een Fout in de heartbeat zelf. Een exceptie die de taak toch beëindigt, komt dus uit `guard_task`, bijvoorbeeld van een meldfunctie die faalt. Die wordt een Bug "The heartbeat stopped" met `Continued: went on stopping the bot`, en wordt niet doorgegooid: dan zou PTB `shutdown()` overslaan.
- `_send_goodbye_to_fallback` is niet veranderd. Hij gebruikt nog `Log`, voor 15.

Nog te doen: de controle op dev met een geforceerde crash (Klaar als, punt 2). Dat kan alleen de Beheerder.
