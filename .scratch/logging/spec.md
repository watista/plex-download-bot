# Logging-spec

Samengevoegd op 2026-11-03 uit de vijftien tickets van [de map](map.md). Deze spec legt vast hoe de bot logregels, gebruikersacties en admin-meldingen bij fouten produceert, zodat de Beheerder:

1. via SSH en via `/log <gebruiker>` kan terugzoeken wat een gebruiker deed;
2. kan zien waar een fout ontstond;
3. uit een admin-melding bij een fout direct begrijpt wat er mis is.

**Leeswijzer**

- Begrippen met een hoofdletter staan in [`CONTEXT.md`](../../CONTEXT.md): Gebruiker, Bezoeker, Beheerder, Gebruikersactie, Gesprek, Interactie, Geplande taak, Logregel, Code, Admin-melding, Herstelmelding, Herinnering, Foutmelding, Gebruikersbericht, Fout, Bug, Storing en Inrichtingsfout. In de code heten de soorten Fout `bug`, `disruption` en `setup`.
- Velden, gedrag en de indeling in modules zijn besloten. De namen van modules, klassen en functies zijn voorstellen. De soortnamen (`event`) zijn een voorstel uit 06 dat de latere tickets hebben overgenomen.
- Waarom iets zo is besloten, staat in het ticket. Elk hoofdstuk noemt zijn bronnen, met het nummer van het ticket ([lijst onderaan](#bronnen)). De keuze voor excepties met een centrale wrapper staat in [ADR 0001](../../docs/adr/0001-fouten-als-excepties-met-centrale-wrapper.md).
- Randvoorwaarden: alleen code in de bot, zonder extra infrastructuur of externe diensten. Er wordt niets automatisch verwijderd. Maintenance mode (de fallback-host) draait dezelfde code en valt er dus onder.

---

## 1. Logregels

Bronnen: 06, aangevuld door 08, 12, 13 en 15.

### Formaat

1. **JSON Lines**: één JSON-object per regel, in UTF-8. Tekens blijven letterlijk staan (`ensure_ascii=False`), dus "Amélie" en emoji zijn met `grep` te vinden. JSON escapet newlines en stuurtekens, dus één record is altijd één regel. `clean_message()` vervalt.
2. **Alles Engels**: veldnamen, soortnamen en berichten.
3. **Velden zonder waarde worden weggelaten**, dus er komt nooit `null` te staan. Een telling van 0 is wel een waarde en blijft staan.
4. **Separators zoals `json.dumps` ze standaard zet**: een spatie na `,` en na `:`. De substring-check van `/log` (`"user_id": 123`) rekent daarop.
5. Er komt geen tweede tekstbestand. Om via SSH te lezen, komt deze regel in de README:

   ```
   jq -r '"\(.ts) \(.level) \(.account // "-") \(.event // "-") \(.msg)"'
   ```

### Velden

In deze volgorde: eerst wat je in `less` wilt zien, de lange velden achteraan.

| Veld | Wanneer | Inhoud |
|---|---|---|
| `ts` | altijd | lokale tijd met offset en milliseconden, ISO 8601: `2026-11-03T14:05:12.345+01:00` |
| `level` | altijd | `DEBUG`, `INFO`, `WARNING` of `ERROR` |
| `user_id` | als er een persoon bij is | Telegram user ID, als getal |
| `account` | bij een Gebruiker | accountnaam |
| `tg_name` | alleen bij een Bezoeker | Telegram-naam |
| `event` | bij een eigen gebeurtenis | soortnaam, zie [Soortnamen](#soortnamen-event) |
| `msg` | altijd | korte Engelse zin in platte tekst, op zichzelf leesbaar |
| per soort | waar nodig | bijv. `query`, `media_type`, `media_title`, `media_year`, `tmdb_id`, `results`, `outcome`, `kind`, `duration_ms`, `http_status`, `reason`, `repeat`, `restored` |
| `fault` | bij een Fout, en bij `admin_message_sent` over een Fout | `bug`, `disruption` of `setup` |
| `service` | bij een Fout of een `http_call` | `radarr`, `sonarr`, `plex`, `transmission`, `tmdb`, `telegram` of `fallback` |
| `interaction_id` | in een Interactie | de Code: 6 tekens, zie [hoofdstuk 2](#2-interacties-en-codes) |
| `job` | in een run van een Geplande taak | naam van de job, bijv. `check_notify_list` |
| `logger` | altijd | module van de bot of naam van de library |
| `src` | altijd | `pad:regel in functie` van de code die de regel schrijft, niet van een wrapper. Bij een Fout is dat de binnenste eigen frame van de exceptie. |
| `exc_type` | bij een exceptie | bijv. `ConnectTimeout` |
| `exc` | bij een Bug of een onverwachte exceptie, alleen in een volledige regel | volledige traceback, inclusief gekoppelde excepties |

- **Persoon**: een Bezoeker heeft `user_id` en `tg_name`, een Gebruiker heeft `user_id` en `account`. Zo verschijnt een Bezoeker met de Telegram-naam "Wouter" nooit onder de accountnaam "Wouter".
- **Regels van libraries** krijgen binnen een Interactie dezelfde context mee (`user_id`, `account`, `tg_name`, `interaction_id`, `job`). Ze krijgen nooit `event` of `fault`.
- **Niet in een regel**: de host of instantie (elk bestand staat al op zijn eigen host) en de pid.

Voorbeeld van een gebruikersactie:

```json
{"ts": "2026-11-03T14:05:12.345+01:00", "level": "INFO", "user_id": 123456789, "account": "wouter", "event": "search_term", "msg": "searched 'dune' for movie: 7 results", "query": "dune", "media_type": "movie", "results": 7, "interaction_id": "k7p2qx", "logger": "commands.media", "src": "src/commands/media.py:60 in search"}
```

### Niveaus

Het niveau volgt uit wat er gebeurt, en bij een Fout uit de soort. Of er een admin-melding uitgaat (aanhouden, afremmen), verandert het niveau niet.

| Niveau | Wanneer | Voorbeelden |
|---|---|---|
| ERROR | Bug of Inrichtingsfout: de Beheerder moet iets rechtzetten | Radarr 400 "already added", geen passende state, serie zonder pad, lege TMDB-lookup, 401/403 |
| WARNING | Storing (elke mislukte poging), of iets onverwachts dat geen Fout is | Radarr 503, timeout, Telegram onbereikbaar, Conflict bij de start, een Gebruikersbericht dat niet aankomt |
| INFO | de normale gang van zaken | elke gebruikersactie, gesprek verlopen, admin-melding verstuurd, Herstelmelding, start en stop van de bot, het einde van een run |
| DEBUG | details om te debuggen | requests en responses, tussenstappen zoals `notify_check` |
| CRITICAL | niet gebruikt | |

Een Storing die aanhoudt, blijft per poging WARNING. Dat hij is opgeschaald, zie je aan de regel `admin_message_sent`. Live draait op INFO, dus alles wat `/log` moet tonen, staat op INFO of hoger.

### Inhoud

1. **Een leesbare zin plus velden.** `msg` is op zichzelf leesbaar in `less` en met `grep`. Alles waarop `/log` en `jq` filteren, staat daarnaast in aparte velden. Dat de informatie dubbel staat, is de bedoeling: regels van libraries hebben alleen `msg`.
2. **Platte tekst.** `msg` wordt nooit geëscapet voor MarkdownV2 of HTML.
3. **Geen grote gegevens boven DEBUG.** Een complete response of een compleet mediaobject staat nooit in een regel boven DEBUG. Wel:
   - de identificatie van een media-item: titel, jaar en tmdbId
   - bij een 4xx de reden van de dienst in `reason`, zoals "This movie has already been added"
   - bij een Bug de velden waarop de beslissing viel, zoals bij "geen passende state" de velden die het filter bekeek
4. **`http_call` op DEBUG**, één per poging, met `service`, `method`, `url` (zonder apikey), `http_status`, `duration_ms`, en `request` en `response` afgekapt op `LOG_MAX_BODY`. `getUpdates` van Telegram krijgt er geen, anders komt er elke 5 seconden een regel bij.
5. **Tracebacks.** Bij een Bug of een onverwachte exceptie komen `exc_type` en een volledige `exc` erin; `jq -r .exc` toont die weer over meerdere regels. Bij een Storing of Inrichtingsfout komen alleen `exc_type` en de tekst van de exceptie in `msg`. Een traceback wordt nooit met de hand in `msg` geplakt.

### Soortnamen (`event`)

| `event` | Niveau | Wanneer | Bron |
|---|---|---|---|
| de soorten uit de [catalogus](#catalogus) | INFO | elke Gebruikersactie | 04, 06 |
| `conversation_expired` | INFO | een Gesprek verloopt, met de stap waarin het was | 04 |
| `user_message` | INFO, of WARNING als het niet aankomt | elk Gebruikersbericht | 11, 15 |
| `admin_message_sent` | INFO | elke admin-melding en elk ander bericht aan de Beheerder; met `fault` bij een Fout, met `restored: true` bij een Herstelmelding | 06, 14 |
| `job_finished` | INFO | het einde van elke run van een Geplande taak | 15 |
| `transmission_back` | INFO | Transmission is weer bereikbaar en de zoekacties starten | 15 |
| `notify_check` | DEBUG | elk item dat `check_notify_list` controleert | 15 |
| `http_call` | DEBUG | elke poging van een request naar een dienst | 06, 14 |
| `bot_started`, `bot_stopped` | INFO | start en stop van de bot | 06, 12 |
| `bot_crashed` | WARNING of ERROR | het proces crasht na de logging-setup | 12 |

Een regel over een Fout herken je aan het veld `fault`.

### Nooit in een logregel

Bronnen: 04, 06, 12.

- Het wachtwoord van een login, in welke vorm dan ook, ook niet de lengte. Van een login wordt alleen de uitkomst vastgelegd.
- E-mail, telefoon en "via" uit een accountaanvraag. Die staan al in de admin-melding in Telegram, en het logbestand wordt nooit opgeruimd.
- De tekst van invoer buiten een Gesprek, en van genegeerde tekst. Juist daar kan iemand na een time-out zijn wachtwoord opnieuw sturen.
- De DEBUG-regels van PTB met de tekst van berichten: de aanroepen van de Bot API met hun parameters en antwoord (loggers `telegram.Bot` en `telegram.ext.ExtBot`), en "Processing update" en "Dropping pending update" (`telegram.ext.Application`). Eén filter op alle handlers laat ze weg, ook uit het debug-bestand: daarin stonden anders wachtwoorden, en e-mail en telefoon uit een accountaanvraag (besloten bij 05).
- De Telegram-naam van een Gebruiker; die staat er alleen bij een Bezoeker.
- Het tvdbId als aanduiding van media: dat gebeurt met titel, jaar en tmdbId. Alleen het `item` van een Inrichtingsfout kan een tvdb-ID zijn ([hoofdstuk 9](#9-afremmen-en-toestand)).
- **Geheimen.** Eén filter op alle handlers vervangt de waarden van `BOT_TOKEN`, `BOT_TOKEN_DEV`, `RADARR_API`, `SONARR_API`, `PLEX_API` en `TRANSMISSION_PWD` door `***`. Dat gebeurt in `msg` en in elk ander veld, ook in eigen regels. Dezelfde maskering (`mask()`) geldt voor alles wat de bot via de verzendfunctie naar Telegram stuurt.

---

## 2. Interacties en Codes

Bronnen: 01, 08, 14 en 15.

1. **Een Interactie** is één update (één Gebruikersactie plus de afhandeling ervan, inclusief regels van libraries en taken van `create_task`), of één run van een Geplande taak. Er komt geen ID per Gesprek: een Gebruiker heeft één Gesprek tegelijk, dus `user_id` plus de tijd vindt een Gesprek al terug.
2. **De Code is het `interaction_id`**: 6 willekeurige tekens uit het alfabet `23456789abcdefghjkmnpqrstuvwxyz`, zonder `0 o 1 l i`, bijvoorbeeld `k7p2qx`. Dat zijn ongeveer 887 miljoen combinaties, ruim genoeg zonder dat er iets verwijderd wordt. Er is geen apart fout-ID: een Fout hoort bij de Interactie waarin hij ontstond, zodat één `grep` de hele aanloop toont.
3. **De context** van een Interactie staat in contextvars:
   - bij een update: `interaction_id`, `user_id`, en `account` of `tg_name`
   - bij een run: `interaction_id` en `job`, zonder gebruikersvelden. Een run waarin de bot meerdere Gebruikers bedient, houdt één ID.
   - het media-item waar de Interactie mee bezig is (`working_on`), en de tellingen van een run (`tally`)

   De accountnaam komt uit de gebruikerslijst in `data.json` via het user ID (`account_for(user_id)`), niet uit de gespreksgegevens: `/help` en `/aanmelden_updates` lopen niet via de verificatie.
4. **Zetten en resetten**: een eigen `BaseUpdateProcessor` (`InteractionProcessor`) zet de context per update en reset hem met het `Token` in een `finally`. Hij wordt ingesteld met `ApplicationBuilder.concurrent_updates(InteractionProcessor(1))`, dus de verwerking blijft sequentieel, zoals nu. Zonder reset lekt de context naar de volgende update. Jobs erven de context niet betrouwbaar van de scheduler, dus `guard_job` zet per run een nieuwe. Taken van `create_task` erven de context van hun update.
5. **Buiten een Interactie** (opstarten, pollen, de heartbeat) is er geen `interaction_id`. Alleen een Bug buiten een Interactie, zoals een crash of een exceptie in de heartbeat, krijgt een eigen Code op zijn eigen logregel. Een Storing buiten een Interactie heeft er geen. Bij een crashlus krijgt elke crash een eigen Code, en de melding toont die van de crash die gemeld werd.
6. **Meerdere Fouten in één Interactie** delen hetzelfde ID, zonder volgnummer.
7. **Een melding over meerdere Interacties**:
   - een aanhoudende Storing toont het ID van de eerste mislukte poging, waar de Storing begon
   - een Herstelmelding toont dat ID plus het ID van de eerste geslaagde poging (`m4t9cw → r8h3ze`)
   - een Inrichtingsfout toont het ID van de run die de melding uitlokte; de Herstelmelding `Fixed` toont de code van de eerste melding plus die van de Interactie waarin de controle slaagde
8. **In de Foutmelding** staat de Code altijd, als laatste regel `Code: k7p2qx`, ook als er (nog) geen admin-melding uitgaat. In de tekst voor de Gebruiker heet het "code", niet "foutcode".

---

## 3. Bestanden

Bronnen: 06, 07 en 12.

1. **Eén bestand per kalenderdag, in lokale tijd** (dezelfde tijd als `ts`). Het bestand volgt uit de tijd van de regel zelf (`record.created`), niet uit de start van het proces. Na een herstart schrijft de bot verder in het bestand van die dag. Een bestand wordt nooit hernoemd, geleegd of verwijderd. Op de dagen dat de klok verzet wordt, beslaat een bestand 23 of 25 uur.
2. **Naam**: `plex-download-bot-JJJJ-MM-DD.jsonl` voor live, ook in maintenance mode, en `dev-plex-download-bot-JJJJ-MM-DD.jsonl` voor dev. De map blijft `LOG_FOLDER`.
3. **Elke host houdt zijn eigen logbestanden.** `log/` blijft buiten Syncthing, en de hostnaam staat niet in de naam. `/log` en SSH tonen alleen wat op die host gebeurde.
4. **Het hoofdbestand bevat altijd INFO en hoger**, welke `LOG_TYPE` er ook staat. Bij `LOG_TYPE=DEBUG` komt er per dag een tweede bestand, `…-JJJJ-MM-DD-debug.jsonl`, met alles vanaf DEBUG, inclusief de regels van INFO en hoger. `LOG_TYPE` kent alleen nog `INFO` en `DEBUG`. Ook het debug-bestand wordt nooit automatisch verwijderd; DEBUG zet je tijdelijk aan.
5. **Wat in welk bestand komt**:

   | Uitvoer | Eigen code | Libraries |
   |---|---|---|
   | hoofdbestand | vanaf INFO | vanaf WARNING |
   | debug-bestand (bij `LOG_TYPE=DEBUG`) | vanaf DEBUG | vanaf DEBUG, ook httpx en httpcore bij elke poll, maar zonder de regels van PTB met de tekst van berichten (zie [Nooit in een logregel](#nooit-in-een-logregel)) |
   | console (alleen bij `--verbose`) | vanaf `LOG_TYPE` | vanaf WARNING |

   De console toont tekst in dezelfde weergave als de `jq`-regel: `ts level account event msg`. Eigen code zijn de loggers van de bot, die onder één naam hangen. Elke andere logger telt als library, ook een die nu nog niet bekend is.
6. **Een eigen handler** kiest per regel het dagbestand op basis van `record.created`. `TimedRotatingFileHandler` valt af: op Python 3.12.3 (de server) roteert hij na de overgang naar wintertijd niet meer tot een herstart.
7. **journald krijgt geen logregels.** Het journal blijft de plek voor wat buiten de logging valt: meldingen van systemd en een crash vóór de logging-setup. Om via SSH live mee te kijken, komt in de README `tail -F` op het bestand van vandaag, met de `jq`-regel. Die volgt niet over middernacht heen.
8. **Geen compressie en geen maximumgrootte.** Op INFO wordt dat tientallen kB per dag. Een maximumgrootte zou regels weggooien, juist bij een Bug die je wilt zien. Herhaling wordt afgeremd in de regels zelf ([hoofdstuk 9](#9-afremmen-en-toestand)).
9. **Bestaande `.log`-bestanden blijven staan** zoals ze zijn en worden niet omgezet. `/log` leest alleen `.jsonl`, dus het kijkt niet verder terug dan de dag van de overstap.

---

## 4. Regels van buiten de eigen code

Bronnen: 12, 13 en 14.

1. **Libraries**: in het hoofdbestand vanaf WARNING (zie de tabel in [hoofdstuk 3](#3-bestanden)). Een regel van een library houdt zijn eigen niveau en wordt nooit een Fout: hij krijgt geen `event` en geen `fault`, en er gaat geen admin-melding over uit. Wat telt, vangt de wrapper in de eigen code af. Uit het hoofdbestand verdwijnen zo de start- en stopregels van PTB, die `bot_started` en `bot_stopped` vervangen, en "Flood control exceeded" van de Updater. Wel blijven bijvoorbeeld de WARNINGs van apscheduler over een overgeslagen run.
2. **Python-warnings** worden logregels via `logging.captureWarnings(True)`: WARNING, logger `py.warnings`. De `PTBUserWarning` over `per_message=False` wordt gericht onderdrukt bij het bouwen van de ConversationHandler, met een comment waarom. `per_message=False` klopt, want de handler bevat ook CommandHandlers en MessageHandlers. Een warning in het logbestand is zo altijd iets nieuws. De waarschuwing van systemd over de unit blijft in het journal.
3. **Een crash van het proces** na de logging-setup: een `sys.excepthook` geeft de exceptie aan `faults.report_crash(exc)` ([hoofdstuk 12](#de-meldfunctie)), die één regel `bot_crashed` schrijft en zo nodig een admin-melding stuurt. Daarna geeft de hook de exceptie door aan de standaard hook, zodat hij ook in het journal blijft.
   - Een `NetworkError` of `TimedOut` van Telegram is een Storing: WARNING, `fault: disruption`, `service: telegram`, met alleen `exc_type` en de tekst.
   - Al het andere is een Bug: ERROR, met de volledige `exc` en een eigen Code.

   Een crash vóór de logging-setup (een variabele die ontbreekt in dot-env, een importfout) blijft alleen in het journal: er is dan nog geen logbestand.
4. **Pollfouten van Telegram**: elke `NetworkError` bij het pollen is een mislukte poging van een Storing van Telegram: WARNING, `fault: disruption`, `service: telegram`, zonder `interaction_id`. Begin en einde krijgen geen eigen regel: het einde staat in het log via de Herstelmelding (`admin_message_sent` met `restored: true`). Een `TimedOut` bij het pollen blijft een DEBUG-regel van PTB. Een Conflict bij de start blijft één WARNING zonder `fault`.
5. **De heartbeat** is geen handler en geen job. Hij loopt via `guard_task` ([hoofdstuk 12](#de-interactie-en-de-wrappers)), die hem na een Bug na 60 seconden opnieuw start.

---

## 5. Gebruikersacties

Bronnen: 04, 06 en 11.

### Uitgangspunten

1. **Elke stap.** Elk bericht en elke knopdruk die de bot ontvangt, is een Gebruikersactie met een eigen logregel, beschreven naar betekenis ("chose option 3: Dune (2021)", "notify: yes"). Dat geldt ook voor invoer die de bot negeert.
2. **Wie.** Elke regel bevat het Telegram user ID en de accountnaam. Bij een Bezoeker staat de Telegram-naam in `tg_name` in plaats van een accountnaam.
3. **Bezoekers tellen mee.** Acties van iemand die nog niet is ingelogd, een account aanvraagt of geblokkeerd is, worden ook vastgelegd. Na het inloggen blijven eerdere acties te vinden via het user ID.
4. **Gedeelde accounts.** De Gebruiker is de accountnaam. Meerdere user ID's kunnen onder één accountnaam vallen, en omdat elke regel beide bevat, blijven die personen te onderscheiden.
5. **Uitkomst.** Bij elke actie waar de bot iets mee doet, staat in dezelfde regel wat de bot deed of vond, in `outcome` en in `msg`.
6. **Admin-commands** van de Beheerder zijn Gebruikersacties en volgen dezelfde regels.
7. **Media** worden aangeduid met titel, jaar en tmdbId (`media=` vult `media_title`, `media_year` en `tmdb_id`).
8. **Einde van een Gesprek.** `/stop` is een gewone command-actie. Verloopt een Gesprek (nu na 30 minuten, `conversation_timeout=1800`), dan komt er een regel `conversation_expired` bij die Gebruiker of Bezoeker, met de stap waarin het Gesprek was. Dat is geen Gebruikersactie, maar hoort wel in het spoor van die persoon.

### Catalogus

| `event` | Wanneer | Gegevens | Uitkomst |
|---|---|---|---|
| `command` | elk command, ook `/stop` | welk command | in maintenance mode: onderhoudsbericht |
| `menu_choice` | knop in het startmenu of het /help-menu | welke knop | in maintenance mode: onderhoudsbericht |
| `login` | wachtwoord ingevoerd, of een geblokkeerde Bezoeker probeert het | nooit de tekst | gelukt + accountnaam, in maintenance mode met de onderhoudsmelding als die volgt / fout (poging n van 3) / geblokkeerd / geweigerd (staat al op de blokkadelijst) |
| `search_term` | titel ingetypt bij film, serie of aanmelden voor een serie | zoekterm letterlijk + waarvoor (`media_type`, bij aanmelden ook `purpose: series_updates`) | aantal resultaten; bij aanmelden het aantal series dat je kunt kiezen |
| `search_button` | "toon meer", "probeer opnieuw", ja/nee bij "nog een keer proberen?" | welke knop | – |
| `media_request` | optie gekozen | optienummer, titel, jaar, tmdbId | download gestart / wordt al gedownload / al gedownload / nog niet uit / geen downloadmatch / unmonitored (al in Radarr of Sonarr, of meer dan 5 seizoenen met `seasons`) / geen ruimte / fout (`failed`) |
| `notify_choice` | ja/nee op "melding als het online staat?" | keuze | – |
| `quality_request` | ja/nee, reden, omschrijving (film, "overig") of seizoen en aflevering (serie) | reden, tekst letterlijk | – |
| `series_updates` | aan- of afmelden voor een serie, ook ja/nee na een aanvraag | titel, tmdbId | aangemeld / afgemeld / niets om af te melden. Geen resultaten bij het zoeken staat in `search_term` (`results: 0`). |
| `general_updates` | aan of uit | aan of uit | gewijzigd / stond al zo |
| `account_request` | elke stap | alleen de naam letterlijk; bij e-mail, telefoon en "via" alleen "beantwoord" | – |
| `help_question` | vraag via /help → Anders | tekst letterlijk | – |
| `admin_command` | `/message`, `/message_all`, `/add_movie`, `/log` | `/message`: ID van de ontvanger + tekst; `/message_all`: tekst; `/add_movie`: ID van de ontvanger + tmdbId; `/log`: het argument | `/message_all`: aantal verstuurd en overgeslagen |
| `outside_conversation` | tekst terwijl er geen Gesprek loopt | niet de tekst | `/start` getoond |
| `ignored` | tekst terwijl de bot op een knopdruk wacht, een knop uit een oud bericht, een onbekend command, een command dat op dat moment niets doet (`/stop` zonder Gesprek, `/start` midden in een Gesprek), `/log` van iemand anders of in de groep | soort invoer, stap van het Gesprek, waarde van de knop of het command; niet de tekst | – |

Een command of een knop in een menu krijgt altijd zijn regel `command` of `menu_choice`. Volgt er in dezelfde Interactie een regel van een andere soort, zoals `general_updates` of `login` (geweigerd), dan staat de uitkomst in die regel (besloten bij 05).

`stats.json` blijft ongewijzigd en krijgt geen logregel.

---

## 6. Gebruikersberichten en andere berichten aan de Beheerder

Bronnen: 04, 10, 11, 14 en 15.

1. **Elk Gebruikersbericht krijgt een regel `user_message`.** Het gaat via `send_user_message`, dus er kan geen Gebruikersbericht uitgaan zonder logregel.
   - INFO, met `user_id` en `account` van de ontvanger. Dat geldt ook in een run van een Geplande taak, die zelf geen gebruikersvelden heeft.
   - `kind`: `online`, `new_season`, `new_episodes`, `message` of `broadcast`
   - bij media: titel, jaar en tmdbId
   - geen tekst bij `message` en `broadcast`, want die staat al in de regel `admin_command` van de Beheerder
   - komt het bericht niet aan (`Forbidden`, "bot was blocked by the user"), dan wordt het een WARNING met `reason`. Dat is geen Fout.

   Bij `/message_all` levert dat ongeveer 20 regels per keer op.
2. **Admin-meldingen worden niet meer naar het logbestand gekopieerd.** De logregel van de Gebruikersactie is de registratie. Er staan dus geen e-mailadressen en telefoonnummers uit accountaanvragen meer in het log.
3. **Andere berichten aan de Beheerder** (accountaanvraag, kwaliteitsverzoek, "User notified", "Bot gestart" en dergelijke) houden hun inhoud en MarkdownV2; ze vallen verder buiten deze spec. Ze gaan wel via `send_admin_message`, met hetzelfde maskeren, dezelfde terugval op platte tekst en dezelfde telling bij een Storing van Telegram als een admin-melding over een Fout.
   - Elk bericht schrijft een regel `admin_message_sent` zonder `fault`. In `msg` staat waar het over ging, maar niet de tekst zelf.
   - Het opknippen in stukken van 1024 tekens vervalt: een bericht is één bericht van hooguit 4096 tekens.

---

## 7. Geplande taken

Bron: 15, met 08, 09 en 14.

| `job` | Wanneer | Mode | Regels naast Fouten en `job_finished` |
|---|---|---|---|
| `check_notify_list` | elke 30 minuten, de eerste bij de start | normal | `user_message` per Gebruikersbericht, `admin_message_sent` per "User notified", `notify_check` per item (DEBUG) |
| `check_transmission` | elke 30 minuten | normal | `transmission_back` |
| `scan_missing_sonarr`, `scan_missing_radarr` | elke 6 uur, de eerste bij de start | normal | – |
| `publish_command_list` | eenmalig bij de start | normal en maintenance | – |
| `notify_admin_startup` | eenmalig bij de start | normal en maintenance | `admin_message_sent` |

1. **Namen**: de naam in `job` wordt met `name=` meegegeven bij het registreren. Zonder `name=` noemt PTB een job naar zijn callback, en dan heten beide scans `scan_missing_media`.
2. **Eén eindregel per run, altijd.** `guard_job` schrijft hem in een `finally`: `event: job_finished` op INFO, met `outcome` (`ok` of `stopped`), `duration_ms` en de tellingen van de job.
   - Ook een run zonder resultaat krijgt hem, en ook een run die door een Fout stopte. Na een stop staan de tellingen tot dat moment erin.
   - Er komt geen beginregel. De eerste regel van de run en `duration_ms` laten de start al zien.
   - Dat zijn zo'n 104 regels per dag, plus 2 bij elke start. `/log <persoon>` toont ze niet, want ze hebben geen gebruikersvelden. `/log <code>` van een Fout in een job laat zo ook zien hoe de run afliep.
3. **Tellingen**:

   | Job | Velden naast `outcome` en `duration_ms` | `msg`, bijvoorbeeld |
   |---|---|---|
   | `check_notify_list` | `items`, `sent`, `not_delivered`, `skipped` | "check_notify_list finished in 4.2 s: 14 items checked, 2 messages sent" |
   | `check_transmission` | geen | "check_transmission finished in 0.2 s: Transmission reachable" |
   | `scan_missing_sonarr`, `scan_missing_radarr` | geen | "scan_missing_sonarr finished in 0.3 s: missing search started" |
   | `publish_command_list`, `notify_admin_startup` | geen | "publish_command_list finished in 0.1 s" |

   `items` is het aantal gecontroleerde items, `sent` het aantal afgeleverde Gebruikersberichten, `not_delivered` het aantal dat niet aankwam, en `skipped` het aantal items dat de run oversloeg door een Inrichtingsfout. Een telling van 0 staat erin als `0`. Na een stop: "check_notify_list stopped after 1.2 s: 6 items checked, 1 message sent".
4. **Tellen met `tally(name, n=1)`**. Dat houdt de tellingen bij in de context van de Interactie, en `guard_job` leest ze in de `finally`, dus ook na een stop. `send_user_message` telt `sent` en `not_delivered` zelf. De job telt alleen `items` en `skipped`.
5. **`notify_check` (DEBUG)**, één per gecontroleerd item, met:
   - `kind`: `online`, `new_season` of `new_episodes`, dezelfde waarden als bij `user_message`
   - de media-velden uit `working_on(item)`
   - `user_id` en `account` van de ontvanger, als keywords op de regel zelf en niet in de context. Een Fout tijdens dat item, zoals een serie zonder pad, krijgt zo geen gebruikersvelden en verschijnt niet in `/log <persoon>`.
   - `outcome`: `no_data`, `no_folder`, `seasons_missing` (met `missing`, bijv. `["S03"]`), `empty_folder`, `nothing_new` of `sent`

   Live staan deze regels nergens. Wil de Beheerder weten waarom iemand geen bericht kreeg, dan zet hij tijdelijk DEBUG aan. Het bijwerken van `data.json` (een item van de lijst halen, de stand van de seizoenen bijwerken) krijgt geen eigen regel: de regel `user_message` is de registratie.
6. **`check_transmission` is een eigen job.** Nu staat de check vooraan in `check_notify_list`, die een onbereikbaar Transmission stil inslikt. Voortaan is dat een poging van een Storing, en die beëindigt alleen de run van `check_transmission`. De Gebruikersberichten lopen dus door, en de Code in een melding over Transmission wijst naar de goede job. Is Transmission twee runs achter elkaar onbereikbaar (30 minuten), dan krijgt de Beheerder een admin-melding, en later een Herstelmelding.
7. **`transmission_back`**: is Transmission bereikbaar terwijl hij bij de vorige run onbereikbaar was, dan schrijft de run vóór de twee zoekacties een INFO-regel "Transmission is back: starting the missing searches in Sonarr and Radarr". Mislukt daarna een zoekactie, dan volgen de regel van de Storing en een eindregel met `stopped`. Na een herstart weet de bot niet of Transmission onbereikbaar was, dus de eerste run start geen zoekacties, zoals nu.
8. **De overige jobs schrijven alleen hun eindregel.** De scans sturen één POST; wat Sonarr of Radarr daarna vindt, ziet de bot niet, en de `http_call` staat op DEBUG. `notify_admin_startup` stuurt "Bot gestart" via `send_admin_message`, die zelf `admin_message_sent` schrijft.
9. **Fouten in een run**: een Inrichtingsfout voor één item wordt gemeld en dat item wordt overgeslagen (`skipped`). Een Storing of Bug beëindigt de run. `guard_job` stuurt geen Foutmelding.

Voorbeeld van twee eindregels:

```json
{"ts": "2026-11-03T14:30:04.210+01:00", "level": "INFO", "event": "job_finished", "msg": "check_notify_list finished in 4.2 s: 14 items checked, 1 message sent", "outcome": "ok", "duration_ms": 4210, "items": 14, "sent": 1, "not_delivered": 0, "skipped": 0, "interaction_id": "k7p2qx", "job": "check_notify_list", "logger": "…", "src": "…"}
{"ts": "2026-11-03T15:00:01.412+01:00", "level": "INFO", "event": "job_finished", "msg": "check_notify_list stopped after 1.2 s: 6 items checked, 0 messages sent", "outcome": "stopped", "duration_ms": 1204, "items": 6, "sent": 0, "not_delivered": 0, "skipped": 0, "interaction_id": "m3tq8w", "job": "check_notify_list", "logger": "…", "src": "…"}
```

---

## 8. Fouten

Bronnen: 05, 09 en 13, ADR 0001.

### Soorten

Elke Fout krijgt een logregel. Er komt alleen een admin-melding bij als de Beheerder iets moet doen. Wat geen Fout is, blijft alleen een logregel.

| Soort | `fault` | Wat | Admin-melding |
|---|---|---|---|
| **Bug** | `bug` | De bot doet zelf iets wat niet klopt. | de eerste keer; daarna hooguit één per 24 uur per handtekening |
| **Storing** | `disruption` | Een dienst waar de bot van afhangt (Radarr, Sonarr, Plex, Transmission, TMDB, Telegram, de fallback-host) reageert niet of geeft een serverfout. | alleen als hij aanhoudt, met Herinneringen, en daarna een Herstelmelding |
| **Inrichtingsfout** | `setup` | Iets in de inrichting van de server klopt niet of schiet tekort, en alleen de Beheerder kan het met de hand rechtzetten: gegevens in Sonarr of Radarr, een instelling van de bot, een volle opslag. | meteen, met Herinneringen, en een Herstelmelding als hij is rechtgezet |

Eén Fout geeft hooguit één admin-melding. Hoe het afremmen precies werkt, staat in [hoofdstuk 9](#9-afremmen-en-toestand).

### Indeling

De soort wordt bepaald waar het antwoord binnenkomt:

| Antwoord of situatie | Soort | Wie bepaalt het |
|---|---|---|
| onbereikbaar, timeout of 5xx | Storing | de requestregel |
| 4xx, behalve 401 en 403 | Bug: de bot vroeg iets wat niet kan. De reden van de dienst gaat mee. | de requestregel |
| 401 of 403 | Inrichtingsfout: een verkeerde API-sleutel | de requestregel |
| een geslaagd antwoord met een leeg of verkeerd resultaat (lege TMDB-lookup, SkyHook die een andere titel teruggeeft), een serie zonder pad, een ontbrekende of verkeerde instelling, opslag vol | Inrichtingsfout | de aanroeper, die hem zelf gooit |
| elke andere exceptie die de wrapper bereikt, ook `BadRequest: Can't parse entities` van Telegram | Bug | de wrapper |
| `NetworkError`, `TimedOut` of `RetryAfter` van Telegram | Storing | de verzendfunctie, de wrapper of `error_handler` |

Geen Fout, alleen een logregel:

- een Conflict bij de start (WARNING zonder `fault`)
- geen Plex-match voor een titel: de Gebruiker krijgt het bericht zonder link
- `/message_all` of een ander Gebruikersbericht dat niet aankomt (`user_message` op WARNING)
- een regel van een library

### Per geval

Uit de live-logs van oktober (03) en de code. De admin-melding volgt uit de soort, tenzij er iets anders staat.

| Geval | Waar in de code nu | Soort |
|---|---|---|
| Serie zonder pad, bij de geplande check of bij het aanmelden; beide zijn dezelfde Fout | `src/commands/schedule.py` (`log_missing_path`), `src/commands/serie.py:219` | Inrichtingsfout |
| TMDB-lookup leeg | `src/services/arr.py` (`log_lookup_failure`) | Inrichtingsfout |
| Radarr 400 "This movie has already been added" | `src/services/arr.py` (`post`) | Bug, met de reden van Radarr |
| Geen passende state bij "media state filtering" | `src/commands/media.py:335` | Bug, met de velden die het filter bekeek |
| Radarr of Sonarr onbereikbaar, of 503 | `src/services/arr.py` | Storing |
| Telegram onbereikbaar, of een startcrash door DNS | `error_handler`, `run_polling` | Storing |
| Onverwachte exceptie in `error_handler` | `src/bot.py` (`error_handler`) | Bug |
| Transmission onbereikbaar | `src/services/transmission.py` | Storing |
| Plex niet te bereiken, of de bibliotheek geeft een fout | `src/services/plex.py:47`, `:94` | Storing |
| Heartbeat naar de fallback-host mislukt | `src/bot.py` (`_heartbeat_loop`) | Storing |
| Instelling ontbreekt of klopt niet: Plex-URL of -token, `HEARTBEAT_TARGET_PORT`, een mediamap die bij geen schijf hoort, een API-sleutel (401/403) | `src/services/plex.py:32` e.a. | Inrichtingsfout |
| Opslag vol: geen schijf met 150 GB vrij. Dit staat los van een mislukte diskspace-check, die een Storing is. | `src/commands/media.py:475` | Inrichtingsfout |
| Media zonder titel bij het maken van een Plex-link | `src/services/plex.py:80` | Inrichtingsfout |
| Plex-link: onverwachte exceptie | `src/services/plex.py:119` | Bug, één melding in plaats van twee |
| `stats.json` niet te schrijven | `src/commands/media.py:489` | Bug |
| Conflict-melding in maintenance mode, als beide instanties tegelijk pollen | `src/bot.py:528` | blijft zoals hij is (admin-melding, afgeremd) |
| Start- of stopbericht aan de groep mislukt; de HTML-broadcast valt terug op platte tekst | `src/bot.py:307`, `:381`, `src/commands/message.py:40` | blijft een logregel |
| `CHAT_ID_GROUP` ongeldig | `src/bot.py:288` e.a. | Inrichtingsfout, maar blijft een logregel: in live kan dan geen enkele admin-melding aankomen |
| `HEARTBEAT_TARGET_HOST` niet ingesteld | | geen Fout: de heartbeat staat bewust uit, zoals op dev. Blijft een logregel. |

### Afvangen

1. **Een Fout is een exceptie met een soort** (`Fault`, [hoofdstuk 12](#de-fault)). Diensten geven geen `False`/`None` plus `last_error` meer terug. Wie niets met een Fout kan, laat hem doorvallen. Zo hoort er bij elke Fout één object, en de traceback gaat mee naar `exc`.
2. **De requestfunctie van elke dienst** zet een antwoord of library-exceptie om in een Fault, via één gedeelde requestregel (`call`), zodat de tabel hierboven op één plek staat. plexapi en transmission-rpc krijgen in hun eigen client een omzetting van hun excepties.
3. **Eén centrale vangplek: een wrapper om elke handler en elke job.** Die schrijft de logregel en laat de admin-melding uitgaan, allebei via de meldfunctie. Daarna stuurt hij de Foutmelding. Een Fout beëindigt het Gesprek: de wrapper geeft `ConversationHandler.END` terug. Daarom is het niet PTB's `error_handler`, want die kan geen `END` teruggeven, en dan blijft de Gebruiker in een halve state hangen.
4. **De wrapper komt bij het registreren** in `src/bot.py` om de callback: elke callback van een `CommandHandler`, `CallbackQueryHandler` of `MessageHandler`, en die van `run_repeating` en `run_once`. Commands weten er niets van.
5. **Lokaal afvangen mag alleen om door te werken**, bijvoorbeeld als de Plex-link ontbreekt maar het antwoord wel uitgaat. De vangplek meldt de Fout dan via `faults.report(fault, continued="sent the answer without a Plex link")`, en gooit hem niet opnieuw. Afvangen, zelf loggen en doorgaan mag niet meer, en een eigen admin-melding sturen ook niet.
6. **Een Storing van Telegram tijdens een handler** (`NetworkError`, `TimedOut`, `RetryAfter` bij het antwoorden): de wrapper legt de Storing vast en probeert géén Foutmelding. De bot wacht niet in de handler op `RetryAfter`.
7. **`error_handler` blijft het vangnet.** Netwerkfouten bij het pollen en Conflict blijven daar ([hoofdstuk 4](#4-regels-van-buiten-de-eigen-code)). Al het andere wat er aankomt (een fout in de wrapper, een callback die per ongeluk niet gewikkeld is), behandelt hij als Bug via de meldfunctie, met in de melding "Caught by error_handler, outside the wrapper". Hij kan geen Gesprek beëindigen, en stuurt alleen een Foutmelding als er een `update` met een chat is.

### Foutmelding

De wrapper stelt de Foutmelding samen; handlers sturen er zelf geen meer. Hij is Nederlands en bestaat uit:

1. een zin over wat er misging: `user_text` van de Fault (bijv. "Er is op dit moment een probleem met de opslag van de Plęx server"), of anders een standaardzin per soort;
2. "De serverbeheerder is hiervan op de hoogte", alleen als `report()` `True` teruggaf. Anders zegt de Foutmelding dat de Gebruiker het later nog eens kan proberen;
3. "Stuur /start om opnieuw te beginnen.";
4. `Code: <interaction_id>`.

Eerst `report()`, dan de Foutmelding. Zo belooft de Foutmelding nooit een melding die niet uitging. Mislukt de Foutmelding daarna, dan staat dat alleen in het log, als poging van een Storing van Telegram. Een job stuurt geen Foutmelding.

---

## 9. Afremmen en toestand

Bron: 13, met 14.

### Storingen

1. **Een Storing houdt aan** bij minstens 2 mislukte pogingen, de laatste minstens 15 minuten na de eerste, zonder geslaagd antwoord van die dienst ertussen. Dat geldt voor elke dienst hetzelfde, en het wordt bekeken bij elke mislukte poging: er is geen aparte timer. Een request die het met opnieuw proberen nog steeds niet haalt, telt als één mislukte poging.
2. **Een Storing is voorbij** bij het eerste geslaagde antwoord van dezelfde dienst, op welke request ook (`faults.ok(service)`). De bot controleert een dienst niet zelf. Een Storing die voorbij is voordat hij aanhield, laat alleen logregels achter, zonder Herstelmelding.
3. **Telegram**: na een Storing van Telegram komt er een Herstelmelding als hij aanhield, of als de lijst `Not sent meanwhile` niet leeg is. Een `NetworkError` bij het versturen van een admin-melding of Foutmelding telt ook als mislukte poging. Een crash door een Storing van Telegram krijgt geen eigen melding: hij telt als poging van die Storing.
4. **Herinnering bij een Storing**: met dezelfde tussenpozen als bij een Inrichtingsfout. Hij gaat uit bij de eerste mislukte poging nadat de tussenpoos voorbij is. Wordt de dienst niet aangeroepen, dan komt er geen. Bij een Storing van Telegram kan er geen komen.
5. **Een dienst die blijft haperen** krijgt geen extra regel. Elke ronde die aanhoudt, geeft een melding en een Herstelmelding.

### Inrichtingsfouten

6. **Meteen melden, daarna Herinneringen**: na 1 dag, dan na 3 dagen en daarna elke 7 dagen, telkens gemeten vanaf de vorige melding en bekeken als de Fout opnieuw voorkomt. `LOOKUP_ALERT_THRESHOLD` vervalt.
7. **Dezelfde Inrichtingsfout** heeft dezelfde sleutel: dienst + `check` + `item` (tmdb- of tvdb-ID, of de naam van de instelling). Bij opslag vol is het alleen dienst + `check`. Een serie zonder pad is dus één Fout, of hij nu opvalt bij de geplande check of bij het aanmelden van een Gebruiker. Wie daarna op die Fout stuit, krijgt een Foutmelding dat de beheerder op de hoogte is. De Fout telt per run, niet per aanroep.
8. **Rechtgezet**: slaagt dezelfde controle, dan roept de code die controleert `faults.fixed(...)` aan. Ging er over die Fout een melding uit, dan komt er een stille Herstelmelding met de kop `✅ Fixed`.
9. **Niet meer gecontroleerd**: een Inrichtingsfout die 30 dagen niet voorkwam, verdwijnt stil, zonder Herstelmelding. Komt hij daarna terug, dan is het een nieuwe Fout met een eerste melding.

### Bugs

10. **Hooguit één melding per 24 uur per handtekening.** De handtekening bestaat uit de dienst, het type exceptie, de binnenste eigen frame (bestand:regel) en bij een 4xx de statuscode. De tekst van de reden telt niet mee, want daar staan titels in. Wie de Bug binnen die 24 uur raakt, krijgt te horen dat de beheerder op de hoogte is.
11. **Crash door een Bug**: de excepthook verstuurt zelf een admin-melding, afgeremd per handtekening. Een crashlus geeft zo één melding per 24 uur, ook als de bot al bij het opstarten crasht.

### Voor alle soorten

12. **De regel `Repeat:`** staat alleen in een melding die een herhaling is:
    - Inrichtingsfout: `Repeat: 3rd alert · failing since 1 Oct 06:27 (96×) · next alert 8 Oct`
    - Storing: `Repeat: 2nd alert · next alert 5 Nov`. Begin en pogingen staan al in `Since:`.
    - Bug: `Repeat: 4× since the last alert (12 Oct 14:02)`
13. **De toestand overleeft een herstart.** Hij staat in `faults.json` (dev: `faults.dev.json`) naast `data.json`, wordt bijgewerkt bij elke wijziging, onder één lock, en is er per host. Erin staan:
    - per open Storing: het begin, het `interaction_id` van de eerste poging, het aantal pogingen, de laatste reden en de laatste melding
    - per Inrichtingsfout: sinds wanneer, hoe vaak, de eerste code en de laatste melding
    - per Bug-handtekening: de laatste melding en hoe vaak hij sindsdien voorkwam
    - de lijst `Not sent meanwhile`: alleen soort, dienst en code, niet de melding zelf
14. **Logregels**: elke keer dat een Fout voorkomt, krijgt hij een regel. De regel is volledig bij de eerste keer en bij elke keer dat er een admin-melding uitgaat. Daartussen is hij kort: dezelfde vaste velden met `repeat: n`, zonder `exc`, response en beslisvelden. Dat geldt ook voor pogingen buiten een Interactie. Bij een Storing van de heartbeat (elke 5 seconden) zijn dat zo'n 17.000 korte regels per etmaal.
15. **Geen noodrem** op het aantal meldingen, en geen bundeling. Hebben na een wijziging in Sonarr ineens 30 series geen pad, dan komen er 30 meldingen.

---

## 10. Admin-melding bij een Fout

Bronnen: 10 en 13. Prototype: branch `prototype/admin-melding-bij-fout` (commit `6314f9c`), bestand `src/prototype_admin_melding.html`, variant E.

1. **Opbouw**:
   - **In beeld**:
     - een kop met emoji, soort en wat er misging (`what` van de Fault)
     - `Reason:` (de reden van de dienst, afgekapt op 300 tekens, met de HTTP-status) of `Exception:`
     - wie: `User:`, `Visitor:` of `Job:`
     - `Media:` met titel en jaar
     - bij een Storing: `Since:` met de tijd, het aantal mislukte pogingen en de laatste reden
     - bij een Bug buiten de wrapper: "Caught by error_handler, outside the wrapper"
     - bij melden en doorwerken: `Continued:`
     - bij een herhaling: `Repeat:`
   - **In een uitklapbaar blok** (`<blockquote expandable>`), in deze volgorde, en alleen als er iets in staat:
     1. de velden waarop de beslissing viel
     2. de eigen code
     3. het tmdb- of tvdb-ID
     4. `user_id`
     5. `user told: yes/no`
   - **Laatste regel**: `Code: <code>k7p2qx</code>`, als inline code.
2. **Traceback**: in de melding staat alleen de eigen code, met de binnenste frame bovenaan, plus de exceptie in de regel `Exception:`. Frames van libraries blijven weg. Staat er geen enkele eigen frame in de traceback, dan komen de laatste 3 frames erin. De volledige traceback staat in `exc` in de logregel.
3. **De Code**:
   - Bij een Storing: `Code: m4t9cw (first failed attempt)`.
   - Bij een Herstelmelding: `Code: m4t9cw → r8h3ze`.
   - Geen hashtags.
4. **Taal en koppen**: Engels. De soorten heten in de kop zoals `fault`, met een hoofdletter:
   - 🐞 **Bug**
   - 🌩 **Disruption**
   - 🔧 **Setup**
   - ✅ **Restored**: Herstelmelding na een Storing
   - ✅ **Fixed**: Herstelmelding na een rechtgezette Inrichtingsfout
5. **Opmaak**: HTML, met escapen van alleen `< > &` in elke waarde.
6. **Telegram weigert de melding**: de bot stuurt dezelfde tekst één keer opnieuw zonder `parse_mode`. De tags zijn eruit, de entities zijn teruggezet en bovenaan staat `⚠️ Telegram rejected the formatting: <reden>`. De weigering zelf is een Bug: hij krijgt een ERROR-regel met `fault: bug` en hetzelfde `interaction_id`, maar geen eigen melding. Mislukt ook de platte tekst, dan blijft het bij de logregel.
7. **Lengte**: altijd één bericht van hooguit 4096 tekens. Wordt een melding te lang, dan kort de bot het blok van achteren in en sluit hij af met `… truncated, see log`.
8. **Storing**: getroffen Gebruikers of jobs komen er niet in; `jq` op `service` en `fault` vindt ze in het log.
9. **Herstelmelding (`Restored`)**: toont begin en eind, de duur, het aantal mislukte pogingen en beide codes.
10. **Herstelmelding (`Fixed`)**: toont wat rechtgezet is, van wanneer tot wanneer het misging, hoe vaak, en de code van de eerste melding → de code van de Interactie waarin de controle slaagde.
11. **Na een Telegram-storing**: één Herstelmelding met begin en eind, de duur, het aantal mislukte polls, en een lijst `Not sent meanwhile (N):` met soort, dienst en code van elke Fout waarvan de melding niet aankwam. Hooguit 10, de rest als `+N more`. Herstelmeldingen staan er niet in. Hij heeft geen code, omdat pollen buiten een Interactie valt.
12. **Geluid**: een melding over een Bug, Storing of Inrichtingsfout komt met geluid, ook een Herinnering. Een Herstelmelding komt stil binnen (`disable_notification`). Uitzondering: de Herstelmelding na een Telegram-storing komt met geluid als de lijst `Not sent meanwhile` niet leeg is.
13. **Link**: als de dienst Sonarr of Radarr is en het item daar bestaat, is de titel op de regel `Media:` een link naar dat item.

Voorbeelden:

```html
🐞 <b>Bug</b> · Radarr refused the movie request
Reason: <i>This movie has already been added</i> (HTTP 400)
User: anna
Media: <a href="https://radarr…/movie/693134">Dune: Part Two (2024)</a>
<blockquote expandable><code>src/services/arr.py:98 in post
src/services/radarr.py:31 in add_movie
src/commands/movie.py:84 in start_download
src/commands/media.py:242 in media_choice</code>
tmdb 693134
user_id: 123456789
user told: yes</blockquote>
Code: <code>k7p2qx</code>
```

```
🌩 Disruption · Radarr is not responding
Reason: Unable to communicate with RadarrAPI (HTTP 503)
Since: 05:02, 14 failed attempts
Code: m4t9cw (first failed attempt)

🌩 Disruption · Radarr is not responding
Reason: ClientConnectorDNSError
Since: 1 Nov 17:37, 412 failed attempts
Repeat: 2nd alert · next alert 5 Nov
Code: m4t9cw (first failed attempt)

✅ Restored · Radarr is responding again
Down: 05:02 – 06:07 (1 h 5 min), 23 failed attempts
Code: m4t9cw → r8h3ze

✅ Fixed · Carrie now has a path in Sonarr
Failing: 1 Oct 06:27 – 3 Nov 10:15 (33 days), 1,544×
Code: a3k9pw → t6n2rd
```

---

## 11. `/log`

Bron: 11.

### Wie en waar

1. **Alleen de Beheerder, alleen privé.** `/log` werkt alleen voor `allowed_users` (`CHAT_ID_ADMIN`) en alleen in de privéchat met de bot. In de groep, of van iemand anders, komt er geen reactie, maar een regel `ignored`. Gewone gebruikers zien `/log` niet in hun commandlijst.
2. **Altijd beschikbaar.** `/log` is een losse handler, net als `/help`, en geen entry point van de ConversationHandler. Het werkt dus ook midden in een eigen Gesprek, zonder dat Gesprek af te breken.

### Argument

3. **`/log <accountnaam | user ID | code>`**, herkend in deze volgorde:
   - alleen cijfers: een user ID
   - een accountnaam, hoofdletterongevoelig
   - de vorm van een code (6 tekens uit het alfabet van de Code): een `interaction_id`

   Lijkt een accountnaam op een code (bijvoorbeeld "sander"), dan wint de accountnaam. Zoeken op Telegram-naam kan niet. Zonder argument toont `/log` een korte gebruiksuitleg.
4. **Accountnaam**: alle regels waarin `account` die naam is, plus de regels van elk user ID dat de gebruikerslijst aan die naam koppelt. Zo komen ook de acties mee die iemand als Bezoeker deed, vóór het inloggen. Staat de naam niet (meer) in de gebruikerslijst, dan zoekt `/log` toch op het veld `account`.
5. **User ID**: alle regels met dat `user_id`, zowel als Bezoeker als als Gebruiker.

### Inhoud

6. **Bij een persoon** toont `/log` alles van INFO en hoger met zijn user ID, behalve regels van libraries:
   - Gebruikersacties en `conversation_expired`
   - Fouten in zijn Interacties, kort: soort, dienst en reden, met de code
   - `admin_message_sent`, zodat je ziet dat de Beheerder een melding kreeg
   - Gebruikersberichten aan hem (`user_message`)
7. **Bij een code** toont `/log` alle regels van die Interactie uit het hoofdbestand (INFO en hoger), ook die van libraries, want dan wil je de hele aanloop zien. De kop noemt de persoon of de job. De traceback staat er niet in, `exc_type` wel. Onderaan staat dat de traceback via SSH te vinden is met `grep k7p2qx`. `/log` zoekt terug door de bestanden tot de code gevonden is.
8. **Eén bericht per keer**: de meest recente regels die in één Telegram-bericht passen, ook over meerdere dagbestanden heen. Er is geen datumargument.
9. **Bladeren** gaat met de knoppen "⬅️ Earlier" en "Later ➡️", die het bericht ter plekke vervangen. De positie (datum van het bestand plus byte-offset) zit in de knop zelf, dus een knop blijft ook na een herstart werken. Alleen `allowed_users` kunnen hem indrukken.

### Opmaak

10. HTML en Engels:
    - Een kop met wie het is: de accountnaam, of bij een Bezoeker het user ID plus de Telegram-naam. Bij een code de persoon of de job.
    - Regels gegroepeerd per dag ("Mon 7 Dec"), de oudste bovenaan, elke regel als `<b>14:05</b> msg`. `event` blijft weg, want `msg` zegt het al.
    - Op regels van een Fout staat de code als `<code>k7p2qx</code>`, met één tik te kopiëren. Andere regels hebben geen code.
    - Bij een gedeeld account: komt er op de pagina meer dan één user ID voor, dan staat voor elke regel de Telegram-naam uit de gebruikerslijst, en zegt de kop welk user ID bij welke naam hoort.
    - Een regel van meer dan 200 tekens wordt afgekapt met "…".
    - `msg` wordt HTML-geëscapet. Weigert Telegram het bericht toch, dan gaat het opnieuw als platte tekst.
    - Onderaan staat "Logs on `<host>` since <datum van het oudste `.jsonl`-bestand>".
11. **Niets gevonden**:
    - een persoon zonder regels: "No log lines for wouter on `<host>` since …"
    - een code die niet voorkomt: "Code k7p2qx not found on `<host>`"
    - geen getal, geen accountnaam (ook niet in de logs) en niet de vorm van een code: "Unknown user or code: x"

Een schets; de teksten van `msg` zijn alleen een voorbeeld:

```
📋 wouter

Mon 7 Dec
14:05 command /start
14:05 menu choice: movie request
14:06 searched 'dune' for movie: 7 results
14:06 chose option 3: Dune (2021): already added
⚠️ 14:06 Bug · radarr: This movie has already been added  k7p2qx
14:06 admin message sent: bug
Tue 8 Dec
09:12 user message: online, Dune (2021)

Logs on thuisserver since 2026-12-01
[⬅️ Earlier]
```

### Lezen

12. De lezer leest de dagbestanden binair en achterwaarts in blokken, doet eerst een goedkope substring-check en pas daarna `json.loads`, alles in `asyncio.to_thread`. Een halve laatste regel die de bot nog aan het schrijven is, slaat hij over.

---

## 12. Code: modules en interfaces

Bronnen: 14 en 15, met 01, 09 en 12.

### Logregels schrijven

1. **Een logger per module, met velden als keywords.** Een module maakt `log = get_logger(__name__)` aan en schrijft `log.info("searched 'dune' for movie: 7 results", event="search_term", query="dune", media_type="movie", results=7)`.
   - `media=` vult `media_title`, `media_year` en `tmdb_id` in één keer.
   - Het is synchroon, dus zonder `await`.
   - Alle loggers van de bot hangen onder één naam. Zo herkent de setup eigen code.
   - `logger` en `src` zijn die van de aanroeper.

   Er komt geen functie per soort uit de catalogus.
2. **`Log` gaat niet meer door de constructors.** Op de plek van de parameter `logger` komt `faults` (de meldfunctie), waar die nodig is. Overal anders verdwijnt de parameter. Een test geeft een nep-meldfunctie mee. Er komt geen object op moduleniveau.

### De Fault

3. **`Fault`**, met `kind` = `FaultKind.BUG | DISRUPTION | SETUP`. In tickets en gesprekken blijven het Fout, Bug, Storing en Inrichtingsfout.
4. **Velden**:
   - `kind` en `service`
   - `what`: wat er misging, voor de kop van de melding ("Radarr refused the movie request")
   - `reason`: de reden van de dienst of de exceptie
   - `http_status` bij een HTTP-antwoord
   - alleen bij een Inrichtingsfout `check` en `item`. `check` zegt welke controle mislukte, bijvoorbeeld `series_path`, `tmdb_lookup`, `setting` of `disk_space`. `item` is het tmdb/tvdb-ID of de naam van de instelling. Met `service` vormen ze de sleutel uit [hoofdstuk 9](#9-afremmen-en-toestand).
   - `details`: de velden waarop de beslissing viel
   - `media`
   - `user_text`: een optionele Nederlandse zin voor de Foutmelding
   - de oorspronkelijke exceptie, via `raise Fault(...) from e`
5. **Drie constructors**: `Fault.bug(...)`, `Fault.disruption(...)` en `Fault.setup(...)`. Elke constructor neemt alleen de velden van zijn soort, dus een `Fault.setup` zonder `check` kan niet.
6. **Elke request krijgt een omschrijving mee**: `await self.post("/movie", payload, action="movie request")`. De requestregel maakt daar "Radarr refused the movie request" of "Radarr is not responding" van.
7. **Het media-item komt uit de context.** `working_on(media)` zet het item in de context van de Interactie. De meldfunctie neemt het daaruit over als de Fault zelf geen `media` heeft. Een job met een lus zet het per item.

### De meldfunctie

8. **`await faults.report(fault, user_told=False, continued=None) -> bool`**:
   - Hij schrijft de logregel van de Fout: volledig, of kort met `repeat: n`. `src` is de binnenste eigen frame van de exceptie, of de aanroeper als er geen exceptie is.
   - Hij beslist via `faults.json`: een melding, een Herinnering of niets.
   - Hij verstuurt via de verzendfunctie en houdt `Not sent meanwhile` bij.
   - Hij geeft `True` terug als de Beheerder van deze Fout weet: er ging nu een melding uit, of al eerder binnen de afremming.
   - `user told: yes` in de melding betekent "de wrapper gaat het de Gebruiker vertellen".
9. **Een controle die slaagt**:
   - **Storing**: `await faults.ok(service)` bij elk geslaagd antwoord. Die aanroep zit in de requestregel en in `TelegramRequest`, dus geen dienst roept hem zelf aan. Als er geen Storing openstaat, kost hij bijna niets.
   - **Inrichtingsfout**: `await faults.fixed(service, check, item, msg="Carrie now has a path in Sonarr")`, aangeroepen door de code die de controle doet, als die slaagt. Staat er niets open, of ging er nooit een melding uit, dan ruimt hij alleen de toestand op.
10. **Crash: `faults.report_crash(exc)`**, aangeroepen door de `sys.excepthook`. Die hook wordt geïnstalleerd zodra de meldfunctie bestaat.
    - Een `NetworkError` of `TimedOut` van Telegram wordt een Storing. Al het andere wordt een Bug.
    - Daarna draait dezelfde async `report()` in een nieuwe event loop (`asyncio.run`), met een nieuwe `Bot` en een timeout van 5 seconden. Zo is er één codepad voor beslissen, opmaken en versturen.
    - Bij een Storing van Telegram telt `report()` alleen de poging en verstuurt hij niets.

### Telegram

11. **Eén verzendfunctie: `await send(chat_id, text, fmt, silent=False)`**:
    - Hij maskeert met `mask()`, kapt af op 4096 tekens, en als Telegram de opmaak weigert, verstuurt hij het bericht één keer opnieuw als platte tekst met de regel ⚠️. De weigering schrijft hij als ERROR-regel met `fault: bug`, zonder eigen melding.
    - `NetworkError`, `TimedOut` en `RetryAfter` zet hij om in een Fault van Telegram (Storing).
    - `Forbidden` ("bot was blocked by the user") geeft hij terug als "niet afgeleverd", met de reden. Dat is geen Fault.
    - Hij wordt gebruikt door de meldfunctie, `send_admin_message`, `send_user_message` en de Foutmelding van de wrapper.
    - Gewone antwoorden in een Gesprek (`Functions.send_message`) blijven erbuiten. Een `NetworkError` daar valt door naar de wrapper.
12. **`send_admin_message(text)`** voor andere berichten aan de Beheerder: zie [hoofdstuk 6](#6-gebruikersberichten-en-andere-berichten-aan-de-beheerder).
13. **`await send_user_message(user_id, kind, text, media=None)`** verstuurt een Gebruikersbericht en schrijft de regel `user_message`.
    - Hij zoekt de accountnaam van de ontvanger op.
    - Hij schrijft INFO, of WARNING met `reason` als het bericht niet aankomt, en telt `sent` of `not_delivered`.
    - Een Fault van Telegram laat hij doorvallen naar de wrapper. Een Storing beëindigt dan de run.
14. **`TelegramRequest`**, een eigen subklasse van `HTTPXRequest`, ingesteld via `ApplicationBuilder.request()` en `.get_updates_request()`.
    - Bij elk geslaagd antwoord roept hij `faults.ok("telegram")` aan, ook bij het pollen. Zo komt de Herstelmelding na een storing in de nacht meteen, en niet pas bij het eerstvolgende bericht.
    - `getUpdates` krijgt geen `http_call`.
    - Mislukte pogingen telt hij niet, want PTB moet zijn eigen excepties blijven zien om opnieuw te proberen. Die worden geteld waar ze opduiken: in `error_handler` (pollen), in de wrapper (een antwoord in een handler) en in de verzendfunctie.

### De requestregel

15. **`await call(service, action, attempt, retries=3)`** handelt het hele verloop van een request naar een dienst af.
    - Per poging schrijft hij een `http_call` op DEBUG.
    - Hij zet een antwoord of exceptie om volgens de tabel in [hoofdstuk 8](#indeling).
    - Bij een Storing probeert hij het opnieuw, en pas na de laatste poging gooit hij de Fault. Dat is één mislukte poging.
    - Bij succes roept hij `faults.ok(service)` aan.

    De client geeft alleen mee hoe hij één poging doet. Daar komen de status, de body en de reden uit, of bij plexapi en transmission-rpc de omzetting van hun excepties. Radarr en Sonarr houden 3 pogingen, de andere diensten 1, zoals nu.

### De Interactie en de wrappers

16. **`InteractionProcessor`** zet per update `interaction_id`, `user_id` en `account` of `tg_name` ([hoofdstuk 2](#2-interacties-en-codes)). Bij de start krijgt hij `account_for(user_id)` mee, die de gebruikerslijst in `data.json` leest.
17. **`guard(callback)`** komt om elke handler-callback en geeft na een Fout altijd `ConversationHandler.END` terug. Er is één variant voor alles, ook voor losse handlers zoals `/help` en `/log`, want daar negeert PTB de teruggegeven waarde.
18. **`guard_job(callback)`** zet per run een nieuwe context (`interaction_id` en `job`), stuurt geen Foutmelding, en schrijft in een `finally` de regel `job_finished` met de tellingen uit `tally`.
19. **`guard_task(coro_fn)`** is voor de heartbeat. Een exceptie is een Bug buiten een Interactie, met een eigen Code. Daarna start de wrapper de heartbeat na 60 seconden opnieuw. Stopt de heartbeat, dan denkt de watcher na een tijd dat de thuisserver uit de lucht is, en start hij de fallback-bot; dan pollen er twee bots. Een Bug die terugkomt, geeft door de afremming hooguit één melding per 24 uur.
20. **`working_on(media)`**, **`tally(name, n=1)`** en **`current_code()`** lezen en schrijven de context van de huidige Interactie.

### Modules

Elke module heeft eigen tests, behalve `src/log/files.py`.

| Module | Bestand | Interface | Wat erin zit |
|---|---|---|---|
| Logregels | `src/log/__init__.py` (vervangt `src/log.py`) | `setup_logging(env, level, folder, verbose)`, `get_logger(name)`, `mask(text)` | JSON-formatter met de velden, een handler per dagbestand en het debug-bestand, de console, de filters voor context, maskeren en eigen code tegenover libraries, `captureWarnings` |
| Bestandsnamen | `src/log/files.py` (intern) | naam per dag, lijst van dagbestanden | gedeeld door de dagbestand-handler en de lezer |
| Loglezer | `src/log/search.py` | `search(query, before=None)`: regels van nieuw naar oud, elk met een positie (datum van het bestand plus byte-offset). `query` is een set user ID's plus een accountnaam, of een Code | achterwaarts lezen, eerst een substring-check, in `asyncio.to_thread` |
| Meldfunctie | `src/faults.py` | `Fault`, `FaultKind`, `FaultReporter.report / ok / fixed / report_crash`, plus het installeren van de excepthook | de toestand in `faults.json` onder één lock (jobs en updates lopen door elkaar op dezelfde loop), de beslisregels van [hoofdstuk 8](#8-fouten) en [9](#9-afremmen-en-toestand), de HTML-opmaak van [hoofdstuk 10](#10-admin-melding-bij-een-fout), `Not sent meanwhile`, `bot_crashed` |
| Verzendfunctie | `src/telegram_out.py` | `send`, `send_user_message`, `send_admin_message`, `TelegramRequest` | maskeren, de terugval op platte tekst, omzetten van Telegram-excepties, `user_message` en `admin_message_sent` |
| Interactie | `src/interaction.py` | `InteractionProcessor`, `guard`, `guard_job`, `guard_task`, `working_on`, `tally`, `current_code()` | de contextvars, het samenstellen van de Foutmelding, `job_finished`, het herstarten van de heartbeat |
| Requestregel | `src/services/request.py` | `call(service, action, attempt, retries)` | de indeling van antwoorden, opnieuw proberen, `http_call`, `ok` |
| `/log` | `src/commands/log.py` | het command en de handler voor de knoppen | het argument herkennen, de HTML-pagina bouwen, bladeren. De positie van de laatste regel gaat in de knop |

### Wat verdwijnt

- de klasse `Log` met `logger`, `debug_call`, `send_telegram_message`, `clean_message`, `truncate` en `NoLibraryChatter`
- `NOISY_LOGGERS`
- `last_error` in de diensten
- `_lookup_failures`, `_missing_path` en `LOOKUP_ALERT_THRESHOLD`
- de bestandsnaam met de startdatum en `Path(log_file).touch()` in `src/log.py`
- de Transmission-check in `check_notify_list` en zijn `try/except: pass`

### Tests

Met `unittest`, net als `tests/test_movie_states.py`, dus zonder nieuwe dependency. Elke module wordt getest via zijn eigen interface, met nepversies voor de verzendfunctie, de klok, de PTB-bot en een tijdelijke map. De belangrijkste gevallen:

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
  - `job_finished` na een geslaagde run en na een stop, met de tellingen tot dan
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

---

## 13. Buiten de code

- **README**:
  - de `jq`-regel en `tail -F` op het bestand van vandaag
  - de nieuwe bestandsnamen en het debug-bestand (`…-JJJJ-MM-DD-debug.jsonl` in plaats van `<name>-<date>-debug.log`)
  - `LOG_TYPE` met alleen `INFO` en `DEBUG`
  - in de Syncthing-paragraaf `faults.json` en `faults.dev.json` bij de aanbevolen `.stignore`-patronen: de toestand is er per host (zie Feiten)
- **`dot-env.template`**: `LOG_TYPE` met twee waarden, en `LOOKUP_ALERT_THRESHOLD` eruit.
- **`.gitignore`**: `faults.json` en `faults.dev.json` erbij, naast `data.json`.
- **De systemd-units** starten zonder `--verbose`; daar verandert niets.

---

## 14. Feiten uit de code

Nagekeken tijdens de tickets. Regelnummers zijn van 2026-11-03.

**Logging nu**

- Eigen regels lopen via `Log.log_to_file()` in `src/log.py`, dat `logging.error()` en dergelijke direct aanroept. Daardoor is `logger` altijd `root` en wijst de codeplek altijd naar `src/log.py`.
- `Log.logger()` escapet de tekst voor MarkdownV2 en schrijft die geëscapete tekst ook naar het bestand (bijvoorbeeld `Notify: New episode\(s\)`).
- Een traceback met `traceback.format_exc()` in de tekst, ook bij timeouts: `src/services/arr.py:114`, `:121`, `:174`, `:181`, `src/services/plex.py:54`, `:100`, `:126`, `src/services/transmission.py:59`, `src/commands/media.py:489`, `src/bot.py:533`.
- Live gaan admin-meldingen naar `CHAT_ID_GROUP`, in dev naar `CHAT_ID_ADMIN` (`src/log.py:100`). `notify_admin_startup` stuurt ook in dev naar `CHAT_ID_GROUP` (`src/bot.py:288`).
- Via de kopie van de admin-meldingen staan e-mail en telefoon uit accountaanvragen nu in de logbestanden (`src/commands/account.py:89`).
- Nu niet gelogd: algemene updates aan/uit (`src/commands/message.py:51`), foute wachtwoordpogingen 1 en 2 (`src/commands/start.py:166`) en de zoekterm (`src/commands/media.py:60`).
- De afmeldmelding gebruikt `self.log.escape_markdown` (`src/bot.py:376`). Die escape gaat mee naar `send_admin_message`.

**Handlers en Gesprekken**

- `src/bot.py` maakt 82 handlers aan in twee ConversationHandlers (`_build_normal_conversation`, `_build_maintenance_conversation`) en een paar losse `add_handler`s (r. 105-112). De jobs staan op r. 119-126, `error_handler` op r. 504.
- Genegeerde invoer heeft nu geen handler: de ConversationHandler laat die stil vallen (`src/bot.py:153`). Voor `ignored` is een vangnet nodig.
- Er is nog geen handler voor een verlopen Gesprek (geen `ConversationHandler.TIMEOUT`-state).
- De admin-commands zijn nu entry points van de ConversationHandler met `filters.User(self.allowed_users)` (`src/bot.py:162`). Midden in een Gesprek werken ze daardoor niet. `/help` en `/privacy` zijn wel losse handlers (`src/bot.py:110-113`).
- De Foutmeldingen staan nu als losse teksten in de handlers: `src/commands/media.py:422`, `:430`, `src/commands/serie.py:194`, `src/commands/subscribe.py:115`, plus de zin "op de hoogte" in `src/commands/media.py:334`, `:412` en `src/commands/start.py:221`. Ze gaan via `send_message()` in `src/functions.py` (MarkdownV2).
- PTB 21.10: `Application.process_update` wacht op de handler en gooit de teruggegeven waarde weg (`telegram/ext/_application.py:1307-1325`), dus `END` uit een losse handler kan geen kwaad. In een ConversationHandler houdt `None` de huidige state vast.
- Na een exceptie in een blocking state-callback blijft een Gesprek nu in de oude state, terwijl de timeout-job al verwijderd is (01, niet getest). Met `guard`, die altijd `END` teruggeeft, speelt dat niet meer.

**Diensten en Fouten**

- `ArrClient.get()` (`src/services/arr.py:55-125`) vangt alles af, zet `last_error` en geeft `False` terug. Bij één diskspace-fout gaan er nu drie meldingen uit: `src/services/arr.py:195`, `src/commands/media.py:444` en `:413`. Een mislukte Plex-link geeft er twee (`src/services/plex.py:121`, `:125`).
- `src/services/plex.py:46`, `:93`, `:113`, `:119` en `src/services/transmission.py:37`, `:51`, `:102` vangen `Exception` af en loggen zelf.
- De tellers voor herhaling staan nu in het geheugen: `_lookup_failures` (`src/services/arr.py:19`) en `_missing_path` (`src/commands/schedule.py:33`). Na elke herstart beginnen ze opnieuw. `log_missing_path` telt serie 288673 twee keer per run.
- Er is geen eigen TMDB-client. Lookups gaan via Radarr en Sonarr (`/movie/lookup`, SkyHook).
- plexapi en transmission-rpc zijn synchroon en worden direct in async functies aangeroepen. Tijdens zo'n request staat de event loop stil. Dat is geen logging, en de requestregel laat het zoals het is.
- Geheimen: httpx logt op INFO elke request met de volledige URL, en PTB zet het bot-token in die URL. transmission-rpc logt op DEBUG zijn URL met `gebruiker:wachtwoord@` (`transmission_rpc/client.py:120`), en bij een 401 of 403 de headers met Basic auth. Radarr en Sonarr krijgen de apikey via `params` (`src/services/arr.py:55`, `:129`). plexapi maskeert zijn token zelf.

**Geplande taken en de heartbeat**

- De twee `run_once`-jobs starten hun werk met `create_task` in een lambda (`src/bot.py:119-120`). `guard_job` moet om de coroutine zelf, anders valt een exceptie buiten de wrapper.
- `check_notify_list` begint met `check_transmission_and_trigger_scans` (`src/commands/schedule.py:48`). Of Transmission bij de vorige run onbereikbaar was, staat alleen in het geheugen, in `_last_transmission_up` (`src/services/transmission.py:10`). `TransmissionService.is_available` (`:30`) vangt elke exceptie af. Met de requestregel wordt dat een Fault; zet `_last_transmission_up` dan op onbereikbaar voordat de Fault doorvalt.
- Beide scans heten `scan_missing_media` (`src/services/sonarr.py:45`, `src/services/radarr.py:45`).
- Per Gebruikersbericht schrijft `check_notify_list` nu een regel en stuurt het een admin-melding "User notified" (`src/commands/schedule.py:120`, `:187`, `:241`). `check_requirements` (`:305`) slaat een item zonder data (`:311`) of zonder map (`:329`) over, zonder regel.
- De heartbeat (`_heartbeat_loop`, `src/bot.py:424`, gestart met `asyncio.create_task` op r. 317) draait live elke 5 seconden en vangt alleen `OSError` en `asyncio.TimeoutError` af. Bij elke andere exceptie stopt hij zonder regel, en `_post_stop` slikt die exceptie in.

**Start, pollen en crashes**

- `Application.initialize()` roept `get_me` aan. `run_polling` vangt alleen `KeyboardInterrupt` en `SystemExit` af, dus een `NetworkError` bij de start valt uit `main()` naar stderr. systemd herstart de bot na 10 seconden (`files/plex-download-bot.service`).
- `run_polling` sluit bij het stoppen zijn event loop (`close_loop=True`). Daarom heeft `report_crash` een nieuwe loop nodig.
- Bij het pollen vangt PTB `RetryAfter` zelf af (INFO "Flood control exceeded"), net als `TimedOut` (DEBUG, meteen opnieuw). Elke andere `TelegramError` gaat naar `error_handler`. De wachttijd tussen de pogingen loopt op van 1 tot 30 seconden.
- De volgorde bij de start is een kringetje: de meldfunctie heeft de verzendfunctie nodig, de verzendfunctie de `Bot`, en die `Bot` wordt gebouwd met `TelegramRequest`, die `faults.ok` aanroept. Een van de drie krijgt zijn partner pas na het aanmaken.
- `HTTPXRequest.do_request` (`telegram/request/_httpxrequest.py:256`) en `ApplicationBuilder.request()` en `.get_updates_request()` (`telegram/ext/_applicationbuilder.py:468`, `:701`) bestaan in PTB 21.10.0.

**Opslag**

- De bot bewaart zijn toestand al in `data.json` en `stats.json` in de werkmap, met `.dev`-varianten (`src/commands/media.py:37`). De gebruikerslijst staat in `data.json` onder `user_id`, als "accountnaam, Telegram-naam" (19 accounts en 24 user ID's in oktober).
- De README raadt aan om de hele botmap via Syncthing te delen, met `log/` in `.stignore`. Zonder extra patroon gaat `faults.json` dan mee naar de fallback-host, terwijl de toestand per host hoort.
- `callback_data` is maximaal 64 bytes. Dat is genoeg voor het argument van `/log` plus een positie.

### Na te kijken bij de implementatie

- De vorm van de link naar Sonarr en Radarr in de admin-melding: waarschijnlijk `/movie/<tmdbId>` en `/series/<titleSlug>`.
- Dat jobs de contextvars niet betrouwbaar erven, is afgeleid uit de broncode van APScheduler 3.11.2, niet getest (01). `guard_job` zet de context daarom zelf.
- De codeschetsen uit het onderzoek naar structured logging (02) zijn niet uitgevoerd.

---

## 15. Implementatie

Opgeknipt in vijftien issues in [implementatie/](implementatie/index.md), met de volgorde, de afhankelijkheden en de issues die dezelfde bestanden raken. Na elke issue werkt de bot nog: issue 01 laat de klasse `Log` tijdelijk bestaan als dunne laag op de nieuwe logging, en issue 15 haalt die weg.

---

## Buiten scope

Van de map:

- Admin-meldingen die geen fout zijn (accountaanvraag, kwaliteitsverzoek, vraag via /help, aanvraag voor iets dat unmonitored staat, en overige meldingen over gebruikersacties): hun inhoud blijft ongewijzigd.
- Overzichten en statistieken over gebruik: alleen terugzoeken is nodig.
- Live meekijken met gebruikersacties via Telegram.
- Extra infrastructuur of externe diensten (Loki/Grafana, Seq, Sentry e.d.).
- Bewaartermijnen en afstemming met de privacy policy: de retentie blijft zoals nu. Daaronder valt ook de FAQ-zin dat berichten aan de bot "niet opgeslagen of gelezen" worden (`src/commands/help.py:141`), die na deze spec niet meer klopt.
- Het watcher-script (`files/plex-download-bot-watcher.py`).
- De bugfix voor "al toegevoegd" (de bot biedt een film aan die al in Radarr staat).
- Een lookup met de tekst `serie_request` als TMDB ID op 01-10: de `callback_data` van de knop 📺 Serie.

---

## Bronnen

| # | Ticket | Type |
|---|---|---|
| 01 | [Hoe onderschep je in python-telegram-bot 21 elke update centraal en geef je context door?](issues/01-ptb-update-context.md) | research |
| 02 | [Welke opties heeft Python voor gestructureerde logregels en dagelijkse rotatie?](issues/02-python-structured-logging.md) | research |
| 03 | [Recente live-logs van de thuisserver ophalen](issues/03-live-logs-ophalen.md) | task |
| 04 | [Welke gebruikersacties leggen we vast, en met welke gegevens?](issues/04-gebruikersacties-vastleggen.md) | grilling |
| 05 | [Welke fouten worden een admin-melding, en welke alleen een logregel?](issues/05-welke-fouten-admin-melding.md) | grilling |
| 06 | [Welk formaat en welke logniveaus krijgen logregels?](issues/06-logformaat-en-niveaus.md) | grilling |
| 07 | [Hoe worden logbestanden opgeslagen en geroteerd?](issues/07-opslag-en-rotatie.md) | grilling |
| 08 | [Hoe koppelen we logregels van één interactie, en een melding aan de logregel?](issues/08-interactie-id-en-fout-id.md) | grilling |
| 09 | [Waar vangen we excepties af: lokaal of centraal?](issues/09-excepties-lokaal-of-centraal.md) | grilling |
| 10 | [Hoe ziet een admin-melding bij een fout eruit?](issues/10-admin-melding-bij-fout.md) | prototype |
| 11 | [Wat toont /log <gebruiker>, en voor wie?](issues/11-log-command.md) | grilling |
| 12 | [Wat komt er van buiten de eigen code in de logregels?](issues/12-ruis-buiten-eigen-code.md) | grilling |
| 13 | [Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?](issues/13-herhaalde-fouten-afremmen.md) | grilling |
| 14 | [Welke interface krijgt de logmodule?](issues/14-interface-logmodule.md) | grilling |
| 15 | [Welke logregels schrijft een run van een geplande taak?](issues/15-logregels-geplande-taken.md) | grilling |
