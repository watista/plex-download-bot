# Logging verbeteren

Label: wayfinder:map

## Destination

Een logging-spec (`.scratch/logging/spec.md`) die vastlegt hoe de bot logregels, gebruikersacties en admin-meldingen bij fouten produceert, zodat de beheerder (1) via SSH en via `/log <gebruiker>` kan terugzoeken wat een gebruiker deed, (2) kan zien waar een fout ontstond, en (3) uit een admin-melding bij een fout direct begrijpt wat er mis is. Klaar om in implementatie-issues op te knippen.

## Notes

- Domein: Python 3.12, python-telegram-bot 21.10 (asyncio, ConversationHandlers, JobQueue). Logging zit nu in `src/log.py` (`Log.logger()` doet logregel en Telegram-bericht in één call).
- Begrippen staan in `CONTEXT.md` (Gebruiker, Bezoeker, Beheerder, Gebruikersactie, Gesprek, Logregel, Admin-melding, Foutmelding). Gebruik die en houd het glossarium bij.
- Skills: grilling-tickets via "grilling" + "domain-modeling"; bij vragen over code-structuur (09 en de code-interface in de fog) ook "codebase-design"; prototype-tickets via "prototype".
- Randvoorwaarden: alleen code in de bot, geen extra infrastructuur of externe diensten. Retentie blijft zoals nu: er wordt niets automatisch verwijderd. Logregels moeten leesbaar zijn via SSH (`grep`/`jq`/`less`) en machinaal door `/log <gebruiker>`.
- Maintenance mode (fallback-host) valt binnen scope: zelfde code.
- Plan, don't do: tickets leveren beslissingen, geen code. Als alle tickets dicht zijn, worden de beslissingen samengevoegd in `spec.md`.
- Tracker: lokale markdown in `.scratch/logging/` (geen `gh` op deze machine). Overleg in het Nederlands.
- Commando's draaien via WSL (`wsl -e bash -lc '…'`). De opgehaalde live-logs van oktober 2026 staan in WSL onder `/home/wouter/log/live-sample/`; ze bevatten persoonsgegevens en blijven buiten de repo.

## Decisions so far

<!-- the index: one line per closed ticket, enough to judge relevance, then zoom the link for the detail the ticket holds -->

- [04 Gebruikersacties vastleggen](issues/04-gebruikersacties-vastleggen.md): elk bericht en elke knopdruk is een gebruikersactie (catalogus van 15 soorten) met user ID + accountnaam en uitkomst; wachtwoord, e-mail/telefoon en tekst buiten een Gesprek nooit letterlijk; admin-meldingen niet meer naar het logbestand gekopieerd.

- [Welke opties heeft Python voor gestructureerde logregels en dagelijkse rotatie?](issues/02-python-structured-logging.md): stdlib met een contextvars-handlerfilter volstaat; JSONL-dagbestanden via een eigen handler; `TimedRotatingFileHandler` heeft DST-bugs op 3.12 en `logrotate` verwijdert standaard.
- [Hoe onderschep je in python-telegram-bot 21 elke update centraal en geef je context door?](issues/01-ptb-update-context.md): eigen `BaseUpdateProcessor` die contextvars per update zet en reset; JobQueue-jobs moeten zelf context zetten; de handler of state van een fout is niet direct te achterhalen.
- [Recente live-logs van de thuisserver ophalen](issues/03-live-logs-ophalen.md): live-logs van oktober 2026 plus journal, Python 3.12.3. Tien soorten fouten in een tabel. 90% van het volume komt van één herhaalde WARNING met de complete JSON; een van de admin-meldingen komt door een MarkdownV2-fout nooit aan; startcrashes staan alleen in het journal.
- [Welke fouten worden een admin-melding, en welke alleen een logregel?](issues/05-welke-fouten-admin-melding.md): een Fout is een Bug (altijd een melding), een Storing (alleen als hij aanhoudt, plus een Herstelmelding) of een Inrichtingsfout (melding, afgeremd). Een 4xx-antwoord is een Bug, onbereikbaar of 5xx een Storing, een leeg resultaat of 401/403 een Inrichtingsfout. Eén Fout geeft hooguit één melding, en de Foutmelding belooft alleen een melding die echt uitgaat. Bevat een tabel per geval.
- [Welk formaat en welke logniveaus krijgen logregels?](issues/06-logformaat-en-niveaus.md): JSON Lines in UTF-8, alles Engels, met vaste velden; de Telegram-naam van een Bezoeker staat in een eigen veld. ERROR voor een Bug of Inrichtingsfout, WARNING voor een Storing, INFO voor gebruikersacties. Boven DEBUG geen complete responses, en een volledige traceback alleen bij een Bug. Bevat de velden en soortnamen.
- [Hoe worden logbestanden opgeslagen en geroteerd?](issues/07-opslag-en-rotatie.md): één bestand per lokale kalenderdag, `plex-download-bot-JJJJ-MM-DD.jsonl` (dev met de prefix `dev-`), nooit hernoemd, begrensd of verwijderd. Het hoofdbestand bevat altijd INFO en hoger, bij DEBUG komt er een `-debug.jsonl` bij. Elke host houdt zijn eigen logs, en journald krijgt geen logregels. Het bestand van 200 MB kwam door een lus van foutregels, niet van het debug-bestand.
- [Hoe koppelen we logregels van één interactie, en een melding aan de logregel?](issues/08-interactie-id-en-fout-id.md): `interaction_id` hoort bij één Interactie: één update of één run van een job (die run krijgt ook een veld `job`). Er is geen apart fout-ID: de admin-melding en de Foutmelding (`Code: k7p2qx`) tonen het `interaction_id`. Het ID is 6 willekeurige tekens zonder tekens die op elkaar lijken. Een aanhoudende Storing krijgt het ID van de eerste mislukte poging.
- [Waar vangen we excepties af: lokaal of centraal?](issues/09-excepties-lokaal-of-centraal.md): centraal. Een Fout is een exceptie met een soort, die de requestfunctie van de dienst bepaalt (de aanroeper bij een Inrichtingsfout; al het andere is een Bug). Een wrapper, bij het registreren om elke handler en job gezet, schrijft de logregel, laat de admin-melding uitgaan, stelt de Foutmelding samen en beëindigt het Gesprek. Lokaal afvangen mag alleen om door te werken, via dezelfde meldfunctie. `error_handler` blijft het vangnet. Zie ADR 0001.
- [Hoe ziet een admin-melding bij een fout eruit?](issues/10-admin-melding-bij-fout.md): HTML, in het Engels, altijd één bericht. Bovenaan een kop met de soort (Bug, Disruption, Setup, Restored) en wat er misging, dan een paar regels in beeld. De details en de eigen code zitten in een uitklapbaar blok, en `Code: k7p2qx` staat onderaan. Weigert Telegram de opmaak, dan gaat de melding opnieuw als platte tekst. Een Herstelmelding komt stil binnen. Na een Telegram-storing noemt hij de Fouten waarvan de melding niet aankwam. Het prototype staat op een branch.
- [Wat toont /log <gebruiker>, en voor wie?](issues/11-log-command.md): `/log <accountnaam | user ID | code>`, alleen voor de Beheerder, alleen in de privéchat, ook midden in een Gesprek. Bij een persoon toont het gebruikersacties, Fouten (met code), `admin_message_sent` en Gebruikersberichten, zonder regels van libraries. Bij een code toont het de hele Interactie. Eén HTML-bericht per keer, met knoppen om te bladeren. Elk Gebruikersbericht (nieuw begrip) krijgt een regel `user_message` met de ontvanger. Bevat een schets.
- [Wat komt er van buiten de eigen code in de logregels?](issues/12-ruis-buiten-eigen-code.md): in het hoofdbestand staat eigen code vanaf INFO en staan libraries vanaf WARNING, met hun eigen niveau en nooit als Fout; het debug-bestand krijgt alles. Tokens en wachtwoorden worden gemaskeerd, in logregels en in berichten naar Telegram. Python-warnings worden logregels, en een crash na de logging-setup schrijft `bot_crashed` (Storing of Bug). Elke pollfout van Telegram is een poging van een Storing.
- [Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?](issues/13-herhaalde-fouten-afremmen.md): een Storing houdt aan bij minstens 2 mislukte pogingen over 15 minuten. Hij is voorbij bij het eerste geslaagde antwoord, zonder dat de bot zelf controleert. Een Inrichtingsfout wordt meteen gemeld. Storingen en Inrichtingsfouten krijgen Herinneringen (nieuw begrip) na 1 en 3 dagen en daarna wekelijks. Een rechtgezette Inrichtingsfout krijgt een stille Herstelmelding (`Fixed`). Een Bug geeft per handtekening hooguit één melding per 24 uur; dat geldt ook voor een crash, die zelf een melding stuurt. De toestand staat in `faults.json`. Elke Fout krijgt elke keer een logregel, na de eerste een korte. Er is geen noodrem.
- [Welke interface krijgt de logmodule?](issues/14-interface-logmodule.md): elke module krijgt een logger met velden als keywords, zonder `await`. Een Fout is in de code een `Fault` met drie constructors; het media-item komt uit de context van de Interactie. De meldfunctie (`report`, `ok`, `fixed`, `report_crash`) geeft terug of de Beheerder het weet, en `report` komt vóór de Foutmelding. Er is één verzendfunctie naar Telegram, met een eigen `HTTPXRequest` voor `ok`, en één requestregel voor de diensten. De wrappers zijn `guard`, `guard_job` en `guard_task`; de heartbeat start na een Bug opnieuw. Een Bug buiten een Interactie krijgt een eigen Code (nieuw begrip). Bevat de indeling in modules en de tests.

## Not yet specified


## Out of scope

- Admin-meldingen die geen fout zijn (accountaanvraag, kwaliteitsverzoek, vraag via /help, aanvraag voor iets dat unmonitored staat, en overige meldingen over gebruikersacties): blijven ongewijzigd. Deze map gaat over fouten die aandacht nodig hebben.
- Overzichten en statistieken over gebruik: alleen terugzoeken is nodig.
- Live meekijken met gebruikersacties via Telegram.
- Extra infrastructuur of externe diensten (Loki/Grafana, Seq, Sentry e.d.).
- Bewaartermijnen en afstemming met de privacy policy: retentie blijft zoals nu.
- Het watcher-script (`files/plex-download-bot-watcher.py`): eigen logging, geen klachten.
- De implementatie zelf: de bestemming is de spec.
- De FAQ-zin dat berichten aan de bot "niet opgeslagen of gelezen" worden (`src/commands/help.py:141`), die na 04 niet meer klopt: hoort bij de afstemming met de privacy policy. Besloten in [Welke fouten worden een admin-melding, en welke alleen een logregel?](issues/05-welke-fouten-admin-melding.md).
- De bugfix voor "al toegevoegd" (de bot biedt een film aan die al in Radarr staat): een fout in de bot, geen logging. Gevonden in [Welke fouten worden een admin-melding, en welke alleen een logregel?](issues/05-welke-fouten-admin-melding.md).
- Een lookup met de tekst `serie_request` als TMDB ID, op 01-10. Dat is de `callback_data` van de knop 📺 Serie. Het is een fout in de bot, geen logging. Gevonden in [Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?](issues/13-herhaalde-fouten-afremmen.md).
