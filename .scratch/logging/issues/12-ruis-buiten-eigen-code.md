# Wat komt er van buiten de eigen code in de logregels?

Type: grilling
Status: resolved
Blocked by: 06, 07
Assignee: Wouter

## Question

Welke output van externe libraries en van het proces zelf (opstarten, afsluiten, storingen van buitenaf) wordt een logregel, op welk niveau, en wat blijft alleen in het journal of verdwijnt?

Wat de live-logs van oktober laten zien (ticket 03):

- **Telegram onbereikbaar**: tijdens een DNS-storing van bijna een etmaal (1 en 2 november) schreef de `error_handler` 805 WARNING-regels "Network error while calling Telegram", één per poll-poging.
- **Crash bij het opstarten**: op 20 en 22 oktober crashte de bot bij het opstarten door DNS. De traceback staat alleen in het journal, niet in het logbestand.
- **Alleen in het journal**: bij elke start een `PTBUserWarning` (`per_message=False` bij een ConversationHandler in `src/bot.py`) en een systemd-waarschuwing over de unit.
- **Telegram Conflict** bij elke start (9×), en één keer een overgeslagen apscheduler-job.
- "Task was destroyed but it is pending" bij het afsluiten kwam in deze periode niet voor.

Te beslissen:

- Welke loggers van libraries (PTB, httpx, httpcore, aiohttp, apscheduler, asyncio) op welk niveau logregels worden. Nu filtert `NoLibraryChatter` alleen in debug mode, en zet `src/log.py` httpx en apscheduler buiten debug mode op WARNING.
- Of Python-warnings en excepties van vóór of na de logging-setup ook als logregel worden vastgelegd (`logging.captureWarnings`, `sys.excepthook`), of in het journal blijven.
- Hoe een langdurige storing van buitenaf (Telegram, Radarr/Sonarr) er in de logregels uitziet: elke mislukte poging als eigen regel, of begin, einde en aantal.

Uit 06: het niveaubeleid geldt ook voor deze regels. Een Storing is WARNING per poging, iets onverwachts wat geen Fout is ook WARNING, en een Bug is ERROR met de volledige traceback in `exc`. Regels van libraries hebben geen `event`, maar krijgen wel `user_id`, `account` en `tg_name` mee.

Uit 11: bij een persoon laat `/log` geen regels van libraries zien, maar bij een code wel: alles van INFO en hoger in die Interactie. Welke regels van libraries in het hoofdbestand komen, bepaalt dus ook wat `/log <code>` toont.

Uit 07: journald krijgt geen logregels; het journal blijft de plek voor wat buiten de logging valt. Hier dus nog de vraag of een startcrash en Python-warnings alsnog in het logbestand komen. Het hoofdbestand bevat altijd INFO en hoger, en alleen bij `LOG_TYPE=DEBUG` is er een debug-bestand met alles vanaf DEBUG. Te beslissen hier: welke regels van libraries in het hoofdbestand en welke in het debug-bestand komen, en wat de console bij `--verbose` toont (nu filtert `NoLibraryChatter` daar het geruis van libraries uit).

## Answer

Besloten in een grilling met de beheerder op 2026-11-03, in twee rondes. Er zijn geen nieuwe begrippen bijgekomen in `CONTEXT.md`.

### Besluiten

1. **Hoofdbestand: eigen code vanaf INFO, libraries vanaf WARNING.** Eigen code zijn de loggers van de bot zelf. Elke andere logger telt als library, ook een die nu nog niet bekend is. De lijst `NOISY_LOGGERS` vervalt. Uit het hoofdbestand verdwijnen zo de start- en stopregels van PTB ("Application started", "Application is stopping", "Application.stop() complete"), die `bot_started` en `bot_stopped` uit 06 vervangen, en "Flood control exceeded" van de Updater bij het pollen: daar wacht PTB zelf en probeert het opnieuw. Wat blijft, zijn WARNING en hoger van libraries, zoals de overgeslagen run van apscheduler op 2 november.
2. **Een regel van een library houdt zijn eigen niveau en wordt nooit een Fout.** Hij krijgt geen `event` en geen `fault`, en er gaat geen admin-melding over uit. Wat telt, vangt de wrapper uit 09 in de eigen code af. Binnen een Interactie krijgt de regel wel de context mee (`user_id`, `account`, `tg_name`, `interaction_id`; 06, 08), dus `/log <code>` toont hem (11).
3. **Debug-bestand: alles vanaf DEBUG, ook van libraries**, zoals nu. Daar horen ook httpx en httpcore bij, bij elke poll.
4. **Geheimen worden gemaskeerd.** Eén filter op alle handlers vervangt de waarden van `BOT_TOKEN`, `BOT_TOKEN_DEV`, `RADARR_API`, `SONARR_API`, `PLEX_API` en `TRANSMISSION_PWD` door `***`, in `msg` en in elk ander veld, ook in eigen regels. Dezelfde maskering geldt voor alles wat de meldfunctie uit 09 naar Telegram stuurt: admin-meldingen en Foutmeldingen.
5. **Console bij `--verbose`**: eigen code vanaf `LOG_TYPE`, libraries vanaf WARNING, in de weergave uit 06. Bij INFO is dat precies het hoofdbestand. Bij DEBUG komen de eigen DEBUG-regels erbij, zoals `http_call`, zonder het geruis van httpx en PTB.
6. **Python-warnings worden logregels** via `logging.captureWarnings(True)`: WARNING, logger `py.warnings`. De `PTBUserWarning` over `per_message=False` wordt gericht onderdrukt bij het bouwen van de ConversationHandler, met een comment waarom. `per_message=False` klopt: de handler bevat ook CommandHandlers en MessageHandlers, en bij `per_message=True` mogen er alleen CallbackQueryHandlers in. Zo is een warning in het logbestand altijd iets nieuws. De waarschuwing van systemd over de unit blijft in het journal.
7. **Een crash van het proces wordt een logregel.** Na de logging-setup komt een `sys.excepthook` die één regel `bot_crashed` schrijft en de exceptie daarna doorgeeft aan de standaard hook, zodat hij ook in het journal blijft. Niveau en `fault` volgen uit de oorzaak:
   - een `NetworkError` of `TimedOut` van Telegram is een Storing: WARNING, `fault: disruption`, `service: telegram`, met alleen `exc_type` en de tekst. Zo hadden de crashes van 20 en 22 oktober in het logbestand gestaan.
   - al het andere is een Bug: ERROR, met de volledige `exc`.

   Een crash vóór de logging-setup (een variabele die ontbreekt in dot-env, een importfout) blijft alleen in het journal: er is dan nog geen logbestand.
8. **Pollfouten van Telegram.** Elke `NetworkError` bij het pollen is een mislukte poging van een Storing van Telegram: WARNING, `fault: disruption`, `service: telegram`, zonder `interaction_id` (08). Begin en einde krijgen geen eigen regel. Het einde staat al in het log via de Herstelmelding (`admin_message_sent` met `restored: true`, 06). Een `TimedOut` bij het pollen blijft een DEBUG-regel van PTB. Een Conflict bij de start blijft één WARNING zonder `fault` (05, 06).

### Feiten uit de code (voor de implementatie)

- PTB 21.10 (`telegram/ext/_updater.py`, `_network_loop_retry`): bij het pollen vangt PTB `RetryAfter` zelf af (INFO "Flood control exceeded"), net als `TimedOut` (DEBUG, meteen opnieuw). Elke andere `TelegramError` gaat via de `error_callback` van `run_polling` naar `process_error`, dus naar `error_handler`. De wachttijd tussen de pogingen loopt op van 1 tot 30 seconden.
- Regels van libraries op INFO en hoger in de live-logs van oktober: 18 van `telegram.ext.Application` (start en stop), 22× "Flood control exceeded" van `telegram.ext.Updater` en 1 WARNING van `apscheduler.scheduler`. Nu zet `src/log.py` buiten debug mode alleen httpx en apscheduler op WARNING, en filtert `NoLibraryChatter` alleen in debug mode.
- De startcrash: `Application.initialize()` roept `get_me` aan. `run_polling` vangt alleen `KeyboardInterrupt` en `SystemExit` af, dus de `NetworkError` valt uit `main()` naar stderr. systemd herstart de bot na 10 seconden (`Restart=on-failure`, `RestartSec=10` in `files/plex-download-bot.service`).
- Geheimen: httpx logt op INFO elke request met de volledige URL, en PTB zet het bot-token in die URL. transmission-rpc logt op DEBUG bij elke request zijn URL, met `gebruiker:wachtwoord@` erin (`transmission_rpc/client.py:120`), en bij een 401 of 403 ook de request-headers met Basic auth. Radarr en Sonarr krijgen de apikey via `params` (`src/services/arr.py:55`, `:129`), en `http_call` logt de URL zonder die params. plexapi maskeert zijn token zelf (`SecretsFilter`). In de lokale `log/`-map staat geen token, omdat httpx daar buiten debug mode al op WARNING stond.
- De heartbeat-taak (`_heartbeat_loop` in `src/bot.py`, gestart met `asyncio.create_task` in `_post_init`) vangt alleen `OSError` en `asyncio.TimeoutError` af. Bij elke andere exceptie stopt hij, en `_post_stop` slikt die exceptie bij het afsluiten in. Er komt dan geen enkele regel.

### Doorgeschoven

- Of een crash door een Bug een admin-melding krijgt, en hoe die wordt afgeremd als systemd elke 10 seconden opnieuw start. Ook het inkorten van de herhaalde WARNING-regels van een Telegram-storing (805 op 1 en 2 november): [Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?](13-herhaalde-fouten-afremmen.md)
- Waar de maskering in de code zit (filter op de handlers en in de meldfunctie), en dat de heartbeat-taak dezelfde wrapper krijgt als een job: [Welke interface krijgt de logmodule?](14-interface-logmodule.md)
- apscheduler schrijft per run geen regel in het hoofdbestand, dus een run is daar alleen zichtbaar via eigen regels: [Welke logregels schrijft een run van een geplande taak?](15-logregels-geplande-taken.md)
