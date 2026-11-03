# Welke interface krijgt de logmodule?

Type: grilling
Status: resolved
Blocked by: 10, 12, 13
Assignee: Wouter

## Question

Welke interface vervangt `Log.logger()` en `Log.debug_call()` (`src/log.py`) voor logregels, gebruikersacties, Fouten en admin-meldingen, en waar liggen de seams?

Skills: naast grilling en domain-modeling ook codebase-design.

Wat al vaststaat:

- Uit 05: de soort Fout wordt op één plek bepaald uit het antwoord van de dienst. Een admin-melding die Telegram weigert, moet alsnog aankomen (opnieuw als platte tekst).
- Uit 06: `logger` en `src` komen van de aanroeper, niet van de wrapper. `debug_call` wordt een `http_call`-regel, en een traceback gaat in het veld `exc` in plaats van in de tekst.
- Uit 07: een eigen handler kiest per regel het dagbestand, en `LOG_TYPE` kent alleen nog `INFO` en `DEBUG`.
- Uit 08: de `BaseUpdateProcessor` zet `interaction_id` per update, en een job-wrapper zet `interaction_id` en `job` per run.
- Uit 09: er is één klasse `Fout` met `soort`, dienst, reden en de oorspronkelijke exceptie, plus een optionele zin voor de Foutmelding. Eén meldfunctie wordt gebruikt door de wrapper, door plekken die melden en doorwerken, en door `error_handler`. De wrapper komt bij het registreren in `src/bot.py` om elke callback, en geeft in een Gesprek `END` terug. Elke requestfunctie van een dienst zet een antwoord om via één gedeelde HTTP-regel. De Foutmelding belooft alleen een admin-melding die echt uitging, dus de meldfunctie moet de wrapper laten weten of hij er een verstuurde.
- Uit 10: de admin-melding is HTML en Engels, en altijd één bericht van hooguit 4096 tekens. Naast de velden van de `Fout` uit 09 heeft hij nodig:
  - het media-item: titel, jaar, tmdb- of tvdb-ID, plus wat nodig is voor de link naar Sonarr of Radarr
  - de velden waarop de beslissing viel
  - bij melden en doorwerken een zin voor `Continued:`
  - of de Gebruiker een Foutmelding kreeg
  - de eigen frames uit de traceback

  Weigert Telegram de opmaak, dan stuurt de meldfunctie de melding één keer opnieuw als platte tekst, met een waarschuwingsregel, en logt hij de weigering als Bug zonder eigen melding. Tijdens een Telegram-storing houdt hij bij welke meldingen niet aankwamen. Een Herstelmelding gaat stil uit. De opbouw staat in 10.

- Uit 11: `/log` leest de dagbestanden achterwaarts en zoekt op een persoon (een accountnaam met de bijbehorende user ID's uit de gebruikerslijst, of één user ID) of op een code. Om te bladeren zit de positie in de knop. Elk Gebruikersbericht schrijft een regel `user_message` met de ontvanger, ook vanuit een job. Beslis hier ook of de lezer van `/log` een eigen module met eigen tests wordt.
- Uit 12: het hoofdbestand en de console onderscheiden eigen code van libraries aan de naam van de logger. Elke logger buiten die van de bot telt als library en komt pas vanaf WARNING binnen; het debug-bestand krijgt alles. Eén filter maskeert de geheimen uit dot-env (bot-tokens, API-keys, het Transmission-wachtwoord) in elke logregel, en de meldfunctie maskeert ze op dezelfde manier in alles wat hij naar Telegram stuurt. Na de logging-setup komen `logging.captureWarnings(True)` en een `sys.excepthook` die een regel `bot_crashed` schrijft. De heartbeat-taak (`asyncio.create_task` in `_post_init`, `src/bot.py`) is geen handler en geen job, maar krijgt dezelfde wrapper; nu stopt hij bij een onverwachte exceptie zonder enige regel.
- Uit 13:
  - **Toestand**: de meldfunctie houdt de toestand bij in `faults.json` (dev: `faults.dev.json`, per host), zodat die een herstart overleeft. Het gaat om open Storingen, de stand per Inrichtingsfout, de laatste melding per Bug-handtekening en de lijst `Not sent meanwhile`.
  - **Beslissen**: bij elke Fout beslist de meldfunctie of er een melding, een Herinnering of niets uitgaat, en de aanroeper hoort of er voor deze Fout een melding uit is.
  - **Sleutels**: een Inrichtingsfout heeft een sleutel (dienst + reden + item of instelling), een Bug een handtekening (dienst, type exceptie, binnenste eigen frame, bij een 4xx de statuscode).
  - **Controle slaagt**: een geslaagde controle moet de meldfunctie dat kunnen laten weten. Dat beëindigt een Storing (bij elk geslaagd antwoord van de dienst) of zet een Inrichtingsfout recht, met een Herstelmelding als er een melding uitging.
  - **Crash**: de `sys.excepthook` gebruikt dezelfde toestand en verstuurt bij een Bug zelf synchroon een melding.
  - **Logregels**: de logregel van een Fout is volledig bij de eerste keer en bij een melding. Daartussen is hij kort, met `repeat: n`.

  Te beslissen hier: welke code de melding over een crash toont, die buiten een Interactie valt.

Te beslissen: de vorm van `Fout` en de meldfunctie, wat de meldfunctie teruggeeft, hoe een aanroeper een logregel of gebruikersactie schrijft, en welke van deze stukken aparte modules zijn met hun eigen tests.

## Answer

Besloten in een grilling met de beheerder op 2026-11-03, in drie rondes. Nieuw begrip in `CONTEXT.md`: **Code**. De namen van modules, klassen en functies hieronder zijn voorstellen. De indeling, de interfaces en het gedrag zijn besloten.

### Logregels schrijven

1. **Een logger per module, met velden als keywords.** Een module maakt `log = get_logger(__name__)` aan en schrijft `log.info("searched 'dune' for movie: 7 results", event="search_term", query="dune", media_type="movie", results=7)`.
   - `media=` vult `media_title`, `media_year` en `tmdb_id` in één keer.
   - Het is synchroon, dus zonder `await`.
   - Alle loggers van de bot hangen onder één naam. Zo herkent de setup eigen code (12).
   - `logger` en `src` zijn die van de aanroeper (06).

   Er komt geen functie per soort uit de catalogus. Dat zouden zo'n 20 functies zijn die alleen doorgeven.
2. **`Log` gaat niet meer door de constructors.** Op de plek van de parameter `logger` komt `faults` (de meldfunctie), waar die nodig is. Overal anders verdwijnt de parameter. Een test geeft een nep-meldfunctie mee, zoals `tests/test_movie_states.py` nu een `MagicMock` meegeeft. Er komt geen object op moduleniveau.

### De Fault

3. **Naam in de code**: `Fault`, met `kind` = `FaultKind.BUG | DISRUPTION | SETUP`. Dat zijn dezelfde woorden als in het veld `fault` (06). In tickets en gesprekken blijven het Fout, Bug, Storing en Inrichtingsfout.
4. **Velden**:
   - `kind` en `service`
   - `what`: wat er misging, voor de kop van de melding ("Radarr refused the movie request")
   - `reason`: de reden van de dienst of de exceptie
   - `http_status` bij een HTTP-antwoord
   - alleen bij een Inrichtingsfout `check` en `item`. `check` zegt welke controle mislukte, bijvoorbeeld `series_path`, `tmdb_lookup`, `setting` of `disk_space`. `item` is het tmdb/tvdb-ID of de naam van de instelling. Met `service` erbij vormen ze de sleutel uit 13. Het veld heet niet `code`, omdat dat woord al voor de Code gebruikt wordt.
   - `details`: de velden waarop de beslissing viel, meegegeven waar de Fout gegooid wordt
   - `media` (besluit 7)
   - `user_text`: een optionele Nederlandse zin voor de Foutmelding (09, besluit 7)
   - de oorspronkelijke exceptie, via `raise Fault(...) from e`
5. **Drie constructors**: `Fault.bug(...)`, `Fault.disruption(...)` en `Fault.setup(...)`. Elke constructor neemt alleen de velden van zijn soort, dus een `Fault.setup` zonder `check` kan niet.
6. **Elke request krijgt een omschrijving mee**: `await self.post("/movie", payload, action="movie request")`. De requestregel (besluit 17) maakt daar "Radarr refused the movie request" of "Radarr is not responding" van.
7. **Het media-item komt uit de context.** Een handler of job zegt waar hij mee bezig is: `working_on(media)` zet het item in de context van de Interactie, net als `user_id` (01). De meldfunctie neemt het daaruit over als de Fault zelf geen `media` heeft. Een job met een lus zet het per item. Zo hoeft een aanroeper een Fault niet af te vangen om hem aan te vullen.

### De meldfunctie

8. **`await faults.report(fault, user_told=False, continued=None) -> bool`**:
   - Hij schrijft de logregel van de Fout: volledig, of kort met `repeat: n` (13). `src` is de binnenste eigen frame van de exceptie, of de aanroeper als er geen exceptie is.
   - Hij beslist via `faults.json`: een melding, een Herinnering of niets.
   - Hij verstuurt via de verzendfunctie (besluit 13) en houdt `Not sent meanwhile` bij.
   - Hij geeft `True` terug als de Beheerder van deze Fout weet: er ging nu een melding uit, of al eerder binnen de afremming (13, besluit 10). Dan staat in de Foutmelding "De serverbeheerder is hiervan op de hoogte".
   - Bij melden en doorwerken: `continued="sent the answer without a Plex link"`.
9. **Eerst `report()`, dan de Foutmelding.** Zo belooft de Foutmelding nooit een melding die niet uitging (05). `user told: yes` in de melding betekent daardoor "de wrapper gaat het de Gebruiker vertellen". Mislukt de Foutmelding daarna, dan staat dat alleen in het log, als poging van een Storing van Telegram.
10. **Een controle die slaagt**:
    - **Storing**: `await faults.ok(service)` bij elk geslaagd antwoord. Die aanroep zit in de requestregel (besluit 17) en in `TelegramRequest` (besluit 16), dus geen dienst roept hem zelf aan. Als er geen Storing open staat, kost hij bijna niets.
    - **Inrichtingsfout**: `await faults.fixed(service, check, item, msg="Carrie now has a path in Sonarr")`, aangeroepen door de code die de controle doet, als die slaagt. Staat er niets open, of ging er nooit een melding uit, dan ruimt hij alleen de toestand op. De aanroeper hoeft dus niet te weten of er iets open stond.
11. **De Code bij een Fout buiten een Interactie** (crash, heartbeat, pollen):
    - Alleen een Bug krijgt een eigen Code, die op zijn eigen logregel staat. Alleen dan staat er in het log meer dan in de melding, namelijk de traceback in `exc`. `grep <code>` of `/log <code>` vindt die regel.
    - Een Storing buiten een Interactie krijgt geen Code, net als de Herstelmelding na een Telegram-storing (10).
    - Bij een crashlus krijgt elke crash een eigen Code. De melding toont die van de crash die gemeld werd.
12. **Crash: `faults.report_crash(exc)`**, aangeroepen door de `sys.excepthook` uit 12. Die hook wordt geïnstalleerd zodra de meldfunctie bestaat.
    - Een `NetworkError` of `TimedOut` van Telegram wordt een Storing. Al het andere wordt een Bug.
    - Daarna draait dezelfde async `report()` in een nieuwe event loop (`asyncio.run`), met een nieuwe `Bot` en een timeout van 5 seconden. Zo is er één codepad voor beslissen, opmaken en versturen, en geen tweede, synchrone verzender.
    - Bij een Storing van Telegram telt `report()` alleen de poging en verstuurt hij niets (13, besluit 11).

### Telegram

13. **Eén verzendfunctie: `await send(chat_id, text, fmt, silent=False)`**:
    - Hij maskeert met `mask()` uit de logmodule (12), kapt af op 4096 tekens, en als Telegram de opmaak weigert, verstuurt hij het bericht één keer opnieuw als platte tekst met de regel ⚠️. De weigering schrijft hij als ERROR-regel met `fault: bug`, zonder eigen melding (10).
    - `NetworkError`, `TimedOut` en `RetryAfter` zet hij om in een Fault van Telegram (Storing).
    - `Forbidden` ("bot was blocked by the user") geeft hij terug als "niet afgeleverd", met de reden. Dat is geen Fault.
    - Hij wordt gebruikt door de meldfunctie, `send_admin_message`, `send_user_message` en de Foutmelding van de wrapper.
    - Gewone antwoorden in een Gesprek (`Functions.send_message`) blijven erbuiten. Een `NetworkError` daar valt door naar de wrapper (09, besluit 8).
14. **Andere berichten aan de Beheerder** (accountaanvraag, kwaliteitsverzoek en dergelijke) gaan via `send_admin_message(text)`. Ze houden hun inhoud en MarkdownV2 (10, besluit 5), maar krijgen hetzelfde maskeren, dezelfde terugval en dezelfde telling bij een Storing van Telegram.
    - Elk bericht schrijft een regel `admin_message_sent` zonder `fault`. In `msg` staat waar het over ging, maar niet de tekst zelf (04, punt 7).
    - Het opknippen in stukken van 1024 tekens vervalt: een bericht is hooguit 4096 tekens.
15. **Gebruikersberichten** gaan via `await send_user_message(user_id, kind, text, media=None)`. Die verstuurt het bericht en schrijft de regel `user_message` (11, punt 9).
    - Hij zoekt de accountnaam van de ontvanger op.
    - Hij schrijft INFO, of WARNING met `reason` als het bericht niet aankomt.
    - Een Fault van Telegram laat hij doorvallen naar de wrapper. Een Storing beëindigt dan de run (09, besluit 6).
    - Alle vier de soorten lopen hierdoor (`online`, `new_episodes`, `message`, `broadcast`), dus er kan geen Gebruikersbericht uitgaan zonder logregel.
16. **`TelegramRequest`**, een eigen subklasse van `HTTPXRequest`, ingesteld via `ApplicationBuilder.request()` en `.get_updates_request()`.
    - Bij elk geslaagd antwoord roept hij `faults.ok("telegram")` aan, ook bij het pollen. Zo komt de Herstelmelding na een storing in de nacht meteen, en niet pas bij het eerstvolgende bericht.
    - `getUpdates` krijgt geen `http_call`, anders komt er op DEBUG elke 5 seconden een regel bij.
    - Mislukte pogingen telt hij niet, want PTB moet zijn eigen excepties blijven zien om opnieuw te proberen. Die worden geteld waar ze opduiken: in `error_handler` (pollen), in de wrapper (een antwoord in een handler) en in de verzendfunctie.

### De requestregel

17. **`await call(service, action, attempt, retries=3)`** handelt het hele verloop van een request naar een dienst af.
    - Per poging schrijft hij een `http_call` op DEBUG, afgekapt op `LOG_MAX_BODY` (06).
    - Hij zet een antwoord of exceptie om volgens de tabel van 05.
    - Bij een Storing probeert hij het opnieuw, en pas na de laatste poging gooit hij de Fault. Dat is één mislukte poging in de zin van 13.
    - Bij succes roept hij `faults.ok(service)` aan.

    De client geeft alleen mee hoe hij één poging doet. Daar komen de status, de body en de reden uit, of bij plexapi en transmission-rpc de omzetting van hun excepties (09, besluit 2). Radarr en Sonarr houden 3 pogingen, de andere diensten 1, zoals nu.

### De Interactie en de wrapper

18. **De context en de wrappers**:
    - `InteractionProcessor`, de `BaseUpdateProcessor` uit 01, zet per update `interaction_id`, `user_id` en `account` of `tg_name`. Bij de start krijgt hij `account_for(user_id)` mee, die de gebruikerslijst in `data.json` leest.
    - `guard(callback)` komt om elke handler-callback en geeft na een Fout altijd `ConversationHandler.END` terug. Er is één variant voor alles, ook voor losse handlers zoals `/help` en `/log`, want daar negeert PTB de teruggegeven waarde.
    - `guard_job(callback)` zet per run een nieuwe context (`interaction_id` en `job`) en stuurt geen Foutmelding.
    - `guard_task(coro_fn)` is voor de heartbeat, die niet in een Interactie valt. Een exceptie is een Bug buiten een Interactie, met een eigen Code (besluit 11). Daarna start de wrapper de heartbeat na 60 seconden opnieuw. Stopt de heartbeat, dan denkt de watcher na een tijd dat de thuisserver uit de lucht is, en start hij de fallback-bot. Dan pollen er twee bots (Conflict). Een Bug die terugkomt, geeft door de afremming hooguit één melding per 24 uur.

### Modules en tests

19. **Indeling**. Elke module heeft eigen tests, behalve `src/log/files.py`.

| Module | Bestand | Interface | Wat erin zit |
|---|---|---|---|
| Logregels | `src/log/__init__.py` (vervangt `src/log.py`) | `setup_logging(env, level, folder, verbose)`, `get_logger(name)`, `mask(text)` | JSON-formatter met de velden van 06, een handler per dagbestand en het debug-bestand (07), de console, de filters voor context, maskeren en eigen code tegenover libraries (12), `captureWarnings` |
| Bestandsnamen | `src/log/files.py` (intern) | naam per dag, lijst van dagbestanden | gedeeld door de dagbestand-handler en de lezer; zonder eigen tests |
| Loglezer | `src/log/search.py` | `search(query, before=None)`: regels van nieuw naar oud, elk met een positie (datum van het bestand plus byte-offset). `query` is een set user ID's plus een accountnaam, of een Code | achterwaarts lezen, eerst een substring-check, in `asyncio.to_thread` (11) |
| Meldfunctie | `src/faults.py` | `Fault`, `FaultKind`, `FaultReporter.report / ok / fixed / report_crash`, plus het installeren van de excepthook | de toestand in `faults.json`, bijgewerkt onder één lock (jobs en updates lopen door elkaar op dezelfde loop), de beslisregels van 05 en 13, de HTML-opmaak van 10, `Not sent meanwhile`, `bot_crashed` |
| Verzendfunctie | `src/telegram_out.py` | `send`, `send_user_message`, `send_admin_message`, `TelegramRequest` | besluit 13 tot en met 16 |
| Interactie | `src/interaction.py` | `InteractionProcessor`, `guard`, `guard_job`, `guard_task`, `working_on`, `current_code()` | de contextvars, het samenstellen van de Foutmelding (09, besluit 7), het herstarten van de heartbeat |
| Requestregel | `src/services/request.py` | `call(service, action, attempt, retries)` | de tabel van 05, opnieuw proberen, `http_call`, `ok` |
| `/log` | `src/commands/log.py` | het command en de handler voor de knoppen | het argument herkennen (11, punt 3), de HTML-pagina bouwen, bladeren. De positie van de laatste regel gaat in de knop |

20. **Wat verdwijnt**:
    - de klasse `Log` met `logger`, `debug_call`, `send_telegram_message`, `clean_message`, `truncate` en `NoLibraryChatter`
    - `last_error` in de diensten
    - `_lookup_failures`, `_missing_path` en `LOOKUP_ALERT_THRESHOLD`
21. **Tests met `unittest`**, net als `tests/test_movie_states.py`, dus zonder nieuwe dependency. Elke module wordt getest via zijn eigen interface, met nepversies voor de verzendfunctie, de klok, de PTB-bot en een tijdelijke map. De belangrijkste gevallen:
    - **Meldfunctie**:
      - een Storing houdt aan na 2 pogingen over 15 minuten
      - `ok` geeft alleen een Herstelmelding als er een melding uitging
      - Herinneringen na 1, 3 en 7 dagen
      - een Inrichtingsfout wordt meteen gemeld, en `fixed` geeft een stille Herstelmelding
      - een Bug geeft één melding per 24 uur per handtekening
      - een Storing van Telegram: niets versturen, `Not sent meanwhile` bijhouden, daarna de Herstelmelding met de lijst
      - de toestand overleeft een nieuwe reporter op hetzelfde bestand
      - `report_crash`
      - een volledige of korte regel met `repeat`
      - wat `report()` teruggeeft
    - **Verzendfunctie**:
      - Telegram weigert de opmaak: het bericht gaat opnieuw als platte tekst met de regel ⚠️, plus een Bug-regel
      - een `NetworkError` wordt een Fault, en `Forbidden` geeft "niet afgeleverd"
      - het maskeren en de grens van 4096 tekens
      - de regel `user_message` met de accountnaam van de ontvanger, of een WARNING als het mislukt
    - **Interactie**:
      - een Fault in een handler geeft `END` en een Foutmelding, met of zonder "op de hoogte" en met de regel `Code:`
      - bij een Storing van Telegram komt er geen Foutmelding
      - een onbekende exceptie is een Bug
      - de context wordt na elke update gereset, en een job krijgt zijn eigen context
      - de heartbeat start na 60 seconden opnieuw (met een nep-`sleep`)
    - **Requestregel**:
      - 3 keer een 503 geeft één Storing, pas na de laatste poging
      - een 400 wordt een Bug met de reden (hooguit 300 tekens) en de status
      - 401 en 403 worden een Inrichtingsfout
      - na een geslaagd antwoord wordt `ok` één keer aangeroepen
      - elke poging krijgt een `http_call`, zonder apikey in de URL
    - **Logregels**:
      - de velden en hun volgorde, en velden zonder waarde worden weggelaten
      - UTF-8 blijft letterlijk staan
      - geheimen worden in elk veld gemaskeerd
      - INFO van een library komt niet in het hoofdbestand, wel in het debug-bestand
      - een nieuw dagbestand om middernacht lokale tijd, ook in de nacht van de klokwissel
      - `src` en `logger` zijn die van de aanroeper
    - **Loglezer**: zoeken over meerdere dagen, een halve laatste regel die de bot nog aan het schrijven is, en een gedeeld account.
    - **`/log`**:
      - de volgorde bij het herkennen: cijfers, dan accountnaam, dan Code (het geval "sander")
      - groeperen per dag, een gedeeld account, afkappen op 200 tekens
      - de teksten als er niets gevonden is

### Feiten uit de code (voor de implementatie)

- Nagekeken in een geïnstalleerde PTB 21.10.0:
  - `Application.process_update` wacht op de handler en gooit de teruggegeven waarde weg (`telegram/ext/_application.py:1307-1325`). `END` uit een losse handler kan dus geen kwaad. In een ConversationHandler houdt `None` de huidige state vast. Daarom geeft `guard` altijd `END` terug.
  - `run_polling` sluit bij het stoppen zijn event loop (`close_loop=True`). Daarom heeft `report_crash` een nieuwe loop nodig.
  - `HTTPXRequest.do_request` (`telegram/request/_httpxrequest.py:256`) en `ApplicationBuilder.request()` en `.get_updates_request()` (`telegram/ext/_applicationbuilder.py:468`, `:701`) bestaan.
- De twee `run_once`-jobs starten hun werk met `create_task` in een lambda (`src/bot.py:119-120`). `guard_job` moet om de coroutine zelf, anders valt een exceptie buiten de wrapper. De heartbeat start met `asyncio.create_task` (`src/bot.py:317`).
- De volgorde bij de start is een kringetje. De meldfunctie heeft de verzendfunctie nodig, de verzendfunctie de `Bot`, en die `Bot` wordt gebouwd met `TelegramRequest`, die `faults.ok` aanroept. Een van de drie krijgt zijn partner dus pas na het aanmaken.
- De gebruikerslijst staat in `data.json` onder `user_id`, als "accountnaam, Telegram-naam", en wordt per gebruik gelezen met aiofiles (`src/commands/message.py:179`).
- Er is geen eigen TMDB-client. Lookups gaan via Radarr en Sonarr (`/movie/lookup`, SkyHook).
- plexapi en transmission-rpc zijn synchroon en worden direct in async functies aangeroepen (`src/services/plex.py`, `src/services/transmission.py`). Tijdens zo'n request staat de event loop stil. Dat is geen logging, en de requestregel laat het zoals het is.
- De afmeldmelding gebruikt `self.log.escape_markdown` (`src/bot.py:376`). Die escape gaat mee naar `send_admin_message`.
