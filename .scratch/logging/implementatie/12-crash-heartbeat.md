# 12 Crash en heartbeat

Status: open
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

- [ ] Tests:
  - `report_crash` voor een Bug en voor een Storing van Telegram
  - de heartbeat start na 60 seconden opnieuw (met een nep-`sleep`)
- [ ] Op dev: een geforceerde crash na de start geeft `bot_crashed` in het logbestand, één admin-melding, en de traceback in het journal.

## Aanwijzingen

- `run_polling` sluit bij het stoppen zijn event loop (`close_loop=True`). Daarom heeft `report_crash` een nieuwe loop nodig.
- systemd herstart de bot na 10 seconden (`files/plex-download-bot.service`).
- De heartbeat staat in `_heartbeat_loop` (`src/bot.py:424`), gestart met `asyncio.create_task` op r. 317. Live gaat hij elke 5 seconden.
