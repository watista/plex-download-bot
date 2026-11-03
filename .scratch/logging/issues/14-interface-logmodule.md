# Welke interface krijgt de logmodule?

Type: grilling
Status: open
Blocked by: 10, 12, 13

## Question

Welke interface vervangt `Log.logger()` en `Log.debug_call()` (`src/log.py`) voor logregels, gebruikersacties, Fouten en admin-meldingen, en waar liggen de seams?

Skills: naast grilling en domain-modeling ook codebase-design.

Wat al vaststaat:

- Uit 05: de soort Fout wordt op één plek bepaald uit het antwoord van de dienst. Een admin-melding die Telegram weigert, moet alsnog aankomen (opnieuw als platte tekst).
- Uit 06: `logger` en `src` komen van de aanroeper, niet van de wrapper. `debug_call` wordt een `http_call`-regel, en een traceback gaat in het veld `exc` in plaats van in de tekst.
- Uit 07: een eigen handler kiest per regel het dagbestand, en `LOG_TYPE` kent alleen nog `INFO` en `DEBUG`.
- Uit 08: de `BaseUpdateProcessor` zet `interaction_id` per update, en een job-wrapper zet `interaction_id` en `job` per run.
- Uit 09: er is één klasse `Fout` met `soort`, dienst, reden en de oorspronkelijke exceptie, plus een optionele zin voor de Foutmelding. Eén meldfunctie wordt gebruikt door de wrapper, door plekken die melden en doorwerken, en door `error_handler`. De wrapper komt bij het registreren in `src/bot.py` om elke callback, en geeft in een Gesprek `END` terug. Elke requestfunctie van een dienst zet een antwoord om via één gedeelde HTTP-regel. De Foutmelding belooft alleen een admin-melding die echt uitging, dus de meldfunctie moet de wrapper laten weten of hij er een verstuurde.
- Uit 10: de admin-melding is HTML en Engels, en altijd één bericht van hooguit 4096 tekens. Naast de velden van de `Fout` uit 09 heeft hij nodig:
  - het media-item: titel, jaar, tmdb- of tvdb-ID, plus wat nodig is voor de link naar Sonarr of Radarr
  - de velden waarop de beslissing viel
  - bij melden en doorwerken een zin voor `Continued:`
  - of de Gebruiker een Foutmelding kreeg
  - de eigen frames uit de traceback

  Weigert Telegram de opmaak, dan stuurt de meldfunctie de melding één keer opnieuw als platte tekst, met een waarschuwingsregel, en logt hij de weigering als Bug zonder eigen melding. Tijdens een Telegram-storing houdt hij bij welke meldingen niet aankwamen. Een Herstelmelding gaat stil uit. De opbouw staat in 10.

- Uit 11: `/log` leest de dagbestanden achterwaarts en zoekt op een persoon (een accountnaam met de bijbehorende user ID's uit de gebruikerslijst, of één user ID) of op een code. Om te bladeren zit de positie in de knop. Elk Gebruikersbericht schrijft een regel `user_message` met de ontvanger, ook vanuit een job. Beslis hier ook of de lezer van `/log` een eigen module met eigen tests wordt.
- Uit 12: het hoofdbestand en de console onderscheiden eigen code van libraries aan de naam van de logger. Elke logger buiten die van de bot telt als library en komt pas vanaf WARNING binnen; het debug-bestand krijgt alles. Eén filter maskeert de geheimen uit dot-env (bot-tokens, API-keys, het Transmission-wachtwoord) in elke logregel, en de meldfunctie maskeert ze op dezelfde manier in alles wat hij naar Telegram stuurt. Na de logging-setup komen `logging.captureWarnings(True)` en een `sys.excepthook` die een regel `bot_crashed` schrijft. De heartbeat-taak (`asyncio.create_task` in `_post_init`, `src/bot.py`) is geen handler en geen job, maar krijgt dezelfde wrapper; nu stopt hij bij een onverwachte exceptie zonder enige regel.
- Uit 13:
  - **Toestand**: de meldfunctie houdt de toestand bij in `faults.json` (dev: `faults.dev.json`, per host), zodat die een herstart overleeft. Het gaat om open Storingen, de stand per Inrichtingsfout, de laatste melding per Bug-handtekening en de lijst `Not sent meanwhile`.
  - **Beslissen**: bij elke Fout beslist de meldfunctie of er een melding, een Herinnering of niets uitgaat, en de aanroeper hoort of er voor deze Fout een melding uit is.
  - **Sleutels**: een Inrichtingsfout heeft een sleutel (dienst + reden + item of instelling), een Bug een handtekening (dienst, type exceptie, binnenste eigen frame, bij een 4xx de statuscode).
  - **Controle slaagt**: een geslaagde controle moet de meldfunctie dat kunnen laten weten. Dat beëindigt een Storing (bij elk geslaagd antwoord van de dienst) of zet een Inrichtingsfout recht, met een Herstelmelding als er een melding uitging.
  - **Crash**: de `sys.excepthook` gebruikt dezelfde toestand en verstuurt bij een Bug zelf synchroon een melding.
  - **Logregels**: de logregel van een Fout is volledig bij de eerste keer en bij een melding. Daartussen is hij kort, met `repeat: n`.

  Te beslissen hier: welke code de melding over een crash toont, die buiten een Interactie valt.

Te beslissen: de vorm van `Fout` en de meldfunctie, wat de meldfunctie teruggeeft, hoe een aanroeper een logregel of gebruikersactie schrijft, en welke van deze stukken aparte modules zijn met hun eigen tests.
