# Onderzoek 02: gestructureerde logrecords en dagelijkse rotatie in Python 3.12

- Datum: 2026-11-02
- Vraag: welke opties biedt Python 3.12 voor gestructureerde logrecords met context per interactie (user ID, interaction ID), en voor dagelijkse rotatie in een proces dat wekenlang draait zonder herstart?
- Context: `plex-download-bot`, Python 3.12, python-telegram-bot 21.10 (asyncio), systemd-service als root (`files/plex-download-bot.service`), huidige setup in `src/log.py`.
- Bronnen: alleen primaire bronnen (docs.python.org, CPython-broncode en -issues, structlog-docs/PyPI/GitHub, python-json-logger-docs/GitHub/PyPI, logrotate-manpage en -repo, PTB-broncode v21.10, jq-handleiding, Telegram Bot API). Waar ik zelf iets afleid of ontwerp, staat dat er expliciet bij ("eigen analyse" of "eigen ontwerp"). In deze omgeving was geen Python-interpreter beschikbaar. De codeschetsen hieronder zijn dus **niet uitgevoerd**.

## Antwoord

1. **Context aan records hangen kan volledig met de stdlib**: een module-level `ContextVar` plus een `logging.Filter` op de **handler** (niet op de logger), of `logging.setLogRecordFactory`. Alleen dan krijgen ook records van third-party libraries (`httpx`, `telegram`, `apscheduler`) de user-/interaction-ID mee. `LoggerAdapter` werkt alleen voor aanroepen via de adapter zelf. Een eigen JSON-formatter is een paar regels `json.dumps`.
2. **Valkuil bij PTB 21.10 met `concurrent_updates(False)`**: alle updates draaien na elkaar in **één** asyncio-taak (`update_fetcher`). Een contextvar die in een handler wordt gezet, lekt dan naar de volgende update. Zet en reset de waarde daarom per update, met de `Token` van `ContextVar.set()`. Het gedocumenteerde aanhaakpunt daarvoor is `BaseUpdateProcessor.do_process_update`.
3. **structlog** (26.1.0, juni 2026, actief, MIT/Apache-2.0) heeft de prettigste API en ingebouwde contextvars-ondersteuning. Records van third-party libraries gaan via `ProcessorFormatter` met `foreign_pre_chain`. De docs noemen die integratie zelf "fiddly". Voor deze bot is de meerwaarde ten opzichte van de stdlib klein.
4. **python-json-logger** (4.2.0, aug 2026; actieve fork van nhairs, het origineel `madzak/python-json-logger` is gearchiveerd) is alleen een `Formatter`. Context gaat via hetzelfde filter-patroon. Het is een prima optie als je geen eigen formatter wilt onderhouden. Let op de importpad- en API-breuken tussen 2.x, 3.x en 4.x.
5. **`TimedRotatingFileHandler(when="midnight", backupCount=0)`**: de opschoonstap (`getFilesToDelete` + `os.remove`) draait alleen bij `backupCount > 0`, dus er wordt niets opgeruimd. De naam wordt `<bestand>.JJJJ-MM-DD`, gedateerd op de dag die wordt afgesloten. Bij een herstart bepaalt de **mtime** van het bestaande bestand de eerste rollover. Voor `midnight` geeft dat een correct gedateerde rotatie na de herstart. Let op: de huidige `Path(log_file).touch()` zet die mtime op "nu".
6. **Maar 3.12 heeft bekende rotatiebugs rond zomertijd.** In de herfstnacht (Europe/Amsterdam, laatste zondag van oktober) kan de backupnaam botsen met die van de dag ervoor. Op 3.12.3+ stopt de rotatie dan tot de volgende herstart (gh-159690/gh-160433). Op 3.12.0–3.12.2 werd de bestaande backup zelfs overschreven (gh-88352). De fixes staan alleen op main/3.14/3.15, en 3.12 krijgt alleen nog security-fixes. `utc=True` omzeilt dit, maar dan valt de dagscheiding om 01:00/02:00 lokale tijd.
7. **`WatchedFileHandler` + `logrotate`** is robuust en extern, maar standaard **verwijdert** logrotate oude versies (`rotate` default 0). Voor "nooit automatisch verwijderen" heb je `rotate -1` nodig, zonder `maxage`. De upstream-timer draait `daily` met `RandomizedDelaySec=1h`, dus de dagscheiding valt ergens tussen 00:00 en 01:00. Je hebt ook systeemconfig buiten de repo nodig.
8. **Beste fit voor de randvoorwaarden (eigen oordeel)**: een eigen handler van circa 20 regels die direct naar `<prefix>-JJJJ-MM-DD.jsonl` schrijft op basis van `record.created`. Die hernoemt en verwijdert nooit iets. Er is geen mtime- of DST-logica nodig en een herstart betekent gewoon verder appenden. De docs bieden zo'n handler niet aan, het is maatwerk.
9. **Eén bestand voor mens én machine**: JSON Lines (één JSON-object per regel) werkt met `grep` en direct met `jq`, dat whitespace-gescheiden JSON-waarden leest. Multiline-berichten en tracebacks blijven op één regel, waardoor `clean_message()` overbodig wordt. Met `less` leest het minder prettig. Twee formaten via twee handlers (tekst + JSONL) is goed ondersteund en gangbaar: structlog zegt "pretty in dev, JSON in productie" en geeft een voorbeeld met twee formatters. Of één bestand "gebruikelijk" is, daarover zwijgen de docs.
10. **`/log <user>`**: gebruik ISO-datums in de bestandsnamen, zodat sorteren meteen nieuw→oud oplevert. Lees elk bestand **binair achterwaarts** in blokken van circa 64 KiB (`seek` vanaf het einde mag alleen in binaire modus). Doe eerst een goedkope bytes-substring-check en pas daarna `json.loads`, en stop bij N treffers. Draai het geheel in `asyncio.to_thread`, zodat de event loop niet blokkeert. Bij een bestand van 200 MB lees je zo meestal alleen de staart. De output moet binnen 4096 tekens per Telegram-bericht passen.

---

## 1. Uitgangssituatie (`src/log.py`)

Wat de code nu doet (gelezen in de repo):

- De root logger krijgt een `FileHandler` naar `log/<naam>-<%m-%d-%Y>.log`. De datum is de **startdatum** van het proces, dus een proces dat weken draait schrijft weken in hetzelfde "dag"-bestand.
- Op DEBUG komt er een tweede bestand `...-debug.log` bij, met al het library-geruis. Het hoofdbestand filtert dat geruis eruit met `NoLibraryChatter`, een **handler**-filter.
- Berichten gaan via `Log.logger()`, dat `clean_message()` aanroept. Die verwijdert alle niet-ASCII-tekens en vervangt newlines door `" - "`, zodat één record één regel blijft.
- Het bestand wordt bij de start aangemaakt met `Path(log_file).touch(exist_ok=True)`.
- De datumnotatie `%m-%d-%Y` sorteert niet lexicografisch op tijd. logrotate waarschuwt om dezelfde reden dat datumstempels "lexically sortable" moeten zijn (<https://github.com/logrotate/logrotate/blob/main/logrotate.8.in>, optie `dateformat`).

## 2. Context per interactie aan logrecords hangen

### 2.1 Mechanismen in de stdlib (Python 3.12)

| Mechanisme | Wat het doet | Raakt het records van third-party loggers? | Bron |
|---|---|---|---|
| `extra={...}` per aanroep | Vult `LogRecord.__dict__` met eigen attributen | Nee, alleen de aanroepen waar je het meegeeft | <https://docs.python.org/3.12/library/logging.html#logging.Logger.debug> |
| `LoggerAdapter(logger, extra)` | Voegt `extra` toe via `process()` bij elke aanroep **op de adapter** | Nee. Third-party code gebruikt zijn eigen `getLogger()` | <https://docs.python.org/3.12/library/logging.html#loggeradapter-objects> |
| `Filter` op een **logger** | Wordt geraadpleegd als op díe logger gelogd wordt | **Nee**. Records van onderliggende loggers passeren een logger-filter niet | <https://docs.python.org/3.12/library/logging.html#filter-objects> |
| `Filter` op een **handler** | Ziet elk record dat de handler bereikt, ook doorgepropageerde records | **Ja** | idem + cookbook-voorbeeld hieronder |
| `setLogRecordFactory()` | Draait bij het **aanmaken** van elk record, globaal | **Ja** | <https://docs.python.org/3.12/library/logging.html#logging.setLogRecordFactory> |

Relevante details:

- **Logger-filters versus handler-filters.** De logging-docs zeggen letterlijk dat records van onderliggende loggers niet door het filter van een logger gaan, "unless the filter has also been applied to those descendant loggers" (<https://docs.python.org/3.12/library/logging.html#filter-objects>). Voor `httpx`, `telegram` en dergelijke moet het filter dus op de handler staan, of je gebruikt de record factory.
- **Cookbook "Use of contextvars".** Dit is precies het patroon: een `ContextVar` per stukje context en een `InjectingFilter` die met `handler.addFilter(f)` op de **handler** wordt gezet. De voorbeeldoutput laat zien dat ook records van de "library" (`webapplib`) de context meekrijgen (<https://docs.python.org/3.12/howto/logging-cookbook.html#use-of-contextvars>).
- **Nieuw in 3.12: een filter mag een nieuw `LogRecord` teruggeven** in plaats van het record in-place te wijzigen. Daarmee kan een handler-filter context toevoegen zonder dat andere handlers het zien (<https://docs.python.org/3.12/library/logging.html#filter-objects>, "Changed in version 3.12"; cookbook-recept <https://docs.python.org/3.12/howto/logging-cookbook.html#imparting-contextual-information-in-handlers>).
- **`LoggerAdapter` in 3.12 negeert de `extra` van de individuele aanroep.** Die wordt "silently overwritten" (<https://docs.python.org/3.12/howto/logging-cookbook.html#using-loggeradapters-to-impart-contextual-information>). De parameter `merge_extra` bestaat pas sinds **3.13** (<https://docs.python.org/3.13/library/logging.html#logging.LoggerAdapter>).
- **Record factory.** De docs geven het patroon `old_factory = logging.getLogRecordFactory()` met chaining. Dat werkt goed zolang factories elkaars attributen niet overschrijven (<https://docs.python.org/3.12/library/logging.html#logrecord-objects>).
- **`taskName` is nieuw in 3.12**: een LogRecord-attribuut met de naam van de `asyncio.Task` (<https://docs.python.org/3.12/library/logging.html#logrecord-attributes>). Bij deze bot is dat **geen** vervanging voor een interaction ID. Met `concurrent_updates(False)` draait alle handlercode in één taak met de vaste naam `Application:<bot_id>:update_fetcher` (<https://github.com/python-telegram-bot/python-telegram-bot/blob/v21.10/telegram/ext/_application.py>).
- **Ontbrekende attributen in een tekst-`Formatter`.** Als een formatstring `%(user_id)s` verwacht en het attribuut ontbreekt, wordt het record niet gelogd (<https://docs.python.org/3.12/library/logging.html#logging.Logger.debug>, uitleg bij `extra`). Een handler-filter dat het attribuut altijd zet (bijv. `"-"` als default) voorkomt dat. Een alternatief is de `defaults=`-parameter van `logging.Formatter` (<https://docs.python.org/3.12/library/logging.html#logging.Formatter>).

### 2.2 `contextvars` en asyncio

- `ContextVar`s worden "natively supported in asyncio" (<https://docs.python.org/3.12/library/contextvars.html#asyncio-support>).
- `asyncio.create_task()` draait de coroutine in een **kopie** van de huidige context als je geen `context=` meegeeft (<https://docs.python.org/3.12/library/asyncio-task.html#asyncio.create_task>). Waarden die vóór `create_task` zijn gezet, erft de nieuwe taak dus. Wijzigingen ín de taak lekken niet terug.
- `asyncio.to_thread()` propageert de huidige context naar de thread (<https://docs.python.org/3.12/library/asyncio-task.html#asyncio.to_thread>).
- Elke OS-thread heeft een eigen top-level `Context` (<https://docs.python.org/3.12/library/contextvars.html#manual-context-management>). Code in een `QueueListener`-thread ziet de contextvars van de loggende taak dus **niet** (zie 2.6).
- `ContextVar.set()` geeft een `Token` terug, en `ContextVar.reset(token)` herstelt de vorige waarde (<https://docs.python.org/3.12/library/contextvars.html#contextvars.ContextVar.reset>).
- De docs eisen dat context variables "created at the top module level and never in closures" worden (<https://docs.python.org/3.12/library/contextvars.html#contextvars.ContextVar>).

### 2.3 Specifiek voor python-telegram-bot 21.10

Bron: PTB-broncode op tag `v21.10`, `telegram/ext/_application.py` en `telegram/ext/_baseupdateprocessor.py` (<https://github.com/python-telegram-bot/python-telegram-bot/tree/v21.10/telegram/ext>).

- In `Application.__update_fetcher` wordt een update bij `max_concurrent_updates > 1` in een nieuwe taak verwerkt (`self.create_task(...)`). Anders gebeurt het met `await self.__process_update_wrapper(update)` **in de fetcher-taak zelf**. De bot gebruikt `.concurrent_updates(False)` (`src/bot.py`), dus alle updates draaien sequentieel in één taak en één context.
- **Gevolg (eigen analyse)**: een `user_id` die tijdens update A met `ContextVar.set()` wordt gezet, staat nog steeds in de context als update B (van een andere gebruiker) wordt verwerkt, tenzij je hem reset. Zet de waarde daarom per update en reset hem in een `finally`.
- **Gedocumenteerd aanhaakpunt**: `BaseUpdateProcessor.do_process_update(update, coroutine)` is de abstracte methode voor "custom implementation of how to process an update". `ApplicationBuilder.concurrent_updates()` accepteert naast `bool`/`int` ook een `BaseUpdateProcessor`-instantie. Een subclass met `max_concurrent_updates=1` kan rond `await coroutine` de contextvars zetten en resetten. Zo behoud je het huidige sequentiële gedrag.
- Handlers met `block=False` en `application.create_task(...)` starten nieuwe taken. Die erven de context op het moment van aanmaken (zie 2.2), dus ze krijgen de user-ID van de update die ze startte.
- **JobQueue-jobs** (`run_repeating` e.d.) hebben geen "interactie". Of ze de context erven van de plek waar ze zijn ingepland, hangt af van APScheduler-internals. Dat heb ik **niet geverifieerd** en de PTB-docs zwijgen erover. Het advies is om in job-callbacks de context expliciet te zetten, bijvoorbeeld `interaction_id="job:<naam>"`.

Schets (eigen ontwerp, niet uitgevoerd):

```python
# src/logcontext.py
import contextvars, uuid
from telegram import Update
from telegram.ext import BaseUpdateProcessor

user_id_var = contextvars.ContextVar("user_id", default=None)        # module-level, zie 2.2
interaction_id_var = contextvars.ContextVar("interaction_id", default=None)

class ContextUpdateProcessor(BaseUpdateProcessor):
    async def do_process_update(self, update, coroutine):
        user = update.effective_user if isinstance(update, Update) else None
        t1 = user_id_var.set(user.id if user else None)
        t2 = interaction_id_var.set(uuid.uuid4().hex[:12])
        try:
            await coroutine
        finally:
            interaction_id_var.reset(t2)
            user_id_var.reset(t1)

    async def initialize(self): ...
    async def shutdown(self): ...

class ContextFilter:            # op de HANDLER zetten, zodat third-party records het ook krijgen
    def filter(self, record):
        record.user_id = user_id_var.get()
        record.interaction_id = interaction_id_var.get()
        return True

# bot.py: Application.builder()...concurrent_updates(ContextUpdateProcessor(1))
```

### 2.4 Een eigen JSON-formatter (stdlib)

- Het cookbook-recept "Implementing structured logging" laat de minimale variant zien: een berichtobject dat `"%s >>> %s" % (message, json.dumps(kwargs))` rendert (<https://docs.python.org/3.12/howto/logging-cookbook.html#implementing-structured-logging>). Dat is een hybride regel, zie hoofdstuk 4.
- Een volledige JSON-formatter is een subclass van `logging.Formatter` die van `record` een dict maakt. Denk aan `created`, `levelname`, `name`, `getMessage()`, `user_id`, `interaction_id` en bij een exceptie `formatException(record.exc_info)`, gevolgd door `json.dumps`. Dit leid ik af uit de `Formatter`-API (<https://docs.python.org/3.12/library/logging.html#formatter-objects>). De docs bieden geen kant-en-klare `JsonFormatter`.
- `json.dumps` escapet newlines in strings. Met `ensure_ascii=True` (de default) worden niet-ASCII-tekens ge-escaped in plaats van weggegooid (<https://docs.python.org/3.12/library/json.html#json.dump>). Eén record blijft zo één regel zonder dataverlies. Dat is precies wat `clean_message()` nu met verlies probeert te bereiken.

### 2.5 structlog

- **Status**: laatste release 26.1.0 (2026-06-06), `requires_python >=3.10`, licentie "MIT OR Apache-2.0", repo actief en niet gearchiveerd (<https://pypi.org/project/structlog/>, <https://github.com/hynek/structlog>).
- **Context**: `structlog.contextvars.bind_contextvars()`, `clear_contextvars()` en `bound_contextvars()`, met de processor `merge_contextvars` als eerste in de keten. Het is "safe to be used both in threaded as well as asynchronous code". Het aanbevolen patroon is `clear_contextvars()` aan het begin van elke request (<https://www.structlog.org/en/stable/contextvars.html>). Er is ook ondersteuning voor `Token`s: `bind_contextvars()` geeft tokens terug en `reset_contextvars(**tokens)` herstelt de vorige waarden (zelfde pagina, sectie "Support for contextvars.Token"). Voor PTB met sequentiële updates speelt hetzelfde lek-risico als in 2.3, dus clear of reset per update.
- **Third-party records via `logging.getLogger`**: daarvoor dient `structlog.stdlib.ProcessorFormatter`, een `logging.Formatter` die ook "non-structlog log entries" door structlog-processors haalt. De `foreign_pre_chain` "should in general match the processors argument to structlog.configure()" (<https://www.structlog.org/en/stable/standard-library.html>). Volgens die regel hoort `merge_contextvars` ook in `foreign_pre_chain`, maar de docs noemen dat **niet expliciet** voor contextvars. `ExtraAdder` neemt `extra=`-velden van stdlib-records over (zelfde pagina).
- **Inspanning**: de docs zeggen zelf dat volledige integratie met stdlib-logging "fiddly" is bij de eerste keer. Ze noemen "Don't integrate" ook als volwaardige optie (<https://www.structlog.org/en/stable/standard-library.html#suggested-configurations>).
- **asyncio**: de async-varianten (`ainfo()` e.d.) loggen "asynchronously in a separate thread". `AsyncBoundLogger` is sinds 23.1.0 deprecated ("This approach has turned out to be a mistake") (<https://www.structlog.org/en/stable/api.html>). De performance-pagina waarschuwt dat logging naar threads verplaatsen "comes with a performance cost" (<https://www.structlog.org/en/stable/performance.html>).
- **Renderers**: `JSONRenderer`, `ConsoleRenderer`, `KeyValueRenderer` en `LogfmtRenderer` (<https://www.structlog.org/en/stable/api.html>).

### 2.6 python-json-logger

- **Status**: laatste stabiele release 4.2.0 (2026-08-15), `requires_python >=3.10`, BSD-2-Clause. Er bestaan 4.3.0-dev-releases (eind oktober 2026). Onderhoud ligt bij Nicholas Hairs (<https://pypi.org/project/python-json-logger/>, <https://github.com/nhairs/python-json-logger>). De oorspronkelijke repo `madzak/python-json-logger` is **gearchiveerd** (GitHub-API `archived: true`, <https://github.com/madzak/python-json-logger>). Versie 3.0.0 was de eerste release van de fork (<https://nhairs.github.io/python-json-logger/latest/changelog/>).
- **API-breuken** (changelog):
  - 3.1.0: `pythonjsonlogger.jsonlogger` is verplaatst naar `pythonjsonlogger.json` (`from pythonjsonlogger.json import JsonFormatter`).
  - 4.0.0: argumenten hernoemd en verwijderd, bijvoorbeeld `json_default`/`json_encoder`/`json_serializer`.
  - 4.1.0: Python 3.8/3.9 niet meer ondersteund.
  
  Oudere voorbeelden, ook in de structlog-docs (`from pythonjsonlogger import jsonlogger`), gebruiken nog het oude pad (<https://www.structlog.org/en/stable/standard-library.html>).
- **Wat het is**: alleen een `logging.Formatter`. Velden komen uit `fmt`, `extra`, `defaults` en `static_fields` en uit niet-gereserveerde `LogRecord`-attributen (<https://nhairs.github.io/python-json-logger/latest/quickstart/>).
- **Context**: de cookbook-sectie "Request / Trace IDs" geeft drie opties: `extra`, een `Filter` (gebaseerd op het stdlib-cookbookrecept) en `process_log_record` overriden (<https://nhairs.github.io/python-json-logger/latest/cookbook/>). Let op: dat voorbeeld zet het filter op een **logger** (`logger.addFilter`). Volgens de stdlib-docs raakt dat geen third-party loggers. Zet het filter op de handler, of gebruik de `process_log_record`-variant in de formatter: die draait voor elk record dat de handler formatteert.
- **asyncio**: geen eigen asyncio-gedrag. Het is een formatter en gedraagt zich als de stdlib (zie 2.7).

### 2.7 Blokkerende I/O in asyncio

- De cookbook zegt bij "Dealing with handlers that block" dat bij async code "network and even file handlers could lead to problems (blocking the event loop)". Daarom: "It might be best ... to use the above approach", namelijk `QueueHandler` + `QueueListener` (<https://docs.python.org/3.12/howto/logging-cookbook.html#dealing-with-handlers-that-block>).
- `QueueHandler.prepare()` formatteert het bericht en zet `args`/`exc_info`/`exc_text` op `None`. Een handler achter de `QueueListener` kan exceptions dus niet meer zelf formatteren, tenzij je `prepare` overridet (<https://docs.python.org/3.12/library/logging.handlers.html#logging.handlers.QueueHandler.prepare>). Nieuw in 3.12: `QueueHandler.listener` wordt via `dictConfig` gezet (zelfde pagina).
- **Gevolg voor context (eigen analyse, volgt uit 2.2)**: de `QueueListener` draait in een eigen thread zonder de contextvars van de taak. Context moet dus vastgelegd worden **vóór** de queue. Dat kan met een filter op de `QueueHandler` of met de record factory, niet met een filter op de bestands-handler achter de listener.
- Voor één bot met lokale bestanden is de blokkering per record klein. Hoe groot precies, daarover zwijgen de docs. De `QueueHandler` is een optimalisatie en geen vereiste.

### 2.8 Vergelijking

| | stdlib (Filter + contextvars + eigen JSON-formatter) | structlog | python-json-logger |
|---|---|---|---|
| Extra dependency | geen | ja (26.1.0) | ja (4.2.0) |
| Context per interactie | `ContextVar` + handler-filter of record factory | `bind_contextvars` + `merge_contextvars` | zelfde als stdlib (filter of `process_log_record`) |
| Third-party records (`httpx`, `telegram`) | ja, mits filter op de **handler** of record factory | ja, via `ProcessorFormatter` + `foreign_pre_chain` | ja, mits filter op de handler |
| asyncio | contextvars werkt native; file-I/O blokkeert (QueueHandler optioneel) | idem; async-methodes gebruiken threads (kost performance) | idem stdlib |
| Onderhoud | CPython (3.12 security-only tot 2028-10) | actief, één hoofdmaintainer | actieve fork; origineel gearchiveerd; recente breaking changes |
| Complexiteit voor deze bot | laag (circa 40 regels eigen code) | middel ("fiddly" integratie) | laag |

## 3. Dagelijkse rotatie zonder ooit automatisch te verwijderen

### 3.1 Gedrag van `TimedRotatingFileHandler` in 3.12

Bronnen: docs <https://docs.python.org/3.12/library/logging.handlers.html#timedrotatingfilehandler> en broncode <https://github.com/python/cpython/blob/3.12/Lib/logging/handlers.py>.

- **`backupCount=0` verwijdert niets.**
  - De docs zeggen: "If backupCount is nonzero, at most backupCount files will be kept".
  - In de 3.12-broncode draait de opschoonstap alleen onder `if self.backupCount > 0:`, met daarin `for s in self.getFilesToDelete(): os.remove(s)`.
  - Het roteren zelf is een `os.rename(source, dest)` (`BaseRotatingHandler.rotate`).
  - Uitzondering op 3.12.0–3.12.2: zie 3.2, gh-88352 (overschrijven van een bestaande backup).
- **Naamgeving.**
  - `when="midnight"` of `"D"` gebruikt suffix `"%Y-%m-%d"`. Het actieve bestand houdt de basisnaam (bijv. `bot.log`), de backup wordt `bot.log.2026-11-01`.
  - De datum is die van het **begin van het afgesloten interval** (`t = self.rolloverAt - self.interval` in `doRollover`).
  - Met `namer` kun je de naam aanpassen, bijvoorbeeld `bot.2026-11-01.log`. De docs eisen dan dat de naam sorteerbaar blijft op het datumdeel. Dat is alleen relevant bij `backupCount > 0` (<https://docs.python.org/3.12/library/logging.handlers.html#logging.handlers.BaseRotatingHandler.namer>).
- **Herstart / mtime.**
  - Docs: "When computing the next rollover time for the first time (when the handler is created), the last modification time of an existing log file, or else the current time, is used".
  - Broncode: `t = os.stat(filename)[ST_MTIME]` en daarna `self.rolloverAt = self.computeRollover(t)`.
  - Bij `midnight` is `rolloverAt` dus de eerstvolgende middernacht ná de laatste schrijfactie. Is het bestand gisteren voor het laatst beschreven, dan triggert het eerste record na de start meteen een rollover. Die krijgt de datum van gisteren (eigen analyse van `computeRollover`/`doRollover`).
  - Het bekende mtime-probleem (gh-84649) speelt vooral bij korte intervallen (`S`/`M`/`H`) met frequente herstarts. Elke schrijfactie verschuift de mtime, waardoor rollover steeds wordt uitgesteld (<https://github.com/python/cpython/issues/84649>). Op main is in 2026 `statx()` (geboortetijd) toegevoegd ("gh-84649: Use statx() in TimedRotatingFileHandler if available"). Dat zit niet in 3.12.
- **Rollover gebeurt alleen bij een emit.** Docs: "rollover occurs only when emitting output". Na middernacht blijft het oude bestand dus open tot het eerste record van de nieuwe dag.
- **Valkuil in de huidige code**: `Path(log_file).touch(exist_ok=True)` zet bij een bestaand bestand de mtime op "nu" (<https://docs.python.org/3.12/library/pathlib.html#pathlib.Path.touch>). Laat je dat staan vóór een `TimedRotatingFileHandler`, dan wordt het bestand van gisteren bij een herstart niet meteen geroteerd. De records van gisteren belanden dan onder de datum van vandaag (eigen analyse).

### 3.2 Bekende problemen in 3.12 (belangrijk voor "wekenlang draaien")

- **gh-88352, gefixt in 3.12.3** (changelog: "doRollover() no longer overwrite the already rolled over file, saving from data loss when run at midnight or during repeated time at the DST change", <https://docs.python.org/3.12/whatsnew/changelog.html>, sectie 3.12.3; issue <https://github.com/python/cpython/issues/88352>).
  - Tot en met 3.12.2 werd een bestaande backup met dezelfde naam **overschreven**. Dat botst met "nooit verwijderen".
  - Sinds 3.12.3 staat er `if os.path.exists(dfn): return  # Already rolled over.`
- **gh-159690, nieuw probleem door die fix** (<https://github.com/python/cpython/issues/159690>).
  - In 3.12 werkt `doRollover()` `rolloverAt` pas op de laatste regel bij. De vroege `return` hierboven slaat dat over.
  - Bestaat de backupnaam al, dan neemt elke volgende emit dezelfde vroege return. De handler "never rolls over again" en het basisbestand groeit onbeperkt, tot een herstart. Er gaan geen data verloren, maar de dagindeling is weg.
  - De reporter testte main en 3.12.3. De fix staat op main (gemerged in oktober 2026), met backport-PR's naar 3.14 en 3.15. Een 3.12-fix is er niet.
- **gh-160433: verkeerde backupnaam rond DST** (<https://github.com/python/cpython/issues/160433>).
  - In `doRollover` vergelijkt 3.12 de DST-status van **nu** (het moment van het triggerende record) met die van het intervalbegin, en verschuift de naam bij verschil een uur.
  - Het triggerende record kan "long after rolloverAt" binnenkomen. In het voorbeeld van het issue (America/New_York, `midnight`, einde zomertijd) krijgt het interval van 31 oktober de al gebruikte naam van 30 oktober.
  - De fix staat op main sinds 2026-10-24, met backport-PR's naar 3.14 en 3.15.
- **Toegepast op Europe/Amsterdam (eigen analyse van de 3.12-code, niet uitgevoerd).**
  - Op 2026-10-25 springt de klok om 03:00 CEST terug naar 02:00 CET. Komt het eerste record na middernacht pas ná die overgang, dan wordt de backup van 24 oktober `...2026-10-23` genoemd. Die bestaat al.
  - Op 3.12.3+ stopt daardoor de rotatie (gh-159690) tot de volgende herstart. Op 3.12.0–3.12.2 wordt de backup van 23 oktober overschreven.
  - In de lentenacht levert dezelfde berekening toevallig de juiste naam op.
  - Bij een bot die 's nachts weinig logt (INFO-niveau, `httpx` op WARNING) is "eerste record na 03:00" realistisch.
- **Onderhoudsstatus**: 3.12 heeft de status "security", met end-of-life 2028-10 (<https://devguide.python.org/versions/>). Bovenstaande bugfixes komen dus niet naar 3.12. In de changelog t/m 3.12.16 komt `TimedRotatingFileHandler` na 3.12.3 niet meer voor (gezocht op de klassenaam).
- **Mitigatie binnen de stdlib**: met `utc=True` slaat de 3.12-code alle DST-correcties over (`if not self.utc`-takken in `computeRollover`/`doRollover`). De dagscheiding valt dan op 00:00 UTC, dus 01:00 of 02:00 lokale tijd, en de bestandsdatum is een UTC-datum.

### 3.3 `WatchedFileHandler` + `logrotate`

- **`WatchedFileHandler`** controleert bij elke emit of device of inode van het bestand veranderd is. Zo ja, dan sluit het het bestand en opent het opnieuw. Het is bedoeld voor "programs such as newsyslog and logrotate" en alleen geschikt voor Unix/Linux (<https://docs.python.org/3.12/library/logging.handlers.html#watchedfilehandler>). Rotatie zit dan buiten het proces, dus geen mtime- of DST-logica in Python.
- **logrotate-opties** (manpage <https://github.com/logrotate/logrotate/blob/main/logrotate.8.in>; laatste release 3.22.0, 2024-06-01):
  - `rotate count`: "If count is 0, old versions are removed rather than rotated. If count is -1, old logs are not removed at all, except they are affected by maxage ... **Default is 0.**" Voor "nooit verwijderen" is `rotate -1` dus verplicht en mag `maxage` niet gebruikt worden ("rotate -1 does not hinder removal").
  - `dateext` en `dateformat`: de default-extensie is `-%Y%m%d`. `dateyesterday` gebruikt de datum van gisteren, "so that the rotated log file has a date in its name that is the same as the timestamps within it".
  - `copytruncate` is niet nodig, want `WatchedFileHandler` heropent zelf. De manpage waarschuwt dat daarbij "some logging data might be lost".
- **Timing**: de upstream `examples/logrotate.timer` gebruikt `OnCalendar=daily`, `RandomizedDelaySec=1h` en `Persistent=true` (<https://github.com/logrotate/logrotate/blob/main/examples/logrotate.timer>). De rotatie gebeurt dus ergens tussen 00:00 en 01:00, waardoor een "dagbestand" tot een uur van de volgende dag kan bevatten. Distributies kunnen hiervan afwijken. Dat heb ik niet gecontroleerd voor de server.
- **Afweging (eigen oordeel)**:
  - Voordelen: robuust, beproefd, en precies de route die de structlog-docs noemen ("systemd redirecting your log entries to syslogd and rotating them using logrotate", <https://www.structlog.org/en/stable/logging-best-practices.html>).
  - Nadelen: een gevaarlijke default (`rotate 0` verwijdert), configuratie in `/etc/logrotate.d` buiten de repo, onscherpe dagscheiding, en de `/log`-reader moet ook de `logrotate`-naamgeving kennen.

### 3.4 Alternatief: zelf direct naar datumbestanden schrijven (eigen ontwerp)

De docs bieden geen handler die direct naar een gedateerde bestandsnaam schrijft. Met de gedocumenteerde `FileHandler`-API is die wel eenvoudig te maken:

- `FileHandler.emit` opent het bestand lui opnieuw als `self.stream is None` (CPython 3.12 `Lib/logging/__init__.py`).
- `Handler.handle` roept `emit` al aan onder de I/O-lock van de handler (<https://docs.python.org/3.12/library/logging.html#logging.Handler.handle>).
- `BaseRotatingHandler` sluit de stream op dezelfde manier (`self.stream.close(); self.stream = None`).

```python
import logging, os
from datetime import datetime
from pathlib import Path

class DailyFileHandler(logging.FileHandler):
    """Schrijft naar <folder>/<prefix>-JJJJ-MM-DD.jsonl op basis van record.created.
    Hernoemt en verwijdert nooit iets; een herstart appendt gewoon aan het bestand van vandaag."""

    def __init__(self, folder, prefix, encoding="utf-8"):
        self.folder, self.prefix = Path(folder), prefix
        self.folder.mkdir(parents=True, exist_ok=True)
        self.day = datetime.now().date()
        super().__init__(self._path(self.day), mode="a", encoding=encoding, delay=True)

    def _path(self, day):
        return os.path.abspath(self.folder / f"{self.prefix}-{day.isoformat()}.jsonl")

    def emit(self, record):
        day = datetime.fromtimestamp(record.created).date()   # lokale datum; DST irrelevant
        if day != self.day:
            if self.stream:
                self.stream.close()
                self.stream = None          # FileHandler.emit opent lui het nieuwe pad
            self.day, self.baseFilename = day, self._path(day)
        super().emit(record)
```

Eigenschappen:

- Er staat geen `os.remove` of `os.rename` in de code, dus "nooit verwijderen" volgt uit de constructie.
- Er is geen mtime-afhankelijkheid, dus `touch()` en herstarts zijn irrelevant.
- Elk record belandt in het bestand van zijn eigen lokale datum.
- De naam sorteert lexicografisch.

Het nadeel is dat het maatwerk is (niet getest). Een debug-bestand vraagt een tweede instantie met een ander prefix.

### 3.5 Vergelijking rotatie

| | `TimedRotatingFileHandler` (3.12) | `WatchedFileHandler` + logrotate | eigen `DailyFileHandler` |
|---|---|---|---|
| Verwijdert nooit | ja met `backupCount=0` (3.12.3+); 3.12.0–3.12.2 kan backup overschrijven | alleen met `rotate -1` en zonder `maxage` (default verwijdert) | ja, door constructie |
| Herstart | mtime-gebaseerd; correct voor `midnight`, maar `touch()` verstoort | n.v.t. | appendt aan bestand van vandaag |
| DST (Europe/Amsterdam) | risico op vastlopen of verkeerde naam (gh-159690/160433); `utc=True` omzeilt | geen Python-logica | geen probleem (datum per record) |
| Dagscheiding | eerste record na middernacht | timer 00:00–01:00 (upstream) | exact per record |
| Bestandsnamen | `bot.log` + `bot.log.JJJJ-MM-DD` | `bot.log` + `bot.log-JJJJMMDD` (default) | `bot-JJJJ-MM-DD.jsonl` |
| Extra config buiten repo | nee | ja (`/etc/logrotate.d`) | nee |

## 4. Eén bestand voor `less`/`grep` én `jq`, of twee formaten?

- **JSON Lines in één bestand** (eigen oordeel):
  - `jq` verwerkt de invoer "as a sequence of whitespace-separated JSON values", dus één object per regel werkt direct (<https://jqlang.org/manual/>).
  - `grep` werkt per regel. Dankzij JSON-escaping (2.4) blijft een record met newlines of een traceback op één regel.
  - Met `less` is het leesbaar maar druk. Een leesbare weergave maak je met bijvoorbeeld `jq -r '"\(.ts) \(.level) \(.user_id) \(.msg)"'`.
- **Hybride regel** (tekstprefix + JSON-staart): de stdlib-cookbook laat dit zelf zien (`message 1 >>> {"fnum": ...}`, <https://docs.python.org/3.12/howto/logging-cookbook.html#implementing-structured-logging>). Mensvriendelijk, maar `jq` heeft dan `-R` ("each line of text is passed to the filter as a string") plus het knippen van het JSON-deel nodig (<https://jqlang.org/manual/>). Dat is fragiel als het scheidingsteken in een bericht voorkomt.
- **logfmt / key=value**: structlog heeft `LogfmtRenderer` en `KeyValueRenderer` (<https://www.structlog.org/en/stable/api.html>). Goed leesbaar en greppable, maar `jq` leest het niet natively.
- **Twee formaten via twee handlers** is goed ondersteund:
  - Stdlib: één logger met meerdere handlers, elk met een eigen formatter (cookbook "Multiple handlers and formatters", <https://docs.python.org/3.12/howto/logging-cookbook.html#multiple-handlers-and-formatters>).
  - structlog: voorbeeld met een `plain`- en een `colored`-formatter op twee handlers. Beide "are run for each log entry" (<https://www.structlog.org/en/stable/standard-library.html>).
  - Kosten: dubbele schijfruimte en twee bestandsreeksen.
- **"Gebruikelijke praktijk"**: de structlog-docs adviseren "pretty printed" output tijdens development en "in production you should emit structured output (like JSON)" (<https://www.structlog.org/en/stable/logging-best-practices.html>). De Python-docs zeggen hier **niets** over. Of één gecombineerd bestand of twee bestanden gangbaarder is, wordt in de geraadpleegde bronnen niet vastgesteld.

## 5. `/log <user>`: snel de recentste records van één gebruiker lezen

Feiten uit de docs:

- In tekstmodus zijn alleen seeks vanaf het begin toegestaan, met als uitzondering `seek(0, 2)`. Achterwaarts lezen met willekeurige offsets vanaf het einde vraagt dus **binaire** modus (<https://docs.python.org/3.12/tutorial/inputoutput.html#methods-of-file-objects>).
- Het `deque`-recept `deque(f, n)` geeft de laatste n regels (<https://docs.python.org/3.12/library/collections.html#deque-recipes>). Het geheugen blijft begrensd, maar het hele bestand wordt gelezen. Bij 200 MB is dat 200 MB I/O plus parsing per aanroep.
- `mmap` heeft `rfind()` en gedraagt zich als `bytearray` (<https://docs.python.org/3.12/library/mmap.html#mmap.mmap.rfind>). Dat is een alternatief voor achterwaarts zoeken zonder eigen blokbeheer.
- `asyncio.to_thread()` voert blokkerende code uit in een thread (<https://docs.python.org/3.12/library/asyncio-task.html#asyncio.to_thread>), zodat de event loop van de bot niet stilvalt.
- Telegram-berichten zijn maximaal "1-4096 characters after entities parsing" (<https://core.telegram.org/bots/api#sendmessage>). Begrens N dus en kort velden in. `send_telegram_message` splitst nu al op 1024 tekens.

Aanpak (eigen ontwerp, niet uitgevoerd):

```python
import asyncio, json
from pathlib import Path

def iter_lines_reversed(path, block=1 << 16):
    """Regels (bytes) van achter naar voren; geheugen begrensd tot circa één blok."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        pos, rest = f.tell(), b""
        while pos > 0:
            step = min(block, pos)
            pos -= step
            f.seek(pos)
            lines = (f.read(step) + rest).split(b"\n")
            rest = lines.pop(0)                 # mogelijk onvolledig: bewaren voor het volgende blok
            for line in reversed(lines):
                if line:
                    yield line
        if rest:
            yield rest

def recent_for_user(folder, prefix, user_id, limit=20, max_files=31):
    needle = f'"user_id": {user_id}'.encode()   # goedkope voorselectie; exacte check na json.loads
    found = []
    files = sorted(Path(folder).glob(f"{prefix}-*.jsonl"), reverse=True)[:max_files]  # ISO-datum: nieuw eerst
    for path in files:
        for raw in iter_lines_reversed(path):
            if needle not in raw:
                continue
            try:
                rec = json.loads(raw)
            except ValueError:                  # half geschreven laatste regel van het actieve bestand
                continue
            if rec.get("user_id") == user_id:
                found.append(rec)
                if len(found) >= limit:
                    return found
    return found

# in de command-handler:
# records = await asyncio.to_thread(recent_for_user, "log", "bot", user_id)
```

Opmerkingen:

- **Kosten.** Voor een actieve gebruiker leest dit alleen de staart van het nieuwste bestand of de nieuwste bestanden. In het slechtste geval (onbekende of inactieve gebruiker) lees je alle `max_files` volledig. Begrens daarom op aantal dagen of bytes (eigen oordeel).
- **De byte-needle hangt af van de serialisatie.** `json.dumps` gebruikt standaard `", "` en `": "` als separators (<https://docs.python.org/3.12/library/json.html#json.dumps>). Houd de formatter en de needle dus gelijk, en verifieer na het parsen. Een needle als `"user_id": 12` matcht ook `"user_id": 123`. De check na het parsen vangt dat af.
- **Met `TimedRotatingFileHandler`** heeft het actieve bestand geen datum (`bot.jsonl`) en de backups wel (`bot.jsonl.2026-11-01`). De reader moet dan eerst het actieve bestand lezen en daarna de backups, aflopend gesorteerd. Met `logrotate` geldt hetzelfde, met naamgeving `-JJJJMMDD`.
- **Alternatieven bij grotere volumes**: een apart bestand per gebruiker, of een index of SQLite naast de logs. Daar zeggen de geraadpleegde bronnen niets over. Ik noem ze alleen als richting.

## 6. Waar de bronnen zwijgen of het niet zeker is

- Of PTB-JobQueue-jobs (APScheduler) de contextvars erven van de plek waar ze zijn ingepland: niet geverifieerd, en PTB-docs zeggen er niets over.
- Of `merge_contextvars` in structlog's `foreign_pre_chain` hoort: de docs zeggen alleen dat `foreign_pre_chain` "in general" gelijk moet zijn aan de processors in `configure()`.
- De DST-analyse voor Europe/Amsterdam (3.2) is een eigen doorrekening van de 3.12-broncode. Ze is consistent met gh-159690 en gh-160433, maar niet met een draaiende interpreter getest.
- Welke 3.12-patchversie op de server draait, is onbekend. Dat bepaalt of gh-88352 (overschrijven) of gh-159690 (vastlopen) van toepassing is. Controleer dat met `python3 --version` in de venv.
- Hoe groot de blokkering van synchrone file-I/O in de event loop in de praktijk is: daar zeggen de docs niets over in cijfers.
- Of één gecombineerd bestand of twee formaten "gebruikelijk" is: geen primaire bron stelt dat vast. Alleen structlog geeft het advies "JSON in productie".

## 7. Bronnen

Python 3.12 (docs.python.org):
- logging: <https://docs.python.org/3.12/library/logging.html> (Filter, LoggerAdapter, LogRecord-attributen incl. `taskName`, `setLogRecordFactory`, `Handler.handle`, `Formatter`)
- logging 3.13 (`merge_extra`): <https://docs.python.org/3.13/library/logging.html#logging.LoggerAdapter>
- logging.handlers: <https://docs.python.org/3.12/library/logging.handlers.html> (TimedRotatingFileHandler, WatchedFileHandler, BaseRotatingHandler, QueueHandler)
- Logging cookbook: <https://docs.python.org/3.12/howto/logging-cookbook.html> (contextvars, filters, LoggerAdapters, handlers that block, structured logging, multiple handlers and formatters)
- contextvars: <https://docs.python.org/3.12/library/contextvars.html>
- asyncio tasks (`create_task`, `to_thread`): <https://docs.python.org/3.12/library/asyncio-task.html>
- collections (deque-recepten): <https://docs.python.org/3.12/library/collections.html#deque-recipes>
- mmap: <https://docs.python.org/3.12/library/mmap.html>
- json: <https://docs.python.org/3.12/library/json.html>
- pathlib `Path.touch`: <https://docs.python.org/3.12/library/pathlib.html#pathlib.Path.touch>
- tutorial, file-objecten / seek: <https://docs.python.org/3.12/tutorial/inputoutput.html#methods-of-file-objects>
- changelog 3.12 (3.12.3, gh-88352): <https://docs.python.org/3.12/whatsnew/changelog.html>
- versiestatus: <https://devguide.python.org/versions/>

CPython-broncode en -issues:
- <https://github.com/python/cpython/blob/3.12/Lib/logging/handlers.py>
- <https://github.com/python/cpython/blob/3.12/Lib/logging/__init__.py>
- <https://github.com/python/cpython/blob/main/Lib/logging/handlers.py> (ter vergelijking: `rolloverAt` wordt vóór de vroege return bijgewerkt)
- gh-88352: <https://github.com/python/cpython/issues/88352>
- gh-159690: <https://github.com/python/cpython/issues/159690>
- gh-160433: <https://github.com/python/cpython/issues/160433>
- gh-84649: <https://github.com/python/cpython/issues/84649>

structlog:
- <https://www.structlog.org/en/stable/contextvars.html>
- <https://www.structlog.org/en/stable/standard-library.html>
- <https://www.structlog.org/en/stable/logging-best-practices.html>
- <https://www.structlog.org/en/stable/performance.html>
- <https://www.structlog.org/en/stable/api.html>
- <https://pypi.org/project/structlog/>, <https://github.com/hynek/structlog>

python-json-logger:
- <https://github.com/nhairs/python-json-logger>
- <https://nhairs.github.io/python-json-logger/latest/quickstart/>
- <https://nhairs.github.io/python-json-logger/latest/cookbook/>
- <https://nhairs.github.io/python-json-logger/latest/changelog/>
- <https://pypi.org/project/python-json-logger/>
- <https://github.com/madzak/python-json-logger> (gearchiveerd)

Overig:
- python-telegram-bot v21.10: <https://github.com/python-telegram-bot/python-telegram-bot/blob/v21.10/telegram/ext/_application.py>, <https://github.com/python-telegram-bot/python-telegram-bot/blob/v21.10/telegram/ext/_baseupdateprocessor.py>, <https://github.com/python-telegram-bot/python-telegram-bot/blob/v21.10/telegram/ext/_applicationbuilder.py>
- logrotate: <https://github.com/logrotate/logrotate/blob/main/logrotate.8.in>, <https://github.com/logrotate/logrotate/blob/main/examples/logrotate.timer>
- jq-handleiding: <https://jqlang.org/manual/>
- Telegram Bot API `sendMessage`: <https://core.telegram.org/bots/api#sendmessage>
