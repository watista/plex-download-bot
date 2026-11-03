# Wat toont /log <gebruiker>, en voor wie?

Type: grilling
Status: resolved
Blocked by: 04
Assignee: Wouter

## Question

Wat laat het admin-command `/log <gebruiker>` zien, en hoe?

Te beslissen:

- Welke periode en hoeveel: laatste N gebruikersacties, vandaag, of een datum als argument.
- Of fouten van die gebruiker ook getoond worden.
- Hoe je de gebruiker aanwijst: op accountnaam, user ID, of allebei. Wat als de gebruiker niet bestaat.
- Wie het mag gebruiken. Andere admin-commands gebruiken `allowed_users` uit `CHAT_ID_ADMIN` (`src/bot.py:67`).
- Opmaak en lengte in Telegram (max. 4096 tekens per bericht).

Uit 06: elke regel heeft `msg` en, bij een eigen gebeurtenis, `event`. `user_id`, `account` en `tg_name` (alleen bij een Bezoeker) zijn aparte velden. Gebruikersacties staan op INFO. De soortnamen staan in 06.

Uit 07: één bestand per lokale kalenderdag, `plex-download-bot-JJJJ-MM-DD.jsonl` (dev: met de prefix `dev-`). Het hoofdbestand bevat altijd INFO en hoger; bij `LOG_TYPE=DEBUG` staat er per dag ook een `-debug.jsonl`, dat `/log` niet nodig heeft. `/log` leest alleen `.jsonl`, dus niet verder terug dan de overstap, en alleen de bestanden van de eigen host: wat tijdens een periode op de fallback gebeurde, staat op de fallback-host.

Uit 08: elke regel in een Interactie heeft een `interaction_id` (6 tekens). Een gebruiker kan een code uit een Foutmelding (`Code: k7p2qx`) doorgeven. Beslis hier of `/log` het ID per regel toont, en of `/log` ook op een code kan zoeken.

## Answer

Besloten in een grilling met de beheerder op 2026-11-03, in twee rondes. Nieuw begrip in `CONTEXT.md`: **Gebruikersbericht**.

### Wie en waar

1. **Alleen de Beheerder, alleen privé.** `/log` werkt alleen voor `allowed_users` (`CHAT_ID_ADMIN`) en alleen in de privéchat met de bot. In de groep, of van iemand anders, komt er geen reactie. Dat wordt een regel `ignored` (04), zoals bij elk onbekend command. Gewone gebruikers zien `/log` niet in hun commandlijst.
2. **Altijd beschikbaar.** `/log` is een losse handler, net als `/help`, en geen entry point van de ConversationHandler. Het werkt dus ook midden in een eigen Gesprek, zonder dat Gesprek af te breken.

### Argument

3. **Eén command: `/log <accountnaam | user ID | code>`**, herkend in deze volgorde:
   - alleen cijfers: een user ID
   - een accountnaam, hoofdletterongevoelig
   - de vorm van een code (6 tekens uit het alfabet van 08): een `interaction_id`

   Lijkt een accountnaam op een code (bijvoorbeeld "sander"), dan wint de accountnaam. Zoeken op Telegram-naam kan niet, want die is geen identiteit en kan botsen met een accountnaam (06). Zonder argument toont `/log` een korte gebruiksuitleg.
4. **Accountnaam**: alle regels waarin `account` die naam is, plus de regels van elk user ID dat de gebruikerslijst aan die naam koppelt. Zo komen ook de acties mee die iemand als Bezoeker deed, vóór het inloggen (04, punt 3). Staat de naam niet (meer) in de gebruikerslijst, dan zoekt `/log` toch op het veld `account`.
5. **User ID**: alle regels met dat `user_id`, zowel als Bezoeker als als Gebruiker.
6. **Code**: alle regels van die ene Interactie (punt 8).

### Inhoud

7. **Bij een persoon** (accountnaam of user ID) toont `/log` alles van INFO en hoger met zijn user ID, behalve regels van libraries:
   - gebruikersacties uit de catalogus van 04, en `conversation_expired`
   - Fouten in zijn Interacties, kort: soort, dienst en reden, met de code (punt 12)
   - `admin_message_sent`, zodat je ziet dat de Beheerder een melding kreeg
   - Gebruikersberichten aan hem (punt 9)
8. **Bij een code** toont `/log` alle regels van die Interactie uit het hoofdbestand (INFO en hoger), ook die van libraries, want dan wil je de hele aanloop zien. De kop noemt de persoon of de job. De traceback staat er niet in, `exc_type` wel. Onderaan staat dat de traceback via SSH te vinden is met `grep k7p2qx`; de eigen frames staan al in de admin-melding (10). `/log` zoekt terug door de bestanden tot de code gevonden is.
9. **Gebruikersbericht.** Elk bericht dat de bot uit zichzelf aan een Gebruiker stuurt, krijgt een eigen logregel met de ontvanger. Dat gaat om "staat online", nieuwe afleveringen, `/message` en `/message_all`:
   - `event: user_message` op INFO, met `user_id` en `account` van de ontvanger. Dat geldt ook in een job-run, die zelf geen gebruikersvelden heeft (08).
   - een veld met de soort: `online`, `new_episodes`, `message` of `broadcast`. Als naam is `kind` voorgesteld, maar die is niet apart besproken.
   - bij media: titel, jaar en tmdbId
   - geen tekst bij `message` en `broadcast`, want die staat al in de regel `admin_command` van de Beheerder (04)
   - mislukt de aflevering, dan wordt het een WARNING met `reason`, bijvoorbeeld "bot was blocked by the user"

   Bij `/message_all` levert dat ongeveer 20 regels per keer op.

### Hoeveel

10. **Eén bericht per keer**: de meest recente regels die in één Telegram-bericht passen, ook over meerdere dagbestanden heen. Er komt geen datumargument.
11. **Bladeren gaat met knoppen** "⬅️ Earlier" en "Later ➡️", die het bericht ter plekke vervangen. De positie zit in de knop zelf, dus een knop blijft ook na een herstart werken. Alleen `allowed_users` kunnen hem indrukken.

### Opmaak

12. HTML en Engels, net als de admin-melding (10):
    - Een kop met wie het is: de accountnaam, of bij een Bezoeker het user ID plus de Telegram-naam. Bij een code de persoon of de job.
    - Regels gegroepeerd per dag ("Mon 7 Dec"), de oudste bovenaan, elke regel als `<b>14:05</b> msg`. `event` blijft weg, want `msg` zegt het al.
    - Op regels van een Fout staat de code als `<code>k7p2qx</code>`, met één tik te kopiëren. Andere regels hebben geen code.
    - Bij een gedeeld account: komt er op de pagina meer dan één user ID voor, dan staat voor elke regel de Telegram-naam uit de gebruikerslijst, en zegt de kop welk user ID bij welke naam hoort.
    - Een regel van meer dan 200 tekens wordt afgekapt met "…".
    - `msg` wordt HTML-geëscapet. Weigert Telegram het bericht toch, dan gaat het opnieuw als platte tekst.
    - Onderaan staat "Logs on `<host>` since <datum van het oudste `.jsonl`-bestand>".
13. **Niets gevonden**:
    - een persoon zonder regels: "No log lines for wouter on `<host>` since …"
    - een code die niet voorkomt: "Code k7p2qx not found on `<host>`"
    - geen getal, geen accountnaam (ook niet in de logs) en niet de vorm van een code: "Unknown user or code: x"

Een schets. De teksten van `msg` zijn alleen een voorbeeld:

```
📋 wouter

Mon 7 Dec
14:05 command /start
14:05 menu choice: movie request
14:06 searched 'dune' for movie: 7 results
14:06 chose option 3: Dune (2021): already added
⚠️ 14:06 Bug · radarr: This movie has already been added  k7p2qx
14:06 admin message sent: bug
Tue 8 Dec
09:12 user message: online, Dune (2021)

Logs on thuisserver since 2026-12-01
[⬅️ Earlier]
```

### Feiten uit de code (voor de implementatie)

- De gebruikerslijst in `data.json` (`user_id`) koppelt elk user ID aan "accountnaam, Telegram-naam". Daar komen de user ID's van een accountnaam vandaan (punt 4), en de Telegram-namen bij een gedeeld account (punt 12). In oktober waren dat 19 accounts en 24 user ID's.
- De admin-commands zijn nu entry points van de ConversationHandler met `filters.User(self.allowed_users)` (`src/bot.py:162`). Midden in een Gesprek werken ze daardoor niet. `/help` en `/privacy` zijn wel losse handlers (`src/bot.py:110-113`).
- Lezen zoals 02 adviseert: de bestanden binair en achterwaarts in blokken lezen, eerst een goedkope substring-check doen en pas daarna `json.loads`, alles in `asyncio.to_thread`.
- `callback_data` is maximaal 64 bytes. Dat is genoeg voor het argument plus een positie (datum van het bestand en byte-offset).
- Volume: de actiefste gebruiker kwam in oktober in 41 regels voor. Met de catalogus van 04 wordt dat ruwweg 4 tot 6 regels per aanvraag, en één bericht biedt plaats aan ongeveer 50 regels.
- In de admin-melding van een accountaanvraag staat geen user ID (`src/commands/account.py:89`), in die van een blokkade wel. Een Bezoeker die een account aanvraagt, vind je dus alleen via een code, of als je zijn user ID al kent. Admin-meldingen die geen fout zijn, blijven ongewijzigd (Out of scope).

### Doorgeschoven

- Welke logregels een run van een geplande taak verder schrijft: [Welke logregels schrijft een run van een geplande taak?](15-logregels-geplande-taken.md)
- Welke regels van libraries in het hoofdbestand komen, en dus wat `/log <code>` toont: [Wat komt er van buiten de eigen code in de logregels?](12-ruis-buiten-eigen-code.md)
- Waar de lezer van `/log` in de code komt, en of hij een eigen module met eigen tests wordt: [Welke interface krijgt de logmodule?](14-interface-logmodule.md)
