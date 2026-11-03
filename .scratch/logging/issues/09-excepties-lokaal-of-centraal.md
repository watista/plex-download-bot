# Waar vangen we excepties af: lokaal of centraal?

Type: grilling
Status: resolved
Blocked by: 01
Assignee: Wouter

## Question

Vangen we excepties lokaal af per handler (loggen en doorgaan, zoals nu), of laten we ze doorvallen naar één centrale plek die de logregel schrijft, de gebruiker een foutmelding stuurt en een admin-melding verstuurt?

Context: de `error_handler` in `src/bot.py` vangt nu alleen wat nergens anders wordt afgevangen. Veel `try/except`-blokken in `src/commands/*` en `src/services/*` loggen en gaan door, en de services geven fouten terug via `last_error` in plaats van een exceptie. Daardoor raakt vaak verloren waar een fout ontstond.

Uit 05: één Fout geeft hooguit één admin-melding, en de soort (Bug, Storing, Inrichtingsfout) volgt uit het antwoord van de dienst. Nu stuurt een mislukte diskspace-check er nog drie. Dit ticket beslist waar die ene melding en de indeling plaatsvinden.

Skills: naast grilling en domain-modeling ook codebase-design.

Uit 08: elke Foutmelding eindigt op `Code: <interaction_id>`. De Foutmeldingen staan nu als losse teksten in de handlers (`src/commands/media.py:422`, `:430`, `src/commands/serie.py:194`, `src/commands/subscribe.py:115`). Wie ze straks stuurt, hangt af van dit ticket.

## Answer

Besloten in een grilling met de beheerder op 2026-11-03, in drie rondes. Vastgelegd in [ADR 0001](../../../docs/adr/0001-fouten-als-excepties-met-centrale-wrapper.md).

### Besluiten

1. **Een Fout is een exceptie met een soort.** Er komt één klasse `Fout` met de velden `soort` (Bug, Storing, Inrichtingsfout), dienst, reden en de oorspronkelijke exceptie. Diensten geven geen `False`/`None` plus `last_error` meer terug. Wie niets met een Fout kan, laat hem doorvallen. Zo hoort er bij elke Fout één object, en de traceback gaat mee naar `exc` (06).
2. **De soort wordt bepaald waar het antwoord binnenkomt.**
   - De requestfunctie van elke dienst (`ArrClient.get/post`, de Plex-client, de Transmission-client, de verzendfunctie voor Telegram) zet een antwoord of library-exceptie om in een `Fout`. Voor HTTP-statussen gebruikt die één gedeelde regel, zodat de tabel uit 05 op één plek staat. plexapi en transmission-rpc krijgen in hun eigen client een mapping van hun excepties.
   - Wat alleen de aanroeper kan zien (een lookup zonder resultaat, een serie zonder pad, een ontbrekende instelling), gooit de aanroeper zelf als Inrichtingsfout.
   - Elke andere exceptie die de wrapper bereikt, is een Bug. Een `BadRequest: Can't parse entities` van Telegram is dus ook een Bug.
3. **Centrale vangplek: een wrapper om elke handler en elke job.** Die schrijft de logregel, laat de admin-melding uitgaan (volgens 05 en het afremmen uit 13) en stuurt de Foutmelding. Een Fout beëindigt het Gesprek: in een ConversationHandler geeft de wrapper `END` terug, bij een losse handler `None`. Daarom niet PTB's `error_handler`, want die kan geen `END` teruggeven, en dan blijft de Gebruiker in een halve state hangen.
4. **De wrapper komt bij het registreren** in `src/bot.py` om de callback. Eén helper wikkelt elke callback in voordat hij aan een `CommandHandler`/`CallbackQueryHandler`/`MessageHandler` gaat, en ook de callbacks van `run_repeating`/`run_once`. Commands weten er niets van. De job-wrapper uit 08 (`interaction_id` + `job` per run) zit in dezelfde helper.
5. **Lokaal afvangen mag alleen om door te werken**: de Plex-link ontbreekt maar het antwoord gaat wel uit, of Transmission is onbereikbaar tijdens `check_notify_list`. De vangplek meldt de Fout dan via dezelfde meldfunctie die de wrapper gebruikt, en gooit niet opnieuw. Afvangen, zelf loggen en doorgaan, of een eigen admin-melding sturen, mag niet meer. Zo blijft "één Fout, hooguit één admin-melding" (05) afdwingbaar.
6. **Jobs met een lus** (bijv. `scan_missing_media` over vijftig series): een Inrichtingsfout voor één item wordt gemeld en dat item wordt overgeslagen. Een Storing of een Bug beëindigt de run.
7. **Foutmelding: de wrapper stelt de tekst samen.** Handlers sturen zelf geen Foutmelding meer. De tekst bestaat uit:
   1. een zin over wat er misging. Die mag meekomen met de `Fout` (bijv. "Er is op dit moment een probleem met de opslag van de Plęx server"); anders staat er een standaardzin per soort;
   2. "De serverbeheerder is hiervan op de hoogte", alleen als de admin-melding echt uitging (05);
   3. "Stuur /start om opnieuw te beginnen.";
   4. `Code: <interaction_id>` (08).
8. **Een Storing van Telegram tijdens een handler** (`NetworkError`, `TimedOut`, `RetryAfter` bij `send_message`): de wrapper legt de Storing vast en probeert géén Foutmelding. De bot wacht niet in de handler op `RetryAfter`. De admin-melding volgt de regels uit 05 (begin en eind, nadat Telegram weer bereikbaar is).
9. **`error_handler` blijft het vangnet.** Netwerkfouten bij het pollen en Conflict blijven daar; hoe die worden vastgelegd, beslist 12. Al het andere wat er aankomt (een fout in de wrapper, een callback die per ongeluk niet gewikkeld is), behandelt de handler als Bug via dezelfde meldfunctie, met een logregel die zegt dat het buiten de wrapper gebeurde. Hij kan geen Gesprek beëindigen, en hij stuurt alleen een Foutmelding als er een `update` met een chat is.

### Feiten uit de code (voor de implementatie)

- `ArrClient.get()` (`src/services/arr.py:55-125`) vangt alles af, zet `last_error` en geeft `False` terug. `radarr.py`/`sonarr.py` (r. 23-58) sturen daarop een admin-melding en schrijven een logregel. `get_disk_space()` (`arr.py:187-200`) stuurt er nog een, en `src/commands/media.py:413` een derde. Daar komen de drie meldingen bij één diskspace-fout vandaan.
- `src/services/plex.py:46,93,113,119` en `src/services/transmission.py:37,51,102` vangen `Exception` af en loggen zelf. `src/commands/schedule.py:53` slikt een fout van Transmission in met `pass`.
- `src/bot.py` maakt 82 handlers aan in twee ConversationHandlers (`_build_normal_conversation`, `_build_maintenance_conversation`) en een paar losse `add_handler`s (r. 105-112). De jobs staan op r. 119-126. `error_handler` staat op r. 504.

### Doorgeschoven

- Hoe de admin-melding eruitziet en wat er gebeurt als Telegram hem weigert: [Hoe ziet een admin-melding bij een fout eruit?](10-admin-melding-bij-fout.md)
- Of de meldfunctie een melding afremt, en wat hij aan de wrapper teruggeeft: [Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?](13-herhaalde-fouten-afremmen.md)
- Polling-fouten en Conflict in `error_handler`: [Wat komt er van buiten de eigen code in de logregels?](12-ruis-buiten-eigen-code.md)
- De interface van `Fout`, de meldfunctie en de wrapper: [Welke interface krijgt de logmodule?](14-interface-logmodule.md)
