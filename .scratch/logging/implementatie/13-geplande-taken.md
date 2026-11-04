# 13 Geplande taken

Status: dicht
Blocked by: 09, 10
Niet tegelijk met: –

## Wat

Elke run eindigt met een regel, en `check_notify_list` laat per item zien wat hij vond.

- **`tally(name, n=1)`** in `src/interaction.py` houdt tellingen bij in de context van de run.
- **`guard_job` schrijft in een `finally` `job_finished`**:
  - op INFO, met `outcome` (`ok` of `stopped`), `duration_ms` en de tellingen
  - ook na een stop, met de tellingen tot dat moment
  - `msg` zoals "check_notify_list finished in 4.2 s: 14 items checked, 2 messages sent", "check_notify_list stopped after 1.2 s: …", "check_transmission finished in 0.2 s: Transmission reachable" en "scan_missing_sonarr finished in 0.3 s: missing search started"
  - een telling van 0 staat erin als `0`
- **Tellen**:
  - `send_user_message` telt `sent` en `not_delivered`
  - `check_notify_list` telt `items` en `skipped` (overgeslagen door een Inrichtingsfout)
- **`notify_check` op DEBUG**, één per gecontroleerd item:
  - `kind`: `online`, `new_season` of `new_episodes`
  - de media-velden uit `working_on(item)`
  - `user_id` en `account` van de ontvanger, als keywords op de regel en niet in de context
  - `outcome`: `no_data`, `no_folder`, `seasons_missing` (met `missing`), `empty_folder`, `nothing_new` of `sent`
- Het bijwerken van `data.json` krijgt geen eigen regel.

## Spec

- [7. Geplande taken](../spec.md#7-geplande-taken)
- [De Interactie en de wrappers](../spec.md#de-interactie-en-de-wrappers), punt 18 en 20

## Klaar als

- [x] Elke run in het hoofdbestand eindigt met precies één `job_finished`.
- [x] Tests:
  - `job_finished` na een geslaagde run en na een stop, met de tellingen tot dan
  - een Inrichtingsfout voor één item verhoogt `skipped`, en de run gaat door
  - `notify_check` heeft de gebruikersvelden op de regel, en een Fout tijdens dat item heeft ze niet

## Besluiten bij de uitvoering

Genomen op 2026-11-04, waar de issue en de spec niets zeggen. De eerste twee zijn het nakijken het meest waard.

- **`outcome: sent` betekent dat het bericht verstuurd is, niet dat het aankwam.** De uitkomsten hebben geen eigen waarde voor een bericht dat niet aankomt (`Forbidden`). Dat staat in de regel `user_message` op WARNING en in de telling `not_delivered`, en het item gaat van de lijst, zoals voorheen. De telling `sent` in `job_finished` telt wel alleen afgeleverde berichten, dus hetzelfde woord betekent op die twee plekken iets anders.
- **`no_data` is een item dat de run oversloeg door een Inrichtingsfout van dat item**: Radarr of Sonarr vindt niets of iets anders (`tmdb_lookup`), of het item heeft geen pad (`series_path`, `movie_path`). Sinds 09 kan een item alleen zo zonder gegevens zijn, dus `no_data` en `skipped` gaan altijd samen. Bij een item zonder pad staan de media-velden erbij, na een lege lookup alleen `tmdb_id`. `no_folder` is een pad waar (nog) geen map is.
- **Een overgeslagen item telt mee in `items`** en krijgt een regel `notify_check`. Een item dat een Storing of Bug onderbrak, telt niet mee en krijgt geen regel: `items` is altijd het aantal regels `notify_check`.
- **Een aflevering-abonnement dat nog niet begonnen is** (`started: false`: de serie is nog niet online) krijgt `nothing_new`. De lookup in Sonarr gaat eraan vooraf, zoals voorheen.
- **Een seriemap zonder bestanden met een seizoen of aflevering in de naam** krijgt bij `new_season` en `new_episodes` `empty_folder`, ook als er andere bestanden in staan.
- **`msg` van `job_finished` noemt alleen `items` en `sent`**, zoals in de voorbeelden van de spec. `not_delivered` en `skipped` staan alleen in de velden. Een run zonder items: "0 items checked, 0 messages sent".
- **Wat een job in `job_finished` zegt, staat bij het registreren in `src/bot.py`**: `counts=NOTIFY_COUNTS` voor `check_notify_list` (de tellingen en hun zinnen staan in `src/commands/schedule.py`), en `done=` met "Transmission reachable" of "missing search started" voor de andere. `done` komt alleen in een run die `ok` afliep, dus "check_transmission stopped after 0.2 s". Een telling die een run bijhoudt maar die de job niet registreerde, komt wel in de velden.
- **De tellingen zijn gedeeld met taken** die de run start (`create_task`), en `working_on` laat ze staan. In een update gaan ze nergens heen.
- **`job_finished` heeft `logger: interaction`** en `src` in `_job_finished`: de wrapper schrijft hem zelf.
- **Faalt de meldfunctie zelf**, dan volgt na `job_finished` nog de regel van `error_handler` met dezelfde Code. De run heeft nog steeds precies één `job_finished`, maar dat is dan niet zijn laatste regel.
- **De ontvanger in `notify_check`** komt uit de al gelezen `data.json`, via `account_in(data, user_id)` in `src/interaction.py`, met dezelfde regels als `account_for`. Een Bezoeker of een geblokkeerde gebruiker heeft alleen `user_id`.
- **`working_on` per item**: gezet zodra Radarr of Sonarr het item geeft, en leeggemaakt na de regel `notify_check`. Een Fout in de lookup van het volgende item gaat zo niet over het vorige.

## Aanwijzingen

- `check_requirements` (`src/commands/schedule.py:305`) slaat een item zonder data (`:311`) of zonder map (`:329`) nu stil over.
