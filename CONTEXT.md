# Plex Download Bot

Telegram-bot waarmee gebruikers films en series aanvragen voor de Plex-server van de beheerder, en waarmee de beheerder zicht houdt op wat er gebeurt.

## Language

### Gebruikers

**Gebruiker**:
Iemand die de bot gebruikt onder een accountnaam uit de gebruikerslijst. De accountnaam is de identiteit: meerdere Telegram user ID's kunnen onder dezelfde accountnaam vallen, en de Telegram-naam is alleen weergave.
_Avoid_: username, first_name, account

**Bezoeker**:
Iemand die de bot gebruikt zonder (al) Gebruiker te zijn: nog niet ingelogd, bezig met een accountaanvraag, of geblokkeerd. Herkend aan het Telegram user ID.
_Avoid_: gast, onbekende gebruiker, anonieme gebruiker

**Beheerder**:
Eigenaar van de Plex-server die de bot beheert en admin-commands mag gebruiken.
_Avoid_: owner

**Gebruikersactie**:
Elk bericht of elke knopdruk van een Gebruiker, Bezoeker of de Beheerder die de bot ontvangt, ook als de bot het negeert: een command, zoekterm, keuze of aanvraag.
_Avoid_: activiteit, usage

**Gesprek**:
Reeks gebruikersacties van één Gebruiker of Bezoeker, van het begin (`/start`, een command of een knop in het startmenu) tot het einde: afgerond, `/stop`, of verlopen na een periode zonder activiteit.
_Avoid_: conversatie, sessie, flow

**Interactie**:
Eén Gebruikersactie plus alles wat de bot doet om die af te handelen, of één run van een geplande taak. Heeft een eigen code waarmee alle logregels ervan en de meldingen erover terug te vinden zijn. Een Gesprek bestaat uit meerdere Interacties.
_Avoid_: request, verzoek, fout-ID

### Logging en meldingen

**Logregel**:
Technisch record in het logbestand, bedoeld om achteraf terug te zoeken wat er gebeurde.
_Avoid_: log message, debug log

**Admin-melding**:
Telegram-bericht aan de beheerder waar de beheerder iets mee moet doen.
_Avoid_: alert, notificatie, log naar Telegram

**Herstelmelding**:
Admin-melding dat een Storing voorbij is of dat een Inrichtingsfout is rechtgezet. Volgt op een eerdere admin-melding over die Fout. Alleen bij een Storing van Telegram is er geen eerdere melding, omdat er tijdens de Storing niets aankomt.
_Avoid_: recovery-melding, fixed-melding, oplosmelding

**Herinnering**:
Admin-melding die een eerder gemelde Storing of Inrichtingsfout opnieuw meldt, omdat hij na een tijd nog steeds bestaat.
_Avoid_: reminder, herhaalmelding

**Foutmelding**:
Tekst die een gebruiker te zien krijgt als er iets misgaat.
_Avoid_: errorbericht

**Gebruikersbericht**:
Bericht dat de bot uit zichzelf aan een Gebruiker stuurt, en dus niet als antwoord op een Gebruikersactie van die Gebruiker: dat iets online staat, dat er nieuwe afleveringen zijn, of een bericht van de Beheerder.
_Avoid_: notificatie, notify, melding

### Fouten

**Fout**:
Iets wat misgaat in de bot of in een dienst waar de bot van afhangt. Er zijn drie soorten: Bug, Storing en Inrichtingsfout.
_Avoid_: error, probleem

**Bug**:
Fout waarbij de bot zelf iets doet wat niet klopt. Alleen een aanpassing van de code lost hem op.
_Avoid_: programmafout, crash

**Storing**:
Fout waarbij een dienst waar de bot van afhangt (Radarr, Sonarr, Plex, Transmission, TMDB, Telegram, de fallback-host) niet reageert of een serverfout geeft. Gaat vaak vanzelf over.
_Avoid_: outage, downtime, uitval

**Inrichtingsfout**:
Fout waarbij iets in de inrichting van de server niet klopt of tekortschiet, zodat alleen de Beheerder het met de hand kan rechtzetten: gegevens in Sonarr of Radarr (een serie zonder pad, een TMDB-ID waarvoor de lookup niets oplevert), een instelling van de bot die ontbreekt of niet klopt, of een volle opslag.
_Avoid_: gegevensfout, configuratiefout, beheerfout
