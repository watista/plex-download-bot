# 09 Requestregel met Radarr en Sonarr

Status: bezig (branch `logging/09-requestregel-arr`, sinds 2026-11-04)
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

## Aanwijzingen

- `ArrClient.get()` staat in `src/services/arr.py:55-125`. De drie meldingen bij een diskspace-fout komen van `arr.py:195`, `src/commands/media.py:444` en `:413`.
- `log_missing_path` telt een serie nu twee keer per run.
- Radarr en Sonarr krijgen de apikey via `params` (`arr.py:55`, `:129`).
