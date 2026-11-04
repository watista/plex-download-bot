# 14 /log

Status: bezig (branch `logging/14-log-command`, sinds 2026-11-04)
Blocked by: 02
Niet tegelijk met: 05, 07 (`src/bot.py`)

## Wat

Het command `/log` voor de Beheerder, met een eigen loglezer. Het werkt vanaf 02, maar is pas echt nuttig als 03, 04 en 05 er zijn.

- **`src/log/search.py`**: `search(query, before=None)` geeft regels van nieuw naar oud, elk met een positie (datum van het bestand plus byte-offset).
  - `query` is een set user ID's plus een accountnaam, of een Code
  - leest de `.jsonl`-bestanden binair en achterwaarts in blokken
  - doet eerst een substring-check, en pas daarna `json.loads`
  - draait in `asyncio.to_thread`
  - slaat een halve laatste regel over
- **`src/commands/log.py`**, een losse handler en geen entry point van de ConversationHandler:
  - **Wie en waar**: alleen `allowed_users`, alleen in de privéchat. Anders volgt een regel `ignored` en geen reactie. Het command komt niet in `publish_command_list`.
  - **Argument**, herkend in deze volgorde: cijfers (user ID), accountnaam (hoofdletterongevoelig, met de user ID's uit de gebruikerslijst), de vorm van een Code. Zonder argument volgt een korte uitleg.
  - **Bij een persoon**: INFO en hoger, zonder regels van libraries. Fouten kort, met de code.
  - **Bij een code**: de hele Interactie, ook regels van libraries, zonder traceback, met de `grep`-tip onderaan.
  - **Eén HTML-bericht per keer**, met de knoppen "⬅️ Earlier" en "Later ➡️". De positie zit in `callback_data` (hooguit 64 bytes), en alleen `allowed_users` kunnen de knoppen indrukken.
  - **Opmaak**: zie de spec (kop, groeperen per dag, gedeeld account, afkappen op 200 tekens, voettekst met host, de teksten als er niets gevonden is).
  - schrijft `admin_command` met het argument

## Spec

- [11. `/log`](../spec.md#11-log)
- De rijen "Loglezer" en "`/log`" in [Modules](../spec.md#modules)

## Klaar als

- [ ] Tests voor de gevallen onder "Loglezer" en "`/log`" in [Tests](../spec.md#tests):
  - zoeken over meerdere dagen, een halve laatste regel en een gedeeld account
  - de volgorde bij het herkennen: cijfers, dan accountnaam, dan Code (het geval "sander")
  - groeperen per dag, afkappen op 200 tekens
  - de teksten als er niets gevonden is
- [ ] Op dev bladert `/log <eigen accountnaam>` terug over twee dagbestanden heen.
