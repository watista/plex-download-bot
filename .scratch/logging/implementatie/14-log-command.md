# 14 /log

Status: dicht
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

- [x] Tests voor de gevallen onder "Loglezer" en "`/log`" in [Tests](../spec.md#tests):
  - zoeken over meerdere dagen, een halve laatste regel en een gedeeld account
  - de volgorde bij het herkennen: cijfers, dan accountnaam, dan Code (het geval "sander")
  - groeperen per dag, afkappen op 200 tekens
  - de teksten als er niets gevonden is
- [ ] Op dev bladert `/log <eigen accountnaam>` terug over twee dagbestanden heen.

## Besluiten bij de uitvoering

Genomen op 2026-11-04, waar de issue en de spec niets zeggen. De eerste twee veranderen een interface uit de spec. Ze zijn na de review voorgelegd en besloten op 2026-11-04, en bijgewerkt in de spec ([11. `/log`](../spec.md#lezen), punt 12, [Telegram](../spec.md#telegram), punt 11, en de rijen "Loglezer" en "Verzendfunctie" in [Modules](../spec.md#modules)).

- **`search` kreeg `after`**: `search(folder, env, query, before=None, after=None)` in `src/log/search.py`. "Later ➡️" heeft de regels ná een positie nodig, en een knop draagt maar één positie, dus met alleen `before` kan het niet. Ook `after` leest achterwaarts, en stopt bij die positie. `folder` en `env` gaan mee, want de lezer heeft geen toestand op moduleniveau. Komt "Later" bij de nieuwste regels uit, dan toont hij de nieuwste pagina, net als `/log` zelf.
- **De verzendfunctie stuurt ook de pagina's van `/log`.** `send` kreeg `markup` (de knoppen) en `edit` (het bericht dat een pagina vervangt). Zo gaat een pagina die Telegram weigert, opnieuw als platte tekst met de regel ⚠️ en een Bug-regel, zonder een kopie van die code in `/log`. `send` kapt nu af op 4096 tekens zoals Telegram ze telt, in UTF-16, zonder een emoji te halveren.
- **Herkennen**: alleen cijfers is een user ID, ook als het de vorm van een Code heeft. Een naam die niet in de gebruikerslijst staat, zoekt eerst op het veld `account` in de logs (hoofdletterongevoelig). Is er niets, en heeft hij de vorm van een Code, dan is het een Code. Een Code mag in hoofdletters.
- **De gebruikerslijst**: alle user ID's van een account tellen mee, ook een geblokkeerde.
- **Regels van libraries** herkent `/log` aan de logger, net als de setup: een eigen logger noemt een module van de bot (het veld `logger` laat `src.` weg). Een regel met `event` of `fault` is altijd eigen.
- **Een Code** zoekt terug tot het eerste oudere bestand zonder die Code. Een Interactie kan over middernacht lopen, maar is daarna voorbij.
- **De host** is `socket.gethostname()`. De bestanden zijn altijd die van de machine zelf, ook op dev, en dat zeggen `PRIMARY_NAME` en `FALLBACK_NAME` niet altijd.
- **Een pagina** vult tot 4096 tekens met de tags erbij, zoals de admin-melding. Zo kapt de verzendfunctie een pagina nooit af, en heeft de platte tekst na een weigering ruimte voor de regel ⚠️.
- **Opmaak**:
  - De kop is `📋 <b>wouter</b>`, of bij een Bezoeker `📋 <b>777 (Piet)</b>`. Bij een Code is het `📋 Code <code>k7p2qx</code> · wouter`, of `· check_notify_list` bij een job.
  - Een regel van een Fout ziet eruit als `⚠️ <b>14:06</b> Bug · radarr: <reden> <code>k7p2qx</code>`, met `msg` als er geen reden is. `admin_message_sent` heeft ook `fault`, maar is geen regel van een Fout.
  - Bij een Code komt `(ExcType)` achter de tekst, tenzij het type er al in staat.
  - Bij een gedeeld account krijgt de kop een tweede regel `Wouter: 1 · Sanne: 3`, en elke regel begint met de Telegram-naam (`Sanne: …`).
  - Onderaan staat bij een Code eerst `Traceback over SSH: grep k7p2qx`, en altijd `Logs on <host> since <dag>`.
  - De dagkop ("Mon 7 Dec") is Engels, ongeacht de locale van de host.
- **De knoppen**: `callback_data` is `log:<e|l>:<p|c>:<JJJJMMDD>:<offset>:<argument>`. Wordt dat langer dan 64 bytes (een argument van meer dan zo'n 40 bytes), dan komen er geen knoppen. Een dubbele druk ("Message is not modified") laat de pagina staan.
- **Elke druk op een knop** schrijft een regel `admin_command` met `button: earlier` of `later`, want een knopdruk is een Gebruikersactie ([5. Gebruikersacties](../spec.md#uitgangspunten), punt 1).
- **Wie en waar**: `/log` of een knop van iemand anders, of `/log` in een groep, neemt de handler niet aan. Het vangnet maakt er een regel `ignored` van, met de stap van het Gesprek.
- De README noemt `/log`.

Nog te doen: de controle op dev (Klaar als, punt 2). Dat kan alleen de Beheerder.
