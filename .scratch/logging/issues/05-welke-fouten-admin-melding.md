# Welke fouten worden een admin-melding, en welke alleen een logregel?

Type: grilling
Status: resolved
Blocked by: 03
Assignee: Wouter

## Question

Welke fouten zijn belangrijk genoeg voor een admin-melding, en welke worden alleen een logregel?

Nu krijgen sommige fouten een admin-melding zonder context ("see the logs"), andere niets. Er bestaan losse drempels voor herhaalde fouten: mislukte TMDB-lookups (`LOOKUP_ALERT_THRESHOLD`, `src/services/arr.py`) en ontbrekende paden (`src/commands/schedule.py`). Telegram-netwerkfouten en rate limits gaan nu alleen naar het logbestand (`error_handler` in `src/bot.py`).

Gebruik de live-logs uit ticket 03 om te zien welke fouten echt voorkomen en hoe vaak. Admin-meldingen die geen fout zijn vallen buiten dit ticket.

## Answer

Besloten in een grilling met de beheerder op 2026-11-02. Fout, Bug, Storing, Inrichtingsfout en Herstelmelding zijn in dit ticket in `CONTEXT.md` bijgekomen.

### Uitgangspunt

Elke Fout krijgt een logregel. Er komt alleen een admin-melding bij als de Beheerder iets moet doen, zoals de definitie in `CONTEXT.md` al zegt. Wat geen Fout is, blijft alleen een logregel.

### Drie soorten Fout

| Soort | Wat | Admin-melding |
|---|---|---|
| **Bug** | De bot doet zelf iets wat niet klopt. | altijd |
| **Storing** | Een dienst waar de bot van afhangt (Radarr, Sonarr, Plex, Transmission, TMDB, Telegram, de fallback-host) reageert niet of geeft een serverfout. | alleen als hij aanhoudt; een Storing die snel vanzelf overgaat, is alleen een logregel. Na een gemelde Storing volgt een Herstelmelding met de duur. |
| **Inrichtingsfout** | Iets in de inrichting van de server klopt niet of schiet tekort, en alleen de Beheerder kan het met de hand rechtzetten: gegevens in Sonarr of Radarr, een instelling van de bot, een volle opslag. | ja, afgeremd bij herhaling |

Wanneer een Storing aanhoudt en hoe vaak een herhaling opnieuw gemeld wordt, staat in [Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?](13-herhaalde-fouten-afremmen.md).

### Regels

1. **Antwoorden van diensten.** Onbereikbaar, timeout of 5xx is een Storing. Een 4xx is een Bug: de bot vroeg iets wat niet kan. Een 401 of 403 is een uitzondering: dat is een verkeerde API-sleutel en dus een Inrichtingsfout. Een geslaagd antwoord met een leeg of verkeerd resultaat (lege TMDB-lookup, SkyHook die een andere titel teruggeeft) is een Inrichtingsfout. Zo kan de code de soort op één plek bepalen.
2. **Eén Fout, hooguit één admin-melding.** Nu levert een mislukte diskspace-check er tot drie op (`src/services/arr.py:195`, `src/commands/media.py:444`, `src/commands/media.py:413`) en een mislukte Plex-link twee (`src/services/plex.py:121`, `:125`). Op welke plek de melding verstuurd wordt, beslist ticket 09.
3. **Storing bij Telegram zelf.** Tijdens de storing kan er niets aankomen. Na het herstel komt er één admin-melding met begin en eind. Meldingen die tijdens een Telegram-storing niet aankwamen, worden niet bewaard voor later. Een startcrash door een Telegram-storing (fout 9 uit 03) valt hieronder.
4. **Foutmelding.** De zin "De serverbeheerder is (hiervan) op de hoogte" staat alleen in een Foutmelding als er echt een admin-melding uitgaat. Anders zegt de Foutmelding dat de Gebruiker het later nog eens kan proberen. Nu staat die zin in `src/commands/media.py:334`, `:412`, `:422` en `:430`, `src/commands/start.py:221`, `src/commands/serie.py:194` en `src/commands/subscribe.py:115`.

### Per geval

Nummers verwijzen naar de tabel in ticket 03.

| Geval | Nu | Soort | Wordt |
|---|---|---|---|
| Serie zonder pad bij de geplande check (1) | admin-melding, 1× per dag per serie | Inrichtingsfout | admin-melding, afgeremd |
| Pad ontbreekt bij aanmelden voor een serie (2); dezelfde oorzaak als 1 (Carrie zit in beide) | admin-melding die nooit aankwam (MarkdownV2, inmiddels hersteld in f2eb618) | Inrichtingsfout | admin-melding, afgeremd |
| TMDB-lookup leeg (3) | admin-melding vanaf 3× op rij, 1× per dag | Inrichtingsfout | admin-melding, afgeremd |
| Radarr 400 "This movie has already been added" (4): 8× voor 3 films, telkens een nieuwe aanvraag. De bot denkt dat de film niet in Radarr staat. | admin-melding zonder reden | Bug | admin-melding met de reden van Radarr |
| Geen passende state (5) | admin-melding "see the logs" | Bug | admin-melding |
| Radarr of Sonarr onbereikbaar (6), Radarr 503 (7) | alleen bij de diskspace-check | Storing | admin-melding als hij aanhoudt, plus Herstelmelding |
| Telegram onbereikbaar (8), startcrash door DNS (9) | geen | Storing | één melding na herstel, met begin en eind |
| Conflict bij elke start (10) | geen | geen Fout | logregel |
| Onverwachte exceptie in de `error_handler` | admin-melding | Bug | admin-melding |
| Transmission onbereikbaar (`src/services/transmission.py:52`) | logregel | Storing | admin-melding als hij aanhoudt, plus Herstelmelding |
| Plex niet te bereiken, of de bibliotheek geeft een fout (`src/services/plex.py:47`, `:94`) | logregel | Storing | idem |
| Heartbeat naar de fallback-host mislukt (`src/bot.py:449`) | logregel | Storing | idem |
| Instelling ontbreekt of klopt niet: Plex-URL of Plex-token (`src/services/plex.py:32`), `HEARTBEAT_TARGET_PORT`, een mediamap die bij geen schijf hoort, een API-sleutel (401/403) | logregel | Inrichtingsfout | admin-melding, afgeremd |
| Opslag vol: geen schijf met 150 GB vrij. Nu valt dat samen met een mislukte diskspace-check (`src/commands/media.py:475`) en krijgt de Beheerder "Error happened during the check of the diskspace". | tot 3 admin-meldingen | Inrichtingsfout, los van de Storing | admin-melding, afgeremd |
| Media zonder titel bij het maken van een Plex-link (`src/services/plex.py:80`) | admin-melding | Inrichtingsfout | admin-melding, afgeremd |
| Plex-link: onverwachte exceptie (`src/services/plex.py:119`) | 2 admin-meldingen | Bug | één admin-melding |
| `stats.json` niet te schrijven (`src/commands/media.py:489`) | admin-melding | Bug | admin-melding |
| Geen Plex-match voor een titel (`src/services/plex.py:104`); de Gebruiker krijgt het bericht zonder link | admin-melding, elke keer | geen Fout | logregel |
| `/message_all` mislukt voor één ontvanger (`src/commands/message.py:188`) | admin-melding per ontvanger | geen Fout van de bot | logregel. Het antwoord aan de Beheerder telt al verstuurd en overgeslagen (ticket 04). |
| Conflict-melding in maintenance mode, als beide instanties tegelijk pollen (`src/bot.py:528`) | admin-melding, afgeremd | – | blijft zo |
| Start- of stopbericht aan de groep mislukt (`src/bot.py:307`, `:381`), de HTML-broadcast valt terug op platte tekst (`src/commands/message.py:40`) | logregel | – | blijft zo |

Aannames, niet apart besproken:

- `HEARTBEAT_TARGET_HOST` niet ingesteld betekent dat de heartbeat bewust uit staat (zoals op dev). Dat blijft een logregel.
- Een ongeldige `CHAT_ID_GROUP` is een Inrichtingsfout, maar in live kan dan geen enkele admin-melding aankomen. Die blijft daarom een logregel.

### Doorgeschoven

- Een admin-melding die Telegram zelf weigert (fout 2 uit 03): opnieuw versturen als platte tekst. Dat valt onder ticket 10 en de nieuwe log-interface (Not yet specified).
- Drempels, herhaling en of tellers een herstart overleven: [Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?](13-herhaalde-fouten-afremmen.md).

### Buiten scope

- De FAQ zegt dat berichten aan de bot "niet opgeslagen of gelezen" worden (`src/commands/help.py:141`). Na ticket 04 klopt dat niet meer. Het aanpassen hoort bij de afstemming met de privacy policy, en die valt buiten deze map.
- De bugfix voor "al toegevoegd": uitzoeken waarom de bot een film aanbiedt die al in Radarr staat.
