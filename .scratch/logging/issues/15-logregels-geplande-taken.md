# Welke logregels schrijft een run van een geplande taak?

Type: grilling
Status: resolved
Assignee: Wouter
Blocked by: 08, 11

## Question

Welke logregels schrijft een run van een geplande taak, behalve Gebruikersberichten en Fouten, en op welk niveau?

Te beslissen:

- Of een run een regel aan het begin en aan het eind krijgt, of één samenvatting (bijvoorbeeld "checked 14 items, 2 online"), en op welk niveau. Live draait op INFO.
- Welke tussenstappen per job een regel worden, en op welk niveau. Het gaat om `check_notify_list` (elke 30 minuten), `scan_missing_media` voor Sonarr en voor Radarr (elke 6 uur), en de jobs die eenmalig bij de start draaien (`publish_command_list`, `notify_admin_startup`). Ze worden geregistreerd in `src/bot.py:119-126`.
- Of een run zonder resultaat (niets online, niets ontbrekend) een regel schrijft. Elke 30 minuten is 48 runs per dag.

Uit 06: INFO staat voor de normale gang van zaken en DEBUG voor details. Een Storing is WARNING, een Bug of Inrichtingsfout ERROR.

Uit 08: elke run is een Interactie met een eigen `interaction_id` en een veld `job`, zonder velden van een gebruiker. Een run waarin de bot meerdere gebruikers bedient, houdt één ID.

Uit 11: elk Gebruikersbericht krijgt een eigen regel `user_message` met de ontvanger, ook binnen een job-run, en een mislukte aflevering wordt WARNING. `/log <code>` toont van een run alle regels van INFO en hoger. Wat een run schrijft, bepaalt dus wat de Beheerder ziet als hij de code uit een admin-melding over een job opvraagt.

Uit 12: regels van libraries komen pas vanaf WARNING in het hoofdbestand. apscheduler schrijft daar dus geen regel per run, en een run is in het hoofdbestand alleen zichtbaar via de eigen regels die dit ticket bepaalt.

Uit 14:
- `guard_job` geeft elke run een eigen context met `interaction_id` en `job`. De run schrijft zijn regels met `get_logger(__name__)` en velden als keywords.
- Een Gebruikersbericht gaat via `send_user_message`, die zelf de regel `user_message` schrijft.
- Elke request naar een dienst schrijft via de requestregel al een `http_call` op DEBUG.
- Als een controle in een run slaagt, laat de run dat weten met `faults.fixed()`.
- De heartbeat is geen job. Hij loopt via `guard_task` en valt buiten deze vraag.

## Answer

Besloten in een grilling met de beheerder op 2026-11-03, in twee rondes. In `CONTEXT.md` is **Geplande taak** bijgekomen, en een nieuw seizoen hoort nu bij de Gebruikersberichten. De namen van functies hieronder zijn voorstellen. Het gedrag en de velden zijn besloten.

### Besluiten

1. **Eén eindregel per run, altijd.** `guard_job` schrijft hem in een `finally`: `event: job_finished` op INFO, met `outcome` (`ok` of `stopped`), `duration_ms` en de tellingen van de job (besluit 3).
   - Ook een run zonder resultaat krijgt hem, en ook een run die door een Fout stopte. Na een stop staan de tellingen tot dat moment erin.
   - Er komt geen beginregel. De eerste regel van de run en `duration_ms` laten de start al zien.
   - Dat zijn zo'n 104 regels per dag (2 × 48 + 2 × 4), plus 2 bij elke start.
   - `/log <persoon>` toont ze niet, want ze hebben geen gebruikersvelden. `/log <code>` van een Fout in een job laat zo ook zien hoe de run afliep.
2. **Namen in `job`**, meegegeven met `name=` bij het registreren: `check_notify_list`, `check_transmission`, `scan_missing_sonarr`, `scan_missing_radarr`, `publish_command_list` en `notify_admin_startup`. Zonder `name=` noemt PTB een job naar zijn callback, en dan heten beide scans `scan_missing_media`.
3. **Tellingen in de eindregel**:

   | Job | Velden naast `outcome` en `duration_ms` | `msg`, bijvoorbeeld |
   |---|---|---|
   | `check_notify_list` | `items`, `sent`, `not_delivered`, `skipped` | "check_notify_list finished in 4.2 s: 14 items checked, 2 messages sent" |
   | `check_transmission` | geen | "check_transmission finished in 0.2 s: Transmission reachable" |
   | `scan_missing_sonarr`, `scan_missing_radarr` | geen | "scan_missing_sonarr finished in 0.3 s: missing search started" |
   | `publish_command_list`, `notify_admin_startup` | geen | "publish_command_list finished in 0.1 s" |

   - `items` is het aantal gecontroleerde items, `sent` het aantal afgeleverde Gebruikersberichten, `not_delivered` het aantal dat niet aankwam, en `skipped` het aantal items dat de run oversloeg door een Inrichtingsfout.
   - Een telling van 0 staat erin als `0`, zodat `jq` kan optellen. 0 is een waarde, dus dit botst niet met "velden zonder waarde worden weggelaten" uit 06.
   - Na een stop: "check_notify_list stopped after 1.2 s: 6 items checked, 1 message sent".
4. **Tellen met `tally(name, n=1)`** in `src/interaction.py`, naast `working_on`. Het houdt de tellingen bij in de context van de Interactie, en `guard_job` leest ze in de `finally`, dus ook na een stop. `send_user_message` telt `sent` en `not_delivered` zelf, zodat elk Gebruikersbericht meetelt. De job telt alleen `items` en `skipped`.
5. **Per item in `check_notify_list` een DEBUG-regel `notify_check`**, met:
   - `kind`: `online`, `new_season` of `new_episodes`, dezelfde waarden als bij `user_message`
   - de media-velden uit `working_on(item)`
   - `user_id` en `account` van de ontvanger, als keywords op de regel zelf en niet in de context. Een Fout tijdens dat item, zoals een serie zonder pad, krijgt zo geen gebruikersvelden (08) en verschijnt niet in `/log <persoon>`.
   - `outcome`: `no_data`, `no_folder`, `seasons_missing` (met `missing`, bijv. `["S03"]`), `empty_folder`, `nothing_new` of `sent`

   Live draait op INFO, dus daar staan deze regels nergens. Wil de Beheerder weten waarom iemand geen bericht kreeg, dan zet hij tijdelijk DEBUG aan, en de regels komen in het debug-bestand (07). Het bijwerken van `data.json` (een item van de lijst halen, de stand van de seizoenen bijwerken) krijgt geen eigen regel: de regel `user_message` is de registratie.
6. **De Transmission-check wordt een eigen job `check_transmission`**, elke 30 minuten en net als nu alleen in normal mode.
   - Nu staat de check vooraan in `check_notify_list`, die een onbereikbaar Transmission stil inslikt. Voortaan is dat een poging van een Storing (05, 14), en die beëindigt alleen de run van `check_transmission` (09, besluit 6).
   - De Gebruikersberichten lopen dus door, en de Code in een melding over Transmission wijst naar de goede job.
   - Gevolg: is Transmission twee runs achter elkaar onbereikbaar (30 minuten), dan krijgt de Beheerder een admin-melding, en later een Herstelmelding (13, besluit 1 en 2). Nu krijgt hij niets.
7. **`transmission_back`**: is Transmission bereikbaar terwijl hij bij de vorige run onbereikbaar was, dan schrijft de run vóór de twee zoekacties een INFO-regel "Transmission is back: starting the missing searches in Sonarr and Radarr". Mislukt daarna een zoekactie, dan volgen de regel van de Storing en een eindregel met `stopped`. Na een herstart weet de bot niet of Transmission onbereikbaar was, dus de eerste run start geen zoekacties, zoals nu.
8. **Een nieuw seizoen is een eigen soort Gebruikersbericht**: `kind: new_season`, naast de vier uit 11 (`online`, `new_episodes`, `message`, `broadcast`). Het gaat om "Seizoen 3 van X is nu beschikbaar" uit de lijst `recurring_serie`. De aanleiding en de tekst verschillen van die bij nieuwe afleveringen.
9. **De overige jobs schrijven alleen hun eindregel.**
   - De scans sturen één POST. Wat Sonarr of Radarr daarna vindt, ziet de bot niet, en de `http_call` staat op DEBUG.
   - `publish_command_list` heeft verder niets te melden.
   - `notify_admin_startup` stuurt "Bot gestart" als bericht aan de Beheerder via `send_admin_message`, die zelf `admin_message_sent` schrijft (14, besluit 14).

### Voorbeeld

Het einde van een run van `check_notify_list` die één Gebruikersbericht verstuurde, en een run die stopte door een Storing:

```json
{"ts": "2026-11-03T14:30:04.210+01:00", "level": "INFO", "event": "job_finished", "msg": "check_notify_list finished in 4.2 s: 14 items checked, 1 message sent", "outcome": "ok", "duration_ms": 4210, "items": 14, "sent": 1, "not_delivered": 0, "skipped": 0, "interaction_id": "k7p2qx", "job": "check_notify_list", "logger": "…", "src": "…"}
{"ts": "2026-11-03T15:00:01.412+01:00", "level": "INFO", "event": "job_finished", "msg": "check_notify_list stopped after 1.2 s: 6 items checked, 0 messages sent", "outcome": "stopped", "duration_ms": 1204, "items": 6, "sent": 0, "not_delivered": 0, "skipped": 0, "interaction_id": "m3tq8w", "job": "check_notify_list", "logger": "…", "src": "…"}
```

### Feiten uit de code (voor de implementatie)

- De jobs worden geregistreerd in `src/bot.py:119-126`. Over de twee `run_once`-jobs met `create_task` in een lambda: zie 14 (Feiten). `guard_job` moet om de coroutine zelf.
- `check_notify_list` begint met `check_transmission_and_trigger_scans` (`src/commands/schedule.py:48`), in een `try/except: pass`. Of Transmission bij de vorige run onbereikbaar was, staat alleen in het geheugen, in `_last_transmission_up` (`src/services/transmission.py:10`).
- `TransmissionService.is_available` (`src/services/transmission.py:30`) vangt elke exceptie af en schrijft alleen een `debug_call`. Met de requestregel (14, besluit 17) wordt dat een Fault. Zet `_last_transmission_up` dan op onbereikbaar voordat de Fault doorvalt.
- Beide scans heten `scan_missing_media` (`src/services/sonarr.py:45`, `src/services/radarr.py:45`).
- Per Gebruikersbericht schrijft de run nu een regel en stuurt hij een admin-melding "User notified" via `Log.logger(..., "info")` met `telegram=True` (`src/commands/schedule.py:120`, `:187`, `:241`). Die admin-melding blijft (Out of scope op de map) en schrijft voortaan `admin_message_sent`.
- `check_requirements` (`src/commands/schedule.py:305`) slaat een item zonder data (`:311`) of zonder map (`:329`) over, zonder regel.
- `notify_admin_startup` stuurt naar `CHAT_ID_GROUP`, ook in dev (`src/bot.py:288`). Admin-meldingen gaan in dev naar `CHAT_ID_ADMIN` (`src/log.py:100`).
