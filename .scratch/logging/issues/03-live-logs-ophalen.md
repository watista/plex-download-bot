# Recente live-logs van de thuisserver ophalen

Type: task
Status: resolved
Blocked by: –
Assignee: Wouter

## Question

Haal recente live-logs op, zodat we zien welke fouten en admin-meldingen in de praktijk voorkomen. Lokaal staan alleen live-logs van 12 en 13 januari 2026.

Checklist (HITL, voor de beheerder):

1. Bekijk op de thuisserver wat er is: `ls -la /root/scripts/plex-download-bot/log/`
2. Kopieer de logbestanden van de laatste ~4 weken naar `log/live-sample/` in deze repo (valt onder `log/*` in `.gitignore`, gaat dus niet mee in git). Sla `-debug.log`-bestanden over als ze erg groot zijn.
3. Exporteer ook wat systemd ving en niet in het logbestand staat: `journalctl -u plex-download-bot --since "4 weeks ago" > log/live-sample/journal.txt`
4. Optioneel: kopieer de tekst van een paar admin-meldingen bij fouten uit de Telegram-groep die je onduidelijk vond naar `log/live-sample/meldingen.txt`.
5. Noteer de exacte Python-versie van de bot: `/root/scripts/plex-download-bot/env/bin/python --version`. Die versie bepaalt welke rotatiebug van 3.12 speelt (zie ticket 02).
6. Noteer hieronder onder `## Answer` welke periode je hebt opgehaald, waar de bestanden staan en welke Python-versie er draait.

De bestanden bevatten persoonsgegevens; ze blijven lokaal.

## Answer

De beheerder heeft de logs op 2026-11-02 opgehaald; ze zijn in dezelfde sessie geanalyseerd.

### Wat er is opgehaald

- **Periode**: live, van 01-10-2026 06:27 tot en met 02-11-2026 22:07. Dat zijn 8 logbestanden, één per start van de bot, samen 5.270 regels en 6,8 MB. Het laatste bestand beslaat 8 dagen. Daarnaast `journal.txt`: het systemd-journal van `plex-download-bot` over de laatste 4 weken.
- **Niet opgehaald**: debug-bestanden (live draait op INFO, er waren er geen), `meldingen.txt` met Telegram-teksten, en het journal van de fallback-host.
- **Waar**: niet in de repo, maar in WSL op de pc van de beheerder: `/home/wouter/log/live-sample/`. De bestanden bevatten persoonsgegevens en blijven lokaal.
- **Python op de server**: 3.12.3. Van de rotatiebugs uit ticket 02 speelt dus deze: na de overgang naar wintertijd roteert `TimedRotatingFileHandler` niet meer tot een herstart.
- **Verdeling**: 4.310 WARNING, 193 ERROR en 380 INFO (340 van de bot zelf, 40 van PTB). Bijna het hele volume komt van twee herhaalde waarschuwingen.

### Fouten die voorkwamen

| # | Fout | Hoe vaak | Admin-melding nu | Wat het log vastlegt |
|---|---|---|---|---|
| 1 | Serie zonder `path` in de Sonarr-JSON (twee series: 288673 en 132005), bij elke run van de geplande check (`src/commands/schedule.py`) | 2.952 WARNING in 32 dagen | 53, één per serie per dag: "N runs in a row came back without a path. Check the error log" | Elke WARNING bevat de complete serie-JSON. Samen 6,1 van de 6,8 MB: 90% van alle logbytes. |
| 2 | `path` ontbreekt bij het aanmelden voor een serie: `aanmelden` in `src/commands/serie.py:219` gooit zelf `KeyError("path")` | 3 | **Komt nooit aan.** De tekst (`serie.py:225`) opent vet met `*` maar sluit niet af, dus Telegram weigert hem (`BadRequest: Can't parse entities`). | ERROR "Telegram API error" met een traceback over meerdere regels. De oorspronkelijke `KeyError` staat er alleen in als "During handling of the above exception". |
| 3 | TMDB-lookup leeg voor één film (TMDB 1593993), elke 30 minuten van 1 tot 8 oktober | 361 WARNING | 9 meldingen (8 voor deze film, 1 voor een andere) op WARNING: "N lookups in a row failed" (`LOOKUP_ALERT_THRESHOLD`) | Een WARNING per lookup. |
| 4 | Een film aanvragen die al in Radarr staat. Radarr antwoordt 400 "This movie has already been added". | 8 | 8× ERROR "Error while queueing movie downlad. Reason: HTTP 400 Bad Request". De echte reden staat alleen in de logregel. | ERROR met de response body op één regel. |
| 5 | Geen passende state bij "media state filtering" (`src/commands/media.py:335`). Alle 4 gevallen gingen over dezelfde film, op 25-10. | 4 | 4× "see the logs for the media JSON". De gebruiker krijgt "Oeps, daar ging iets fout". | Alleen de media-JSON. Er is geen exceptie: dit is de fallback als geen enkele state past. Waarom niets paste, is nergens terug te vinden. |
| 6 | Radarr/Sonarr onbereikbaar: DNS-storing op 1 en 2 november, kort ook op 17 en 18 oktober | 71 ERROR | Alleen bij de diskspace-check: 4× "Error while fetching … diskspace information. Reason: TimeoutError" | Per mislukte request een ERROR met de hele traceback op één regel (regeleindes vervangen door " - "). Eén mislukte diskspace-check levert 5 ERROR-regels op. |
| 7 | Radarr 503 "Unable to communicate with RadarrAPI" op 12-10, rond 05:00 | 12 ERROR | geen (`telegram=False`, `src/services/arr.py:91`) | ERROR met de response body. |
| 8 | Telegram onbereikbaar: DNS-storing van 01-11 17:37 tot 02-11 17:06 | 805 WARNING, plus 64× "Bad Gateway" verspreid over de maand | geen | Een WARNING per poll-poging, vanuit de `error_handler`. |
| 9 | Crash bij het opstarten door DNS (`run_polling` → `get_me`), op 20-10 15:33 en 22-10 17:46 | 2 | geen | Staat **alleen in het journal**, niet in het logbestand. systemd herstartte de bot na 10 seconden. |
| 10 | "Telegram Conflict: Another bot instance is running", bij elke start | 9 | geen | WARNING. |

Niet gezien in deze periode: onverwachte excepties in de `error_handler` ("Unexpected error happened with Telegram dispatcher") en "Task was destroyed but it is pending".

Alleen in het journal en bij elke start: `PTBUserWarning` over `per_message=False` bij een ConversationHandler (`src/bot.py`), en een systemd-waarschuwing over `StartLimitIntervalSec` in de unit. Verder sloeg apscheduler één keer `check_notify_list` over ("maximum number of running instances reached"), tijdens de storing op 2 november.

### Wat dit betekent voor de andere tickets

- **05 (welke fouten een admin-melding worden)**: er gingen ongeveer 78 admin-meldingen bij fouten de deur uit, waarvan 53 dezelfde twee bekende problemen herhaalden (nr. 1). Eén soort kwam nooit aan (nr. 2). "Al toegevoegd" bij Radarr (nr. 4) is geen storing, maar leverde wel een ERROR-melding op. Tijdens de echte storing van 1 en 2 november kwam alleen de diskspace-melding binnen.
- **06 (formaat en niveaus)**: de complete media-JSON in een WARNING is 90% van het volume. Tracebacks staan nu soms op één regel (via `clean_message`) en soms over meerdere regels (`exc_info=True` in `send_telegram_message`).
- **07 (opslag en rotatie)**: één bestand per start, het langste beslaat 8 dagen. De server draait Python 3.12.3. Startcrashes staan alleen in het journal.
- **09 (excepties)**: twee van de fouten zijn geen gewone exceptie: de filtering-fallback (nr. 5) en een eigen `raise KeyError` als control flow (nr. 2). Bij nr. 5 is de oorzaak nergens terug te vinden.
- **10 (admin-melding bij een fout)**: de nummers 1, 2, 4, 5 en 6 zijn echte voorbeelden voor de prototypes.
