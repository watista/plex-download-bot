# Welke gebruikersacties leggen we vast, en met welke gegevens?

Type: grilling
Status: resolved
Blocked by: –

## Question

Welke gebruikersacties leggen we vast als logregel, en welke gegevens horen bij elke actie?

Nu is dit wisselend: sommige commands loggen Telegram-naam + user ID, andere de accountnaam (`gebruiker`), en zoektermen, gekozen titels en knopkeuzes worden vaak helemaal niet gelogd (`src/commands/*`).

Te beslissen:

- Welke acties: commands, zoektermen, gekozen titel, keuzes binnen een conversatie, aanvragen, aan- en afmelden voor series, login (gelukt, mislukt, geblokkeerd), `/stop`, onbekende invoer.
- Welke gegevens per actie (gebruiker, user ID, wat er gekozen of gevraagd werd).
- Wat bewust níet in een logregel komt, zoals het wachtwoord dat een gebruiker bij het inloggen stuurt.

De bestaande admin-meldingen over gebruikersacties blijven ongewijzigd; dit ticket gaat alleen over logregels.

## Answer

Besloten in een grilling met de beheerder op 2026-11-02. Begrippen volgen `CONTEXT.md`; Bezoeker, Beheerder en Gesprek zijn daar in dit ticket bijgekomen.

### Uitgangspunten

1. **Elke stap.** Elk bericht en elke knopdruk die de bot ontvangt, is een gebruikersactie met een eigen logregel, beschreven naar betekenis ("koos optie 3: Dune (2021)", "melding: ja"). Dat geldt ook voor invoer die de bot negeert.
2. **Wie.** Elke regel bevat altijd het Telegram user ID en de accountnaam. De accountnaam wordt via het user ID opgezocht in de gebruikerslijst, niet uit de gespreksgegevens gehaald: `/help` en `/aanmelden_updates` lopen niet via de verificatie. Bij een Bezoeker staat de Telegram-naam op de plaats van de accountnaam. Bij een Gebruiker staat de Telegram-naam er niet in.
3. **Bezoekers tellen mee.** Acties van iemand die nog niet is ingelogd, een account aanvraagt of geblokkeerd is, worden ook vastgelegd. Na het inloggen blijven eerdere acties te vinden via het user ID.
4. **Gedeelde accounts.** De Gebruiker is de accountnaam. Meerdere user ID's kunnen onder één accountnaam vallen, en omdat elke regel beide bevat, blijven die personen te onderscheiden.
5. **Uitkomst.** Bij elke actie waar de bot iets mee doet, staat in dezelfde regel wat de bot deed of vond (zie de catalogus).
6. **Admin-commands** van de Beheerder zijn gebruikersacties en volgen dezelfde regels.
7. **Admin-meldingen niet meer naar het logbestand kopiëren.** Nu schrijft `Log.logger(..., telegram=True)` de tekst van elke admin-melding ook naar het logbestand. Dat vervalt: de logregel van de gebruikersactie is de registratie. Hooguit komt er een korte regel "admin-melding verstuurd: <soort>". De Telegram-tekst van de admin-melding blijft ongewijzigd.
8. **Media** worden voor film en serie aangeduid met titel, jaar en tmdbId. Geen tvdbId.
9. **Einde van een Gesprek.** `/stop` is een gewone command-actie. Als een Gesprek verloopt (nu na 30 minuten, `conversation_timeout=1800`), komt er bij die Gebruiker of Bezoeker een regel "gesprek verlopen" met de stap waarin het Gesprek was. Dat is geen gebruikersactie, maar hoort wel in het spoor van die persoon.

### Catalogus

Elke regel bevat: tijd, user ID, accountnaam (bij een Bezoeker de Telegram-naam), soort, plus:

| Soort | Wanneer | Gegevens | Uitkomst |
|---|---|---|---|
| command | elk command, ook `/stop` | welk command | in maintenance mode: onderhoudsbericht |
| menukeuze | knop in het startmenu of het /help-menu | welke knop | in maintenance mode: onderhoudsbericht |
| login | wachtwoord ingevoerd, of een geblokkeerde Bezoeker probeert het | nooit de tekst | gelukt + accountnaam / fout (poging n van 3) / geblokkeerd / geweigerd (staat al op de blokkadelijst) |
| zoekterm | titel ingetypt bij film, serie of aanmelden voor een serie | zoekterm letterlijk + waarvoor | aantal resultaten |
| zoekknop | "toon meer", "probeer opnieuw", ja/nee bij "nog een keer proberen?" | welke knop | – |
| aanvraag | optie gekozen | optienummer, titel, jaar, tmdbId | wat de bot vond: download gestart / al gedownload / nog niet uit / geen downloadmatch / unmonitored (meer dan 5 seizoenen) / geen ruimte / fout |
| melding | ja/nee op "melding als het online staat?" | keuze | – |
| kwaliteitsverzoek | ja/nee, reden, omschrijving (film, "overig") of seizoen en aflevering (serie) | reden, tekst letterlijk | – |
| serie-updates | aan- of afmelden voor een serie, ook ja/nee na een aanvraag | titel, tmdbId | aangemeld / afgemeld / niets om af te melden / geen resultaten |
| algemene updates | aan of uit | aan of uit | gewijzigd / stond al zo |
| accountaanvraag | elke stap | alleen de naam letterlijk; bij e-mail, telefoon en "via" alleen "beantwoord" | – |
| help-vraag | vraag via /help → Anders | tekst letterlijk | – |
| admin | `/message`, `/message_all`, `/add_movie`, `/log` | `/message`: ID van de ontvanger + tekst; `/message_all`: tekst; `/add_movie`: ID van de ontvanger + tmdbId; `/log`: opgevraagde gebruiker | `/message_all`: aantal verstuurd en overgeslagen |
| buiten gesprek | tekst terwijl er geen Gesprek loopt | niet de tekst | `/start` getoond |
| genegeerd | tekst terwijl de bot op een knopdruk wacht, een knop uit een oud bericht, een onbekend command | soort invoer, stap van het Gesprek, waarde van de knop of het command; niet de tekst | – |

Buiten de catalogus, maar wel in het spoor van de persoon: **gesprek verlopen** (stap van het Gesprek).

### Bewust niet in een logregel

- Het wachtwoord, in geen enkele vorm (ook niet de lengte). Van een login wordt alleen de uitkomst vastgelegd.
- E-mail, telefoon en "via" uit een accountaanvraag. Die staan al in de admin-melding in Telegram, en het logbestand wordt nooit opgeruimd.
- De tekst van invoer buiten een Gesprek en van genegeerde tekst. Dat is precies waar iemand na een time-out het wachtwoord opnieuw kan sturen.
- De Telegram-naam van een Gebruiker (alleen bij een Bezoeker).
- Het tvdbId.

### Feiten uit de code (voor de implementatie)

- Via de kopie van de admin-meldingen staan e-mail en telefoon uit accountaanvragen nu al in de logbestanden (`src/commands/account.py:89`).
- Genegeerde invoer heeft nu geen handler: de ConversationHandler laat die stil vallen (`src/bot.py:153`). Voor de soort "genegeerd" is een vangnet nodig.
- Er is nog geen handler voor een verlopen Gesprek (geen `ConversationHandler.TIMEOUT`-state).
- Nu niet gelogd: algemene updates aan/uit (`src/commands/message.py:51`), foute wachtwoordpogingen 1 en 2 (`src/commands/start.py:166`) en de zoekterm (`src/commands/media.py:60`).

### Doorgeschoven

- Berichten die de bot vanuit geplande taken aan een Gebruiker stuurt ("X staat online", nieuwe afleveringen, `/message_all`) zijn geen gebruikersactie. Ze staan als aantekening bij "Geplande taken" onder "Not yet specified" in de map, omdat `/log` ze misschien moet tonen.
- `stats.json` blijft ongewijzigd: geen logregel, en overzichten vallen buiten scope.
- Logniveau, veldnamen en taal van de soortnamen: ticket 06. Koppeling van de regels van één Gesprek: ticket 08. Wat `/log` toont: ticket 11.
