# 10 Plex en Transmission via de requestregel

Status: dicht
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

## Besluiten bij de uitvoering

Genomen op 2026-11-04, waar de issue en de spec niets zeggen. De eerste drie veranderen wat de bot doet, en zijn het nakijken het meest waard.

- **`check_transmission` draait ook bij de start** (`first=0`), net als de check nu vooraan in `check_notify_list`. De tabel in [7. Geplande taken](../spec.md#7-geplande-taken) zegt alleen "elke 30 minuten". Bij de start weet de bot zo meteen of Transmission onbereikbaar is: de scans bij de start lopen dan vast, en de volgende run start de zoekacties opnieuw als hij weer bereikbaar is. Een Storing van twee runs krijgt zo na 30 minuten een melding, niet pas na een uur.
- **De check na een aanvraag in `media_option` is weg.** Hij kon alleen zwijgend afvangen, wat niet meer mag ([Afvangen](../spec.md#afvangen), punt 5), en startte maar één van de twee zoekacties. Het herstel van Transmission valt nu alleen de job op, dus hooguit 30 minuten later.
- **`media_option` gaat door zonder de torrents van Transmission.** Een Fault van `get_active_torrents` wordt gemeld met `continued="went on without the torrents in Transmission"`. De aanvraag gaat naar Radarr of Sonarr, en de Gebruiker hoort dat er nog geen ruimte is (`no_space`), zoals voorheen.
- **De Plex-link wordt afgevangen in `Plex.link`**, de vangplek van alle vier de aanroepers (`check_notify_list` drie keer, `media_option` bij "al gedownload"). Daar wordt ook een onverwachte exceptie een Bug ("Making a Plex link failed"), ook een die niet uit plexapi komt, zodat het antwoord altijd uitgaat.
- **Een verkeerde Plex-URL**: bij het verbinden vraagt de bot alleen de root van Plex op. Een URL die requests niet kan gebruiken, een HTTP-fout die geen Storing en geen 401 is, of een antwoord dat geen XML is, is daarom de Inrichtingsfout `setting` met `PLEX_URL`. Een ontbrekende instelling is de Inrichtingsfout van die instelling (`PLEX_URL` of `PLEX_API`), zonder request. Een 401 is via de requestregel `PLEX_API`, net als bij Radarr en Sonarr. Na een geslaagde verbinding volgt `fixed` voor beide.
- **Een bibliotheek die niet bestaat** (`NotFound: Invalid library section: Movies`) is een Bug, als onverwachte exceptie bij de link. De namen "Movies" en "TV Shows" staan vast in de code.
- **Na een mislukte verbinding wacht de client 5 minuten**, zoals voorheen, omdat plexapi synchroon is. In die tijd komt er geen link, geen request en dus ook geen poging van de Storing, alleen een DEBUG-regel.
- **Media zonder titel** is de Inrichtingsfout `media_title` van Radarr of Sonarr, met het tmdb-ID als `item`: de titel komt daarvandaan. Met een titel volgt `fixed`.
- **Geen Plex-match** is WARNING, "no match in Plex for 'Dune' in Movies", met de media-velden, zonder `event`.
- **Transmission**: een 401 of 403 is de Inrichtingsfout `setting` met als `item` "TRANSMISSION_USER and TRANSMISSION_PWD", want Transmission zegt niet welke van de twee hij weigert. Elke andere `TransmissionError` is een Bug. transmission-rpc geeft geen HTTP-status door, behalve bij 401, 403 en 409. Een 5xx van iets vóór Transmission wordt daardoor een antwoord dat geen JSON is, en dus ook een Bug, geen Storing.
- **De interface**: `is_available` heet `check()` en geeft niets terug, en `get_active_torrents()` geeft alleen de torrents. Beide gooien hun Fault. `Plex(faults)` en `TransmissionService(faults)` krijgen de meldfunctie in plaats van `Log`.
- **De tijdelijke vangst uit 09 is weg.** Mislukt een zoekactie na `transmission_back`, dan valt de Fault door naar `guard_job`.

## Aanwijzingen

- Nu vangen `src/services/plex.py:46`, `:93`, `:113`, `:119` en `src/services/transmission.py:37`, `:51`, `:102` zelf `Exception` af. `src/commands/schedule.py:48-55` slikt een fout van Transmission in.
- plexapi en transmission-rpc zijn synchroon. Dat de event loop tijdens zo'n request stilstaat, laat deze issue zoals het is.
- transmission-rpc logt op DEBUG `gebruiker:wachtwoord@` in de URL. Het filter uit 01 maskeert dat.
