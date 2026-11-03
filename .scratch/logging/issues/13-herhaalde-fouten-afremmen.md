# Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?

Type: grilling
Status: resolved
Blocked by: 05
Assignee: Wouter

## Question

Wanneer wordt een Fout die terugkomt opnieuw gemeld, en hoe voorkomen we dat dezelfde Fout de Telegram-groep en het logbestand overspoelt?

Uit 05 staat vast: een Bug geeft altijd een admin-melding, een Storing alleen als hij aanhoudt (met een Herstelmelding als hij voorbij is), en een Inrichtingsfout geeft een admin-melding maar wordt afgeremd bij herhaling. Eén Fout geeft hooguit één admin-melding.

Te beslissen:

- Wanneer een Storing aanhoudt: na hoeveel mislukte pogingen of na hoeveel minuten, en of dat per dienst verschilt. In oktober: Radarr gaf rond 05:00 ongeveer een uur 503; de DNS-storing van 1 en 2 november duurde bijna een dag.
- Hoe vaak een Inrichtingsfout die blijft bestaan opnieuw gemeld wordt. Nu: vanaf 3 keer op rij, één keer per dag per ID (`LOOKUP_ALERT_THRESHOLD` in `src/services/arr.py`, `failure_threshold` in `src/commands/schedule.py`). In oktober gaf dat 53 meldingen voor twee series.
- Of een Bug die steeds terugkomt elke keer gemeld wordt. Een voorbeeld: "al toegevoegd" voor dezelfde film, 4 keer in oktober.
- Of tellers en de begintijd van een Storing een herstart overleven. Nu staan ze in het geheugen, en de bot startte in oktober 8 keer.
- Herhaalde logregels voor dezelfde Fout: elke keer een volledige regel, of na de eerste keer een korte regel. Nu zijn dat 2.952 WARNING-regels met de complete JSON, 90% van alle logbytes. Uit 06: de complete JSON hoort niet meer in een regel boven DEBUG; alleen titel, jaar, tmdbId en de velden waarop de beslissing viel.

Uit 07: logbestanden worden nooit begrensd of gecomprimeerd, dus afremmen gebeurt hier. Een voorbeeld van een lus: op 16-01-2026 schreef de dev-bot 18 minuten lang 40 keer per seconde "Telegram API error: Can't parse entities" met een traceback van ongeveer 70 regels. Samen 38.640 keer, 200 MB (`log/dev-wouter-thuisserver-bot-01-16-2026.log`).

Uit 08: de admin-melding van een aanhoudende Storing toont het `interaction_id` van de eerste mislukte poging, en de Herstelmelding toont dat ID ook. Overleeft de begintijd een herstart, dan moet dat ID mee. Een afgeremde Inrichtingsfout toont het ID van de run die de melding uitlokte.

Uit 09: afremmen gebeurt in de ene meldfunctie die de wrapper, plekken die melden en doorwerken en `error_handler` gebruiken. De Foutmelding belooft alleen een melding die echt uitging, dus de meldfunctie moet teruggeven of hij een melding verstuurde, of dat er voor deze Fout al een uit is. Een job met een lus meldt een Inrichtingsfout per item en gaat door. Bij een Storing of Bug stopt de run, dus een Storing geeft per run hooguit één mislukte poging.

Uit 10: een afgeremde Inrichtingsfout krijgt in de admin-melding een regel `Repeat:`. Dit ticket beslist wat erin staat; in het prototype was dat "3rd run in a row, next alert tomorrow". De melding van een Storing toont `Since:` met het aantal mislukte pogingen en de laatste reden. De Herstelmelding toont begin, eind, duur en het aantal pogingen. Na een Telegram-storing noemt de Herstelmelding de Fouten waarvan de melding niet aankwam, met soort, dienst en code. Of die gegevens een herstart overleven, valt onder dezelfde vraag als de tellers. Een startcrash door DNS (03, geval 9) is precies zo'n herstart.

Uit 12: elke `NetworkError` bij het pollen is een mislukte poging van een Storing van Telegram, met een WARNING per poging. In oktober waren dat er 805 in bijna een etmaal, met een wachttijd die PTB laat oplopen tot 30 seconden. Of die regels na de eerste korter worden, valt onder de laatste vraag hierboven. Een crash na de logging-setup schrijft een regel `bot_crashed`: een Storing bij een netwerkfout van Telegram, anders een Bug. Te beslissen hier: of een crash door een Bug een admin-melding krijgt, en hoe die wordt afgeremd als systemd de bot elke 10 seconden opnieuw start en hij steeds weer crasht.

## Answer

Besloten in een grilling met de beheerder op 2026-11-03, in drie rondes, aan de hand van de live-logs van oktober. In `CONTEXT.md` is de Herstelmelding ruimer gemaakt (besluit 8) en is Herinnering bijgekomen.

### Storingen

1. **Een Storing houdt aan** bij minstens 2 mislukte pogingen, de laatste minstens 15 minuten na de eerste, zonder geslaagd antwoord van die dienst ertussen. Dat geldt voor elke dienst hetzelfde. Het wordt bekeken bij elke mislukte poging; er is geen aparte timer. Een drempel op aantal pogingen werkt niet: de heartbeat gaat elke 5 seconden, `check_notify_list` elke 30 minuten. In oktober waren de nachtelijke hapering van Telegram en de korte blips van de heartbeat zo alleen logregels gebleven, en waren de 503 van Radarr (om 05:57) en de DNS-storing van 1 en 2 november gemeld.
2. **Een Storing is voorbij** bij het eerste geslaagde antwoord van dezelfde dienst, op welke request ook. De bot controleert een dienst niet zelf: `system/status` van Radarr had de 503 van SkyHook op 12-10 niet gezien. Een Storing die voorbij is voordat hij aanhield, laat alleen logregels achter, zonder Herstelmelding.
3. **Telegram**: na een Storing van Telegram komt er een Herstelmelding als hij aanhield (besluit 1) of als de lijst `Not sent meanwhile` uit 10 niet leeg is. Zo valt een melding die tijdens een korte hapering verloren ging toch op. Een `NetworkError` bij het versturen van een admin-melding of Foutmelding telt ook als mislukte poging.
4. **Herinnering bij een Storing**: met dezelfde tussenpozen als bij een Inrichtingsfout (besluit 6). De Herinnering gaat uit bij de eerste mislukte poging nadat de tussenpoos voorbij is. Wordt de dienst niet aangeroepen, dan komt er geen. Bij een Storing van Telegram kan er geen komen. Hij is de melding uit 10 met een regel `Repeat:` erbij, met geluid:

   ```
   🌩 Disruption · Radarr is not responding
   Reason: ClientConnectorDNSError
   Since: 1 Nov 17:37, 412 failed attempts
   Repeat: 2nd alert · next alert 5 Nov
   Code: m4t9cw (first failed attempt)
   ```

5. **Een dienst die blijft haperen** krijgt geen extra regel. Elke ronde die aanhoudt, geeft een melding en een Herstelmelding. In oktober kwam dat niet voor.

### Inrichtingsfouten

6. **Meteen melden, daarna Herinneringen.** Een Inrichtingsfout wordt bij de eerste keer gemeld. `LOOKUP_ALERT_THRESHOLD` vervalt: in oktober kwamen alle mislukte lookups behalve die voor TMDB 1593993 door de DNS-storing of de 503, en dat zijn nu Storingen. Zolang de Fout blijft bestaan, gaat er een Herinnering uit na 1 dag, dan na 3 dagen en daarna elke 7 dagen, telkens gemeten vanaf de vorige melding en bekeken als de Fout opnieuw voorkomt. Voor de twee series zonder pad waren dat in oktober hooguit 14 meldingen geweest in plaats van 53.
7. **Dezelfde Inrichtingsfout** heeft dezelfde sleutel: dienst + soort reden + het item (tmdb- of tvdb-ID) of de naam van de instelling. Bij opslag vol is het alleen dienst + reden. Een serie zonder pad is dus één Fout, of hij nu opvalt bij de geplande check of bij het aanmelden van een Gebruiker. Wie daarna op die Fout stuit, krijgt een Foutmelding dat de beheerder op de hoogte is (09). De Fout telt per run, niet per aanroep. Hij is weg zodra dezelfde controle slaagt.
8. **Rechtgezet**: dan komt er een stille Herstelmelding met de kop `✅ Fixed`, maar alleen als er over die Fout een melding uitging. Erin staat wat rechtgezet is, van wanneer tot wanneer het misging, hoe vaak, en de code van de eerste melding → de code van de Interactie waarin de controle slaagde:

   ```
   ✅ Fixed · Carrie now has a path in Sonarr
   Failing: 1 Oct 06:27 – 3 Nov 10:15 (33 days), 1,544×
   Code: a3k9pw → t6n2rd
   ```

9. **Niet meer gecontroleerd**: een Inrichtingsfout die 30 dagen niet voorkwam, verdwijnt stil, zonder Herstelmelding, want de bot weet niet of hij is rechtgezet. Een voorbeeld is een serie die uit de lijst is gehaald. Komt hij daarna terug, dan is het een nieuwe Fout met een eerste melding.

### Bugs

10. **Hooguit één melding per 24 uur per handtekening.** De handtekening bestaat uit:
    - de dienst
    - het type exceptie
    - de binnenste eigen frame (bestand:regel)
    - bij een 4xx de statuscode

    De tekst van de reden telt niet mee, want daar staan titels in. "Altijd" uit 05 wordt zo "altijd de eerste keer". Wie de Bug binnen die 24 uur raakt, krijgt te horen dat de beheerder op de hoogte is.
11. **Crash door een Bug**: de `sys.excepthook` uit 12 verstuurt zelf een admin-melding, synchroon en met een korte timeout. Hij wordt afgeremd per handtekening (besluit 10) via de toestand uit besluit 13. Een crashlus geeft zo één melding per 24 uur, ook als de bot al bij het opstarten crasht. Een crash door een Storing van Telegram krijgt geen eigen melding: hij telt als poging van die Storing, en de Herstelmelding na de herstart vertelt het.

### Voor alle soorten

12. **De regel `Repeat:`** staat alleen in een melding die een herhaling is:
    - Inrichtingsfout: `Repeat: 3rd alert · failing since 1 Oct 06:27 (96×) · next alert 8 Oct`
    - Storing: `Repeat: 2nd alert · next alert 5 Nov`. Begin en pogingen staan al in `Since:`.
    - Bug: `Repeat: 4× since the last alert (12 Oct 14:02)`
13. **De toestand overleeft een herstart.** Hij staat in `faults.json` (dev: `faults.dev.json`) naast `data.json`, wordt bijgewerkt bij elke wijziging en is er per host. Erin staan:
    - per open Storing: het begin, het `interaction_id` van de eerste poging, het aantal pogingen, de laatste reden en de laatste melding
    - per Inrichtingsfout: sinds wanneer, hoe vaak, de eerste code en de laatste melding
    - per Bug-handtekening: de laatste melding en hoe vaak hij sindsdien voorkwam
    - de lijst `Not sent meanwhile`
14. **Logregels**: elke keer dat een Fout voorkomt, krijgt hij een regel. `/log <code>` moet hem tonen (11), en een Storing schrijft een WARNING per poging (12). De regel is volledig bij de eerste keer en bij elke keer dat er een admin-melding uitgaat. Daartussen is hij kort: dezelfde vaste velden met `repeat: n`, zonder `exc`, response en beslisvelden. Dat geldt ook voor pogingen buiten een Interactie. Bij de heartbeat (elke 5 seconden) zijn dat zo'n 17.000 korte regels per etmaal storing. De lus op dev van 16-01 was zo rond de 10 MB geweest in plaats van 200 MB.
15. **Geen noodrem** op het aantal meldingen, en geen bundeling. Hebben na een wijziging in Sonarr ineens 30 series geen pad, dan komen er 30 meldingen.

### Feiten uit de logs en de code (voor de implementatie)

- Nu staan de tellers in het geheugen: `_lookup_failures` (een klasse-attribuut, `src/services/arr.py:19`) en `_missing_path` (`src/commands/schedule.py:33`). Ze worden bijgewerkt in `log_lookup_failure` (`arr.py:235`) en `log_missing_path` (`schedule.py:331`), met `LOOKUP_ALERT_THRESHOLD` als drempel. Bij een geslaagde controle verdwijnt de stand met een `pop` (`arr.py:231`, `schedule.py:325`). Na elke herstart begint de teller opnieuw: de streaks van serie 288673 en 132005 braken af op de startmomenten van 13, 19, 20, 21, 22, 23 en 25 oktober.
- `log_missing_path` telt serie 288673 twee keer per run (bijvoorbeeld "Failure 151" en "152" om 05:27:35 en 05:27:37).
- De 503 van Radarr op 12-10: in de run van 05:27 zocht de bot TMDB 1368337 vijf keer op. De oude teller kwam daardoor in één run op 3 en stuurde "No movie found". Elke request probeert het al 3 keer opnieuw ("after 3 retries") voordat hij als één mislukte poging telt. De run van 06:27 lukte weer.
- Telegram gaf in oktober 64 keer "Bad Gateway". Bijna elke nacht gebeurde dat rond 03:11 (na de wintertijd 02:11), 1 tot 4 keer binnen een minuut, en daarnaast op 29-10 om 23:04 (7×) en op 30-10 om 00:15 (5×).
- De heartbeat (`_heartbeat_loop`, `src/bot.py:424`) draait live elke 5 seconden. Nu logt hij alleen de 1e en elke 30e mislukte poging, plus een INFO-regel "recovered after N failures". Op 01-11 waren er korte blips van 1 en van 8 pogingen.
- De bot bewaart zijn toestand al in `data.json` en `stats.json` in de werkmap, met `.dev`-varianten (`src/commands/media.py:37`).
- Een bijvangst: op 01-10 om 12:36 zocht de bot een serie op met als TMDB ID de tekst `serie_request`. Dat is de `callback_data` van de knop 📺 Serie (`src/commands/start.py:40`). Het is een Bug en geen Inrichtingsfout. Niet verder uitgezocht.

### Doorgeschoven

- Waar `faults.json` gelezen en geschreven wordt, en hoe de meldfunctie en de excepthook die delen. Ook hoe een controle die slaagt dat aan de meldfunctie laat weten, en welke code de melding over een crash toont, die buiten een Interactie valt: [Welke interface krijgt de logmodule?](14-interface-logmodule.md)
