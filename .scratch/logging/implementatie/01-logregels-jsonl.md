# 01 Logregels in JSONL-dagbestanden

Status: dicht
Blocked by: –
Niet tegelijk met: –

## Wat

Het fundament: de bot schrijft voortaan JSON Lines in één bestand per dag. De oude aanroepen blijven werken via een dunne laag.

- Een nieuw pakket `src/log/` vervangt `src/log.py`:
  - `setup_logging(env, level, folder, verbose)`, `get_logger(name)` en `mask(text)`
  - `src/log/files.py` met de naam per dag en de lijst van dagbestanden
- **Formatter**: de velden in de volgorde van de spec. Velden zonder waarde worden weggelaten, UTF-8 blijft letterlijk, en de separators zijn die van `json.dumps`. `logger` en `src` zijn die van de aanroeper. Bij een exceptie komen `exc_type` en `exc` erin.
- **Een handler per dagbestand** die het bestand kiest op basis van `record.created`, in lokale tijd:
  - het hoofdbestand bevat altijd INFO en hoger
  - bij `LOG_TYPE=DEBUG` komt er een `-debug.jsonl` bij
  - `LOG_TYPE` kent alleen nog `INFO` en `DEBUG`
  - de namen voor live en dev volgen de spec
- **Filters**:
  - eigen code tegenover libraries: alle loggers van de bot hangen onder één naam
  - maskeren van de zes geheimen, in elk veld
- **Console bij `--verbose`**: tekst als `ts level account event msg`. Eigen code vanaf `LOG_TYPE`, libraries vanaf WARNING.
- **Warnings**: `logging.captureWarnings(True)`. De `PTBUserWarning` over `per_message=False` wordt gericht onderdrukt bij het bouwen van de ConversationHandler, met een comment waarom.
- **Start en stop**: `bot_started` en `bot_stopped` op INFO. De start- en stopregels van PTB verdwijnen door het filter op libraries uit het hoofdbestand.
- **Dunne laag**:
  - `Log.logger()` schrijft via de nieuwe logging, zonder MarkdownV2-escapes in het bestand en zonder `clean_message`. `src` is de aanroeper (`stacklevel`). Het Telegram-deel blijft voorlopig zoals het is.
  - `Log.debug_call()` schrijft een `http_call` op DEBUG.
- **Wat verdwijnt**: `NOISY_LOGGERS`, `NoLibraryChatter`, de bestandsnaam met de startdatum en `Path(log_file).touch()`.
- **README en `dot-env.template`**: de nieuwe bestandsnamen, het debug-bestand, `LOG_TYPE` met twee waarden, en de `jq`-regel plus `tail -F` om via SSH mee te lezen.

## Spec

- [1. Logregels](../spec.md#1-logregels), behalve de soortnamen die latere issues invullen
- [3. Bestanden](../spec.md#3-bestanden)
- [4. Regels van buiten de eigen code](../spec.md#4-regels-van-buiten-de-eigen-code), punt 1 en 2
- [12. Logregels schrijven](../spec.md#logregels-schrijven) en de rij "Logregels" in [Modules](../spec.md#modules)

## Klaar als

- [ ] Op dev schrijft de bot `dev-plex-download-bot-JJJJ-MM-DD.jsonl`, en met `LOG_TYPE=DEBUG` ook `…-debug.jsonl`.
- [ ] Bestaande `.log`-bestanden blijven onaangeroerd.
- [ ] De `jq`-regel uit de README geeft leesbare regels.
- [ ] Er staat geen bot-token in het hoofdbestand of het debug-bestand, ook niet in de URL's van httpx.
- [ ] Tests (`unittest`) voor de gevallen onder "Logregels" in [Tests](../spec.md#tests):
  - de velden en hun volgorde, en velden zonder waarde worden weggelaten
  - UTF-8 blijft letterlijk staan
  - geheimen worden in elk veld gemaskeerd
  - INFO van een library komt niet in het hoofdbestand, wel in het debug-bestand
  - een nieuw dagbestand om middernacht lokale tijd, ook in de nacht van de klokwissel
  - `src` en `logger` zijn die van de aanroeper
- [ ] `python -m unittest discover -s tests` is groen.

## Niet in deze issue

- Context van de Interactie (`user_id`, `account`, `interaction_id`): 02
- Regels per Gebruikersactie: 04, 05
- Admin-meldingen en de klasse `Log` zelf weghalen: 03 en verder, en 15

## Aanwijzingen

- Nu schrijft `Log.log_to_file()` via de root-logger, dus `logger` is altijd `root` en de codeplek wijst altijd naar `src/log.py`.
- `TimedRotatingFileHandler` valt af: op Python 3.12.3 roteert hij na de overgang naar wintertijd niet meer tot een herstart.
- httpx logt op INFO elke URL, met het bot-token erin. transmission-rpc logt op DEBUG `gebruiker:wachtwoord@` in de URL.
