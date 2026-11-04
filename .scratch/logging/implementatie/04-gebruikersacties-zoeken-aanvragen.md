# 04 Gebruikersacties: zoeken en aanvragen

Status: dicht
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

## Besluiten bij de uitvoering

Voorgelegd en besloten op 2026-11-04, en bijgewerkt in de catalogus van de spec:

- **Zoeken om aan te melden** geeft één regel `search_term`, met `media_type: series` en `purpose: series_updates`. `results` is het aantal series dat je kunt kiezen (gedownload en nog niet afgelopen). `results: 0` staat voor "geen resultaten", dus er komt geen aparte regel `series_updates` met die uitkomst.
- **De uitkomsten van `media_request`**: `download_started`, `already_downloaded`, `not_released`, `no_download_match`, `unmonitored`, `no_space`, `failed`, plus `downloading` als het item al in Transmission staat. `unmonitored` geldt ook voor een serie met meer dan 5 seizoenen; die herken je aan het veld `seasons`. `failed` heet niet `error`, omdat `CONTEXT.md` "error" vermijdt.

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
