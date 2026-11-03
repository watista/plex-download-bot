# Welke logregels schrijft een run van een geplande taak?

Type: grilling
Status: open
Blocked by: 08, 11

## Question

Welke logregels schrijft een run van een geplande taak, behalve Gebruikersberichten en Fouten, en op welk niveau?

Te beslissen:

- Of een run een regel aan het begin en aan het eind krijgt, of één samenvatting (bijvoorbeeld "checked 14 items, 2 online"), en op welk niveau. Live draait op INFO.
- Welke tussenstappen per job een regel worden, en op welk niveau. Het gaat om `check_notify_list` (elke 30 minuten), `scan_missing_media` voor Sonarr en voor Radarr (elke 6 uur), en de jobs die eenmalig bij de start draaien (`publish_command_list`, `notify_admin_startup`). Ze worden geregistreerd in `src/bot.py:119-126`.
- Of een run zonder resultaat (niets online, niets ontbrekend) een regel schrijft. Elke 30 minuten is 48 runs per dag.

Uit 06: INFO staat voor de normale gang van zaken en DEBUG voor details. Een Storing is WARNING, een Bug of Inrichtingsfout ERROR.

Uit 08: elke run is een Interactie met een eigen `interaction_id` en een veld `job`, zonder velden van een gebruiker. Een run waarin de bot meerdere gebruikers bedient, houdt één ID.

Uit 11: elk Gebruikersbericht krijgt een eigen regel `user_message` met de ontvanger, ook binnen een job-run, en een mislukte aflevering wordt WARNING. `/log <code>` toont van een run alle regels van INFO en hoger. Wat een run schrijft, bepaalt dus wat de Beheerder ziet als hij de code uit een admin-melding over een job opvraagt.

Uit 12: regels van libraries komen pas vanaf WARNING in het hoofdbestand. apscheduler schrijft daar dus geen regel per run, en een run is in het hoofdbestand alleen zichtbaar via de eigen regels die dit ticket bepaalt.

Uit 14:
- `guard_job` geeft elke run een eigen context met `interaction_id` en `job`. De run schrijft zijn regels met `get_logger(__name__)` en velden als keywords.
- Een Gebruikersbericht gaat via `send_user_message`, die zelf de regel `user_message` schrijft.
- Elke request naar een dienst schrijft via de requestregel al een `http_call` op DEBUG.
- Als een controle in een run slaagt, laat de run dat weten met `faults.fixed()`.
- De heartbeat is geen job. Hij loopt via `guard_task` en valt buiten deze vraag.
