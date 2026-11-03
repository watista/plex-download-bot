# 10 Plex en Transmission via de requestregel

Status: open
Blocked by: 09
Niet tegelijk met: 13 (`schedule.py`)

## Wat

Plex en Transmission gooien Faults via de requestregel, met 1 poging. De Transmission-check wordt een eigen job.

- **Plex**:
  - de excepties van plexapi worden omgezet in de client, via `call(…, retries=1)`
  - een ontbrekende of verkeerde Plex-URL of Plex-token is een Inrichtingsfout met `check: setting`
  - media zonder titel bij het maken van een link is een Inrichtingsfout
  - een onverwachte exceptie bij de link is een Bug, met één melding in plaats van twee
- **De Plex-link**: de aanroeper vangt een Fault lokaal af, meldt hem met `report(fault, continued="sent the answer without a Plex link")`, en het antwoord gaat zonder link uit.
- **Geen Plex-match voor een titel** is geen Fout, maar een logregel zonder `fault`. Het niveau is niet besloten; WARNING past bij "iets onverwachts dat geen Fout is".
- **Transmission**: de excepties van transmission-rpc worden omgezet in de client, voor `is_available` en `get_active_torrents`. De eigen `try/except`-blokken die zelf loggen, verdwijnen.
- **`check_transmission`** wordt een eigen job: elke 30 minuten, alleen in normal mode, met `name=` en `guard_job`.
  - Een Storing beëindigt alleen die run.
  - Is Transmission weer bereikbaar terwijl hij bij de vorige run onbereikbaar was, dan schrijft de run eerst `transmission_back` op INFO ("Transmission is back: starting the missing searches in Sonarr and Radarr") en start daarna de zoekacties.
  - `_last_transmission_up` gaat op onbereikbaar voordat de Fault doorvalt.
  - De check en zijn `try/except: pass` verdwijnen uit `check_notify_list`.

## Spec

- [Per geval](../spec.md#per-geval) (Plex en Transmission)
- [Afvangen](../spec.md#afvangen), punt 5
- [7. Geplande taken](../spec.md#7-geplande-taken), punt 6 en 7

## Klaar als

- [ ] `src/services/plex.py` en `src/services/transmission.py` vangen geen `Exception` meer af om zelf te loggen.
- [ ] Een test: Transmission onbereikbaar en daarna weer bereikbaar geeft `transmission_back` en start beide zoekacties. Na een herstart start de eerste run niets.
- [ ] Een test: een mislukte Plex-link geeft één `report()` met `continued`, en het antwoord gaat zonder link uit.

## Niet in deze issue

- `job_finished` voor `check_transmission`: 13

## Aanwijzingen

- Nu vangen `src/services/plex.py:46`, `:93`, `:113`, `:119` en `src/services/transmission.py:37`, `:51`, `:102` zelf `Exception` af. `src/commands/schedule.py:48-55` slikt een fout van Transmission in.
- plexapi en transmission-rpc zijn synchroon. Dat de event loop tijdens zo'n request stilstaat, laat deze issue zoals het is.
- transmission-rpc logt op DEBUG `gebruiker:wachtwoord@` in de URL. Het filter uit 01 maskeert dat.
