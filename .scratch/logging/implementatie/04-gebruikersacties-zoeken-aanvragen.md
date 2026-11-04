# 04 Gebruikersacties: zoeken en aanvragen

Status: bezig (branch `logging/04-gebruikersacties-zoeken-aanvragen`, sinds 2026-11-04)
Blocked by: 03
Niet tegelijk met: 07, 09 (dezelfde handlers in `media.py`, `serie.py` en `subscribe.py`)

## Wat

Regels voor de Gebruikersacties rond zoeken en aanvragen, in `src/commands/media.py`, `movie.py`, `serie.py` en `subscribe.py`:

| `event` | Gegevens | Uitkomst |
|---|---|---|
| `search_term` | zoekterm letterlijk + waarvoor | aantal resultaten |
| `search_button` | welke knop | – |
| `media_request` | optienummer, `media=` | download gestart / al gedownload / nog niet uit / geen downloadmatch / unmonitored / geen ruimte / fout |
| `notify_choice` | keuze | – |
| `quality_request` | reden, tekst letterlijk | – |
| `series_updates` | `media=` | aangemeld / afgemeld / niets om af te melden / geen resultaten |

- `msg` beschrijft de actie naar betekenis ("chose option 3: Dune (2021): already added").
- Media worden aangeduid met titel, jaar en tmdbId, niet met tvdbId.
- De admin-berichten in deze bestanden die geen fout zijn, gaan via `send_admin_message`: "User has requested", het kwaliteitsverzoek, aan- en afmelden voor een serie en unmonitored. Hun tekst komt niet meer in het log.
- Meldingen over Fouten (`❌ …`, "see the logs") blijven voor 07 en 09.

## Spec

- [5. Gebruikersacties](../spec.md#5-gebruikersacties)
- [Soortnamen](../spec.md#soortnamen-event) en [Nooit in een logregel](../spec.md#nooit-in-een-logregel)

## Klaar als

- [ ] Een aanvraag van zoeken tot keuze levert op dev de regels uit de catalogus op, elk met `user_id`, `account`, `event` en `outcome` waar dat kan.
- [ ] Waar `tests/test_movie_states.py` de handler al aanroept, controleert een test de regel `media_request` met zijn uitkomst.

## Niet in deze issue

- De andere soorten Gebruikersactie: 05
- Fouten in deze handlers: 07, 09

## Aanwijzingen

- Nu niet gelogd: de zoekterm (`src/commands/media.py:60`).
- De admin-berichten staan onder meer op `media.py:236`, `:257`, `:293`, `movie.py:152`, `:160`, `serie.py:174`, `:234` en `subscribe.py:147`, `:214`.
