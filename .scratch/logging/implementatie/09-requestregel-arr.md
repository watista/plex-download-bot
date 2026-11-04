# 09 Requestregel met Radarr en Sonarr

Status: dicht
Blocked by: 07, 08
Niet tegelijk met: 04, 10, 13 (`media.py`, `serie.py`, `subscribe.py`, `schedule.py`)

## Wat

Radarr en Sonarr gooien Faults via één requestregel. De oude tellers en `last_error` verdwijnen.

- **`call(service, action, attempt, retries=3)`** in `src/services/request.py`:
  - schrijft per poging een `http_call` op DEBUG, zonder apikey in de URL en afgekapt op `LOG_MAX_BODY`
  - deelt antwoorden in volgens de tabel uit de spec: onbereikbaar, timeout of 5xx is een Storing; een 4xx is een Bug met de reden; 401 en 403 zijn een Inrichtingsfout
  - probeert het bij een Storing opnieuw en gooit de Fault pas na de laatste poging
  - roept bij succes `faults.ok(service)` aan
- **`ArrClient.get/post`** via `call`, met een omschrijving per request (`action="movie request"`). `faults` gaat mee in de constructor van de diensten.
- **De aanroepers** in `src/commands/` controleren geen `False`/`None` en `last_error` meer en sturen geen eigen meldingen. Een mislukte diskspace-check geeft zo één melding in plaats van drie.
- **Inrichtingsfouten** die de aanroeper ziet, met `Fault.setup`:

  | `check` | Wanneer | `item` |
  |---|---|---|
  | `tmdb_lookup` | de lookup slaagt maar levert niets op | tmdb-ID |
  | `series_path` | een serie zonder `path`, bij de geplande check en bij het aanmelden (`src/commands/serie.py:219` gooit nu zelf `KeyError`) | tvdb- of tmdb-ID |
  | `disk_space` | geen schijf met 150 GB vrij | – |
  | `setting` | een mediamap die bij geen schijf hoort | naam van de instelling |

  Slaagt dezelfde controle later, dan volgt `faults.fixed(...)`, bijvoorbeeld als een serie weer een pad heeft.
- **In `check_notify_list`** wordt een Inrichtingsfout voor één item gemeld, en slaat de run het item over. Een Storing of Bug beëindigt de run.
- **De link op de regel `Media:`** van de admin-melding wijst naar het item in Sonarr of Radarr. Kijk de vorm na; waarschijnlijk `/movie/<tmdbId>` en `/series/<titleSlug>`.
- **Wat verdwijnt**: `last_error`, `_lookup_failures` en `log_lookup_failure`, `_missing_path` en `log_missing_path`, en `LOOKUP_ALERT_THRESHOLD`, ook uit `dot-env.template`.

## Spec

- [Indeling](../spec.md#indeling) en [Per geval](../spec.md#per-geval)
- [De requestregel](../spec.md#de-requestregel)
- [Inrichtingsfouten](../spec.md#inrichtingsfouten)
- [7. Geplande taken](../spec.md#7-geplande-taken), punt 9

## Klaar als

- [ ] `grep -rn "last_error\|LOOKUP_ALERT_THRESHOLD" src dot-env.template` geeft niets.
- [ ] Tests voor de gevallen onder "Requestregel" in [Tests](../spec.md#tests):
  - 3 keer een 503 geeft één Storing, pas na de laatste poging
  - een 400 wordt een Bug met de reden (hooguit 300 tekens) en de status
  - 401 en 403 worden een Inrichtingsfout
  - na een geslaagd antwoord wordt `ok` één keer aangeroepen
  - elke poging krijgt een `http_call`, zonder apikey in de URL
- [ ] `tests/test_movie_states.py` en de andere tests zijn groen.

## Niet in deze issue

- Plex en Transmission: 10
- `skipped` tellen en `notify_check`: 13

## Besluiten bij de uitvoering

Genomen op 2026-11-04. Het eerste is voorgelegd en besloten op 2026-11-04.

- **Een serie zonder pad bij het aanmelden krijgt zijn pad uit het antwoord van Sonarr.** In de live-logs van oktober kwam "No Path is found in JSON" drie keer voor (Love is Blind NL, Carrie, Ascension), telkens vlak na een nieuwe aanvraag: de lookup in `media_data` is van vóór de serie in Sonarr stond. Als Inrichtingsfout zou elke nieuwe serie met updates een 🔧 Setup-melding geven. Daarom zet `start_download` het `path` uit het antwoord op de POST in `media_data`. Ontbreekt het pad bij het aanmelden dan nog, dan is het de Inrichtingsfout `series_path`, gemeld met `Continued:`, en gaat de aanmelding door vanaf S00E00. Met een pad volgt `fixed`.
- **De interface**: `call(service, action, attempt, faults, retries=3, *, method, url, request)`, met `faults` als parameter omdat er geen object op moduleniveau komt. `attempt` doet één poging en geeft een `Answer(status, body, reason)`. `method`, `url` en `request` zijn alleen voor de `http_call`. Onbereikbaar is een `aiohttp.ClientError`, `ConnectionError` of `TimeoutError`; plexapi en transmission-rpc zetten hun excepties in 10 daarin om. Elke andere exceptie valt ongewijzigd door, na zijn `http_call`.
- **401 en 403** zijn de Inrichtingsfout `setting` met als `item` de instelling met de sleutel (`RADARR_API`, `SONARR_API`): "Radarr does not accept RADARR_API". Elk geslaagd antwoord is ook een geslaagde controle van die sleutel, dus de requestregel roept daarna `fixed` aan.
- **De reden** komt van de dienst: de `errorMessage`s van een validatiefout, anders `message`, anders de tekst. Een HTML-pagina van een proxy is geen reden; dan wordt het de reden van de HTTP-status ("Bad Gateway"). De requestregel kapt elke reden af op 300 tekens.
- **`tmdb_lookup`** geldt ook als de lookup een andere film of serie teruggeeft (SkyHook), zoals de tabel in [Indeling](../spec.md#indeling) zegt. Het is dezelfde sleutel, dus dezelfde Fout. De dienst is `radarr` of `sonarr`, want de lookups lopen via hen. `lookup_by_tmdbid` geeft voortaan het item zelf terug, niet de lijst.
- **Een film zonder pad** in `check_notify_list` is net als een serie een Inrichtingsfout, met `check` `movie_path`. `log_missing_path` deed beide.
- **De mediamappen**: een map die bij geen schijf hoort, is de Inrichtingsfout `setting` (`MOVIE_FOLDERS` of `SERIE_FOLDERS`). Staan de andere mappen wel op een schijf, dan wordt hij gemeld met `Continued:` en zoekt de bot verder; anders, of zonder mappen, beëindigt hij de aanvraag. Geen schijf met 150 GB vrij is `disk_space`, met `user_text` "Er is op dit moment een probleem met de opslag van de Plęx server" en de vrije ruimte per schijf in `details`. Slaagt een controle, dan volgt `fixed`.
- **De zoekactie na een aanvraag** (`scan_missing_media` als `extra_action`): een Fout daarin wordt gemeld met `Continued:`, en de aanvraag gaat door. De download staat dan al in Radarr of Sonarr.
- **`/afmelden`**: mislukt de lookup voor de titel, dan wordt de Fout gemeld met `Continued:` en toont de knop "Serie <tmdb-ID>", zoals voorheen bij een lege lookup. Na een Storing zoekt hij de andere series niet meer op: één mislukte poging is genoeg, en anders wacht elke serie op zijn eigen 3 pogingen.
- **Alleen een Inrichtingsfout van het item zelf slaat het item over** in `check_notify_list` (`tmdb_lookup`, `series_path`, `movie_path`, met het tmdb-ID als `item`). Een sleutel die Radarr of Sonarr niet accepteert (401/403) is ook een Inrichtingsfout, maar elk volgend item loopt er weer tegenaan, dus die beëindigt de run.
- **`check_notify_list` schrijft `data.json` in een `finally`**, ook na een Storing of Bug die de run beëindigt. Anders krijgt wie eerder in die run een Gebruikersbericht kreeg, het de volgende run opnieuw. De admin-meldingen "User notified" van een gestopte run gaan niet uit; de regel `user_message` staat er wel.
- **De link op `Media:`**: uit de live-logs is Radarrs `titleSlug` het tmdbId (`'1314481'`) en die van Sonarr een slug (`'carrie'`). De link is `/movie/<titleSlug of tmdbId>` of `/series/<titleSlug>` op `RADARR_URL` of `SONARR_URL` zonder `/api/v3`. `FaultReporter` krijgt `media_link` mee uit `src/services/arr.py`. Of het item er bestaat, zegt zijn `id` in Radarr of Sonarr: een lookup vindt ook wat er nog niet in staat, zonder `id`. Daarvoor bewaart `media_item` nu ook `id` en `titleSlug`. KPop Demon Hunters, de film van "already added" in oktober, had in de lookup wel een `id` (412).
- **`service_name` en `cut_reason`** in `src/faults.py` zijn openbaar geworden, voor de requestregel. `BotLogger` heeft `enabled_for(level)`, zodat de `http_call` op INFO geen bodies opbouwt.

Tijdelijk, tot 13: `check_transmission_and_trigger_scans` (`src/services/transmission.py`) vangt elke exceptie van de zoekacties na het herstel van Transmission af en schrijft alleen een WARNING via de oude `Log`. Een Fault daar bereikt de meldfunctie dus niet, terwijl `scan_missing_media` vroeger zelf een melding stuurde. In 13 wordt `check_transmission` een eigen job en valt de Fault door ([7. Geplande taken](../spec.md#7-geplande-taken), punt 7).

`LOOKUP_ALERT_THRESHOLD` doet niets meer; hij kan ook uit de eigen `dot-env`.

## Aanwijzingen

- `ArrClient.get()` staat in `src/services/arr.py:55-125`. De drie meldingen bij een diskspace-fout komen van `arr.py:195`, `src/commands/media.py:444` en `:413`.
- `log_missing_path` telt een serie nu twee keer per run.
- Radarr en Sonarr krijgen de apikey via `params` (`arr.py:55`, `:129`).
