# Hoe koppelen we logregels van één interactie, en een melding aan de logregel?

Type: grilling
Status: resolved
Blocked by: 01, 06
Assignee: Wouter

## Question

Hoe koppelen we alle logregels van één interactie aan elkaar, en hoe vind je vanuit een foutmelding of admin-melding de bijbehorende logregels terug?

Te beslissen:

- Waarop een interactie-ID slaat: één update, of een hele conversatie (bijv. zoeken → kiezen → aanvragen).
- Of er een fout-ID komt, en waar die zichtbaar is: in de foutmelding aan de gebruiker, in de admin-melding, of beide.
- Vorm van het ID (kort genoeg om over te typen, uniek genoeg om te vinden).
- Hoe dit werkt voor geplande taken, waar geen gebruiker bij is.

Uit 06: het veld heet `interaction_id` en staat in elke regel waar het een waarde heeft, ook in regels van libraries (via de contextvars uit 01).

## Answer

Besloten in een grilling met de beheerder op 2026-11-03, in twee rondes. Nieuw begrip in `CONTEXT.md`: **Interactie**.

### Besluiten

1. **`interaction_id` slaat op één Interactie**: één update (één Gebruikersactie plus de afhandeling ervan, inclusief regels van libraries en `create_task`-taken), of één run van een geplande taak. Er komt geen ID per Gesprek: een Gebruiker heeft één Gesprek tegelijk, dus `user_id` plus de tijd vindt een Gesprek al terug. Het ID wordt gezet en gereset in de `BaseUpdateProcessor` uit 01.
2. **Geen apart fout-ID.** Een Fout hoort bij de Interactie waarin hij ontstond. Het `interaction_id` staat in de admin-melding én in de Foutmelding, zodat één `grep` de hele aanloep toont, niet alleen de foutregel.
3. **Vorm**: 6 willekeurige tekens, kleine letters en cijfers zonder tekens die op elkaar lijken (alfabet `23456789abcdefghjkmnpqrstuvwxyz`, dus geen `0 o 1 l i`), bijvoorbeeld `k7p2qx`. Dat zijn ongeveer 887 miljoen combinaties, ruim genoeg bij tientallen Interacties per dag zonder dat er iets verwijderd wordt.
4. **Geplande taken**: elke run van een job krijgt een eigen `interaction_id` en een nieuw veld `job` met de naam van de job (bijv. `check_notify_list`), zonder velden van een gebruiker. Volgens 01 moet de job die context zelf zetten. Eén run waarin de bot meerdere gebruikers bedient, houdt één ID.
5. **Regels buiten een update of job** (opstarten, polling-fouten, de heartbeat) hebben geen `interaction_id`; het veld wordt weggelaten (06).
6. **Melding over meerdere Interacties**:
   - Een **Storing** die aanhoudt: de admin-melding toont het ID van de **eerste** mislukte poging, waar de Storing begon.
   - Een **Herstelmelding** toont hetzelfde ID als de melding van de Storing, plus het ID van de eerste geslaagde poging.
   - Een afgeremde **Inrichtingsfout**: het ID van de run die de melding uitlokte.
7. **Foutmelding**: de code staat er altijd in, ook als er (nog) geen admin-melding uitgaat, als laatste regel `Code: k7p2qx`. In de gebruikerstekst heet het "code", niet "foutcode".
8. **Meerdere Fouten in één Interactie** delen hetzelfde ID, zonder volgnummer. `grep` toont ze op volgorde.

### Veld erbij (aanvulling op 06)

| Veld | Wanneer | Inhoud |
|---|---|---|
| `interaction_id` | in een Interactie | 6 tekens, zie besluit 3 |
| `job` | bij een run van een geplande taak | naam van de job, bijv. `check_notify_list` |

`job` staat direct na `interaction_id`.

### Feiten uit de code (voor de implementatie)

- De Foutmeldingen staan nu als losse teksten in de handlers: `src/commands/media.py:422`, `:430`, `src/commands/serie.py:194`, `src/commands/subscribe.py:115`. Ze gaan via `send_message()` in `src/functions.py` (MarkdownV2).
- Jobs worden geregistreerd in `src/bot.py:119-126` (`run_once` bij de start, `run_repeating` voor de notify-check en de scans).

### Doorgeschoven

- Of `/log` het ID per regel toont: [Wat toont /log <gebruiker>, en voor wie?](11-log-command.md)
- Waar het ID in de admin-melding staat en hoe het eruitziet: [Hoe ziet een admin-melding bij een fout eruit?](10-admin-melding-bij-fout.md)
- Of het ID van het begin van een Storing een herstart overleeft: [Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?](13-herhaalde-fouten-afremmen.md)
- Wie de Foutmelding met de code stuurt (lokaal of centraal): [Waar vangen we excepties af: lokaal of centraal?](09-excepties-lokaal-of-centraal.md)
