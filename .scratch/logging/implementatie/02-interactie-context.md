# 02 Interactie-context en Code

Status: open
Blocked by: 01
Niet tegelijk met: –

## Wat

Elke regel in een update of in een run van een job krijgt zijn context en een Code.

- **`src/interaction.py`**:
  - de contextvars
  - `new_code()`: 6 tekens uit `23456789abcdefghjkmnpqrstuvwxyz`
  - `current_code()`
- **`InteractionProcessor`**, een `BaseUpdateProcessor`:
  - zet per update `interaction_id`, `user_id`, en `account` (een Gebruiker) of `tg_name` (een Bezoeker), en reset ze in een `finally` met het `Token`
  - wordt ingesteld met `.concurrent_updates(InteractionProcessor(1))` in plaats van `.concurrent_updates(False)`
- **`account_for(user_id)`** leest de gebruikerslijst in `data.json`, niet de gespreksgegevens.
- **Een contextfilter** in `src/log/` zet de velden in elke regel, ook in die van libraries.
- **`guard_job(callback)`**, voor nu alleen de context: per run een nieuwe context met `interaction_id` en `job`, zonder gebruikersvelden.
- **Jobs registreren met `name=`**: `check_notify_list`, `scan_missing_sonarr`, `scan_missing_radarr`, `publish_command_list` en `notify_admin_startup`. De twee `run_once`-jobs krijgen hun coroutine direct, zonder lambda met `create_task`, zodat `guard_job` er later omheen kan.

## Spec

- [2. Interacties en Codes](../spec.md#2-interacties-en-codes)
- [7. Geplande taken](../spec.md#7-geplande-taken), punt 1
- [De Interactie en de wrappers](../spec.md#de-interactie-en-de-wrappers), punt 16

## Klaar als

- [ ] Elke regel uit een update heeft `interaction_id`, `user_id` en `account` of `tg_name`, ook de regels van libraries.
- [ ] Elke regel uit een run heeft `interaction_id` en `job`, zonder gebruikersvelden.
- [ ] Regels bij het opstarten en pollen hebben geen `interaction_id`.
- [ ] Tests:
  - de context wordt na elke update gereset
  - een job krijgt zijn eigen context, niet die van de laatste update
  - een Code heeft de goede vorm
  - een Bezoeker krijgt `tg_name` en geen `account`

## Niet in deze issue

- Fouten afvangen in `guard_job`: 07
- `working_on`: 06
- `tally` en `job_finished`: 13

## Aanwijzingen

- Jobs erven de context niet betrouwbaar: APScheduler start een job vanuit de context van wie de scheduler het laatst wekte (01).
- De jobs staan in `src/bot.py:119-126`.
- De gebruikerslijst staat in `data.json` onder `user_id`, als "accountnaam, Telegram-naam".
