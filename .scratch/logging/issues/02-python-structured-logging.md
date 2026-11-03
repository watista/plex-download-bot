# Welke opties heeft Python voor gestructureerde logregels en dagelijkse rotatie?

Type: research
Status: resolved
Blocked by: –

## Question

Welke opties heeft Python 3.12 voor gestructureerde logregels met context per interactie, en voor dagelijkse rotatie in een proces dat weken achter elkaar draait?

Uit te zoeken, met de Python-documentatie en de documentatie van de libraries als bron:

- stdlib `logging` (Filter, LoggerAdapter, `contextvars`, eigen JSON-formatter) tegenover `structlog` en `python-json-logger`: afwegingen, gebruik met asyncio, onderhoudsstatus.
- `TimedRotatingFileHandler` met `when="midnight"`: wordt er met `backupCount=0` echt niets verwijderd, hoe heten de geroteerde bestanden, wat gebeurt er bij een herstart? Is `logrotate` met `WatchedFileHandler` een beter alternatief?
- Kan één bestand goed leesbaar zijn voor een mens (`less`, `grep`) én machinaal doorzoekbaar (`jq`)? Of zijn twee uitvoerformaten gebruikelijk?
- Hoe kan een command in de bot (`/log <gebruiker>`) efficiënt de recente logregels van één gebruiker uit dagbestanden lezen?

Context in de code: `src/log.py` (huidige setup: root-logger, bestandsnaam met vaste startdatum, apart debug-bestand).

## Answer

Bevindingen: branch `research/python-structured-logging` (commit `2d56d2c`), bestand `.scratch/logging/research/02-python-structured-logging.md`. De worktree staat in `.claude/worktrees/agent-a0bed8ab38f2e0947`.

- **Context kan volledig met de stdlib**: een `ContextVar` plus een `logging.Filter` op de handler (niet op de logger), of `setLogRecordFactory`. Alleen zo krijgen ook records van `httpx`, `telegram` en `apscheduler` de context mee. `LoggerAdapter` werkt alleen voor aanroepen via de adapter zelf.
- **Valkuil**: de bot draait met `concurrent_updates(False)`, dus alle updates lopen na elkaar in één asyncio-taak. Een contextvar lekt dan naar de volgende update als hij niet per update wordt gereset met de `Token`. `BaseUpdateProcessor.do_process_update` is het gedocumenteerde aanhaakpunt.
- **structlog** heeft de prettigste API, maar de integratie met third-party loggers is omslachtig en de meerwaarde voor deze bot is klein. **python-json-logger** is alleen een formatter: bruikbaar als je geen eigen JSON-formatter wilt onderhouden.
- **`TimedRotatingFileHandler(when="midnight", backupCount=0)`** verwijdert niets. Maar op 3.12 zijn er rotatiebugs rond de herfst-zomertijdovergang: tot een herstart wordt er niet meer geroteerd (3.12.3+), of een backup wordt overschreven (3.12.0–3.12.2). De fixes komen niet naar 3.12. Welke patchversie op de server draait, is nog onbekend (toegevoegd aan ticket 03).
- **`logrotate`** verwijdert standaard oude versies. Voor "nooit verwijderen" is `rotate -1` nodig, plus systeemconfig buiten de repo.
- **Beste fit (eigen oordeel van het onderzoek)**: een eigen handler van circa 20 regels die direct naar `<prefix>-JJJJ-MM-DD.jsonl` schrijft op basis van `record.created`. Die hernoemt en verwijdert niets, en kent geen DST-problemen.
- **JSON Lines** is te doorzoeken met `grep` en `jq` en houdt tracebacks op één regel, waardoor `clean_message()` overbodig wordt. Met `less` leest het minder prettig. Twee formaten via twee handlers (tekst + JSONL) is gangbaar.
- **`/log <gebruiker>`**: gebruik ISO-datums in de bestandsnamen, lees bestanden binair achterwaarts in blokken, en doe eerst een goedkope substring-check en pas daarna `json.loads`. Draai het in `asyncio.to_thread`. Een Telegram-bericht is maximaal 4096 tekens.
- **Bestaande code**: `Path(log_file).touch()` in `src/log.py` zet de mtime op "nu" en verstoort daarmee de mtime-gebaseerde rotatie na een herstart.

Niet geverifieerd: de codeschetsen in het onderzoek zijn niet uitgevoerd (geen Python op de onderzoeksmachine). Of JobQueue-jobs de contextvars erven, is niet nagegaan; dat hoort bij ticket 01.
