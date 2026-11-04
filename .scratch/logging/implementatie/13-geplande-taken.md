# 13 Geplande taken

Status: bezig (branch `logging/13-geplande-taken`, sinds 2026-11-04)
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

- [ ] Elke run in het hoofdbestand eindigt met precies één `job_finished`.
- [ ] Tests:
  - `job_finished` na een geslaagde run en na een stop, met de tellingen tot dan
  - een Inrichtingsfout voor één item verhoogt `skipped`, en de run gaat door
  - `notify_check` heeft de gebruikersvelden op de regel, en een Fout tijdens dat item heeft ze niet

## Aanwijzingen

- `check_requirements` (`src/commands/schedule.py:305`) slaat een item zonder data (`:311`) of zonder map (`:329`) nu stil over.
