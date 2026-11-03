# Hoe worden logbestanden opgeslagen en geroteerd?

Type: grilling
Status: resolved
Blocked by: 02
Assignee: Wouter

## Question

Hoe slaan we logbestanden op en hoe roteren ze?

Te beslissen:

- Eén bestand per kalenderdag. Nu krijgt het bestand alleen de startdatum (`src/log.py`), dus een bot die weken draait schrijft alles in één bestand.
- Naamgeving van de bestanden, live en dev.
- Wat er met het aparte debug-bestand gebeurt (op 16-01-2026 werd dat 200 MB).
- Of journald (systemd vangt stdout/stderr al) ernaast een rol krijgt.

Randvoorwaarde: retentie blijft zoals nu, er wordt niets automatisch verwijderd.

Uit 06: logregels zijn JSON Lines in UTF-8, één object per regel. Bij `--verbose` gaat er tekst naar de console.

## Answer

Besloten in een grilling met de beheerder op 2026-11-03, in één ronde. Er zijn geen nieuwe begrippen bijgekomen in `CONTEXT.md`.

### Correctie op de vraag

Het bestand van 200 MB op 16-01-2026 was geen debug-bestand: dat bestaat pas sinds 21-09-2026 (`ed2b98f`). Het was het gewone dev-log (`log/dev-wouter-thuisserver-bot-01-16-2026.log`), gevuld door een lus: 38.640 keer "Telegram API error: Can't parse entities", elk met een traceback van ongeveer 70 regels, 40 per seconde, 18 minuten lang. Dat is een Bug die zich herhaalt, geen geruis van libraries.

### Besluiten

1. **Eén bestand per kalenderdag, in lokale tijd** (dezelfde tijd als `ts`). Het bestand volgt uit de tijd van de regel zelf, niet uit de start van het proces. Na een herstart schrijft de bot verder in het bestand van die dag. Een bestand wordt nooit hernoemd, geleegd of verwijderd. Op de dagen dat de klok verzet wordt, beslaat een bestand 23 of 25 uur.
2. **Naam**: `plex-download-bot-JJJJ-MM-DD.jsonl` voor live, ook in maintenance mode, en `dev-plex-download-bot-JJJJ-MM-DD.jsonl` voor dev. De ISO-datum sorteert vanzelf in `ls`; de prefix `dev-` houdt de bestanden uit elkaar als live-logs naar de pc gekopieerd worden. De map blijft `LOG_FOLDER`.
3. **Elke host houdt zijn eigen logbestanden.** `log/` blijft buiten Syncthing en de hostnaam staat niet in de naam. `/log` en SSH tonen alleen wat op die host gebeurde; voor een periode op de fallback log je in op de fallback-host. Mocht dat later toch nodig zijn: hostnaam in de naam en `log/` mee in Syncthing.
4. **Het hoofdbestand bevat altijd INFO en hoger**, welke `LOG_TYPE` er ook staat. Bij `LOG_TYPE=DEBUG` komt er per dag een tweede bestand, `plex-download-bot-JJJJ-MM-DD-debug.jsonl` (dev: `dev-plex-download-bot-JJJJ-MM-DD-debug.jsonl`), met alles vanaf DEBUG. Daarin staan ook de regels van INFO en hoger, zodat het op zichzelf compleet is. `LOG_TYPE` kent alleen nog `INFO` en `DEBUG`: bij `WARNING` of `ERROR` zou `/log` zijn gebruikersacties missen. Ook het debug-bestand wordt nooit automatisch verwijderd; DEBUG zet je tijdelijk aan.
5. **journald krijgt geen logregels.** Het journal blijft de plek voor wat buiten de logging valt: meldingen van systemd en een crash vóór de logging-setup. Om via SSH live mee te kijken, komt in de README `tail -F` op het bestand van vandaag, met de `jq`-regel uit 06. Die volgt niet over middernacht heen.
6. **Bestaande `.log`-bestanden blijven staan** zoals ze zijn en worden niet omgezet. `/log` leest alleen `.jsonl`, dus het kijkt niet verder terug dan de dag van de overstap.
7. **Geen compressie en geen maximumgrootte.** Geschat: op INFO tientallen kB per dag, hooguit tientallen MB per jaar. Een maximumgrootte zou regels weggooien, juist bij een Bug die je wilt zien. Herhaalde regels afremmen hoort bij 13.

### Feiten uit de code (voor de implementatie)

- Nu staat de startdatum van het proces in de naam (`src/log.py`), in de vorm MM-DD-JJJJ, onder de naam `wouter-thuisserver-bot`. Het langste live-bestand in oktober besloeg 8 dagen.
- `TimedRotatingFileHandler` valt af: op Python 3.12.3 (de server) roteert hij na de overgang naar wintertijd niet meer tot een herstart (02, 03). Het advies uit 02 is een eigen handler die per regel het bestand kiest op basis van `record.created`. `Path(log_file).touch()` in `src/log.py` vervalt dan.
- De README en `dot-env.template` beschrijven het debug-bestand als `<name>-<date>-debug.log` en geven `LOG_TYPE` vier waarden. Die moeten mee.
- De systemd-units starten zonder `--verbose`; daar verandert niets.

### Doorgeschoven

- De lus van 16-01-2026 als voorbeeld van herhaalde regels: [Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?](13-herhaalde-fouten-afremmen.md)
- Of een startcrash en Python-warnings alsnog een logregel worden, welke regels van libraries in het hoofdbestand en het debug-bestand komen, en wat de console bij `--verbose` toont: [Wat komt er van buiten de eigen code in de logregels?](12-ruis-buiten-eigen-code.md)
- Dat `/log` alleen `.jsonl` en alleen de bestanden van de eigen host leest: [Wat toont /log <gebruiker>, en voor wie?](11-log-command.md)
