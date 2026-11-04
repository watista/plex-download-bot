# 15 Log opruimen

Status: dicht
Blocked by: 03, 04, 05, 07, 09, 10, 11, 12, 13
Niet tegelijk met: –

## Wat

De dunne laag uit 01 verdwijnt, en daarmee de klasse `Log`.

- De klasse `Log` met `logger`, `debug_call`, `send_telegram_message`, `clean_message`, `truncate` en `escape_markdown` verdwijnt. `escape_markdown` gaat mee naar de plek die hem nog nodig heeft (`src/bot.py:376`).
- De parameter `logger` verdwijnt uit de constructors. Waar de meldfunctie nodig is, komt `faults` ervoor in de plaats. Tests geven een nep-meldfunctie mee, zoals `tests/test_movie_states.py` nu een `MagicMock`.
- De README en `dot-env.template` worden nagelopen op resten.

## Spec

- [Wat verdwijnt](../spec.md#wat-verdwijnt)
- [Logregels schrijven](../spec.md#logregels-schrijven), punt 2

## Klaar als

- [x] `grep -rn "self.log\.\|debug_call\|last_error\|NoLibraryChatter\|LOOKUP_ALERT_THRESHOLD" src main.py dot-env.template README.md` geeft niets.
- [ ] Alle tests zijn groen, en de bot start op dev in normal mode en in maintenance mode.
  - De 374 tests zijn groen. `BotBuildTest` (`tests/test_interaction.py`) bouwt de hele bot in beide modes, tot aan het pollen.
  - De start op dev zelf is nog niet gedaan.

## Besluiten bij de uitvoering

Genomen op 2026-11-04 en 2026-11-05. Het afscheid aan de fallback-host is na de review voorgelegd en besloten, en staat in de spec ([Per geval](../spec.md#per-geval)).

- **`escape_markdown`** zat al in `send_admin_message` (`src/telegram_out.py`), sinds 03. Op `src/bot.py:376` was niets meer over.
- **De constructors**: geen klasse kreeg `faults` erbij. De klassen die de meldfunctie nodig hebben (`Movie`, `Serie`, `Schedule`, `Subscribe`), hadden hem al. Bij de rest verdwijnt de parameter gewoon, ook bij `Bot` en `Functions`.
- **De antwoorden van `Functions`** (`send_message`, `send_gif`, `send_image`) schreven hun hele tekst als DEBUG-regel. Die regels verdwijnen, en worden geen `log.debug(text)`:
  - de tekst is Nederlands en staat vol MarkdownV2 en HTML, tegen "Alles Engels" en een `msg` in platte tekst;
  - hij kan teruggeven wat iemand typte;
  - de spec houdt de tekst van berichten overal anders uit het debug-bestand: de regels van PTB worden weggefilterd, en een `http_call` van Telegram heeft geen `request` en `response`.

  Een test in `MessageTextTest` houdt dat vast.
- **Het afscheid (`BYE`) aan de fallback-host bij het stoppen**:
  - Mislukt het (`OSError` of een time-out), dan is dat een poging van een Storing van `fallback`, "The fallback host is not responding", met `Continued: went on stopping the bot`, net als een mislukte heartbeat. Voorheen was het een WARNING zonder `fault`.
  - Komt het aan, dan volgt een INFO-regel "goodbye sent to host:port" en `faults.ok("fallback")`.
  - Elke andere exceptie is een Bug, "The goodbye to the fallback host failed". Die wordt gemeld en niet doorgegooid, zodat de rest van het stoppen doorgaat.
- **`dot-env.template`**: het commentaar bij `LOG_MAX_BODY` beschreef nog `debug_call` ("every Radarr/Sonarr call … in the log file"). Nu staat er dat elke request naar Radarr, Sonarr, Plex of Transmission een `http_call` in het debug-bestand krijgt. In de README stond niets meer van de oude `Log`.

Nog te doen: de bot op dev starten in normal mode en in maintenance mode (Klaar als, punt 2). Dat kan alleen de Beheerder.
