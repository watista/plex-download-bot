# Hoe ziet een admin-melding bij een fout eruit?

Type: prototype
Status: resolved
Blocked by: 03, 08, 09
Assignee: Wouter

## Question

Hoe ziet een goede admin-melding bij een fout eruit?

Maak 3 tot 5 voorbeeldmeldingen op basis van echte fouten uit ticket 03, bijvoorbeeld een fout tijdens media state filtering, een mislukte download-aanvraag bij Radarr/Sonarr, en een onverwachte exceptie in de dispatcher. Beslis aan de hand daarvan:

- Welke informatie erin staat: wat ging er mis, bij welke gebruiker, welke media, waar in de code, welke exceptie, fout-ID.
- Of en hoeveel traceback erin hoort.
- Lengte en opmaak: nu MarkdownV2, in stukken van 1024 tekens (`send_telegram_message()` in `src/log.py`).

Vergelijk met de huidige meldingen, bijv. `src/commands/media.py:335` en `src/commands/serie.py:195`.

Uit 05: neem een voorbeeld op van elke soort Fout (Bug, Storing, Inrichtingsfout), plus een Herstelmelding en de melding na een Telegram-storing (met begin en eind). Een Bug door een 4xx-antwoord bevat de reden van de dienst (bijv. Radarrs "This movie has already been added"). Beslis ook wat er gebeurt als Telegram een melding weigert: die moet alsnog aankomen, bijvoorbeeld als platte tekst.

Uit 08: elke admin-melding bij een Fout toont het `interaction_id` (6 tekens, bijv. `k7p2qx`), zodat `grep` de logregels vindt. Bij een aanhoudende Storing is dat het ID van de eerste mislukte poging. Een Herstelmelding toont dat ID en het ID van de eerste geslaagde poging. Bij een Inrichtingsfout is het het ID van de run die de melding uitlokte. Bij een job staat de naam van de job in het veld `job`. Beslis hier waar het ID in de melding staat en hoe het eruitziet (bijv. kopieerbaar als inline code).

Uit 09: de wrapper om elke handler en job laat de admin-melding uitgaan via één meldfunctie, die ook gebruikt wordt door plekken die melden en doorwerken en door `error_handler`. De gegevens in een melding komen dus uit de `Fout` (soort, dienst, reden, oorspronkelijke exceptie, optionele zin voor de gebruiker) en uit de context van de Interactie (`interaction_id`, gebruiker of `job`). Een Fout die buiten de wrapper in `error_handler` terechtkomt, is een Bug, en de melding zegt dat het buiten de wrapper gebeurde.

## Answer

Besloten met de beheerder op 2026-11-03, in drie rondes, aan de hand van een prototype. Dat liet acht gevallen uit 03 zien in vier varianten, naast de huidige meldingen:

- **A**: een kaart met een kop en velden
- **B**: een verhaal met één zin, een uitklapbaar blok en hashtags
- **C**: een wijzer naar het log, met een `grep`-commando
- **D**: actie eerst

Gekozen is A als basis, met het uitklapbare blok van B. Dat is uitgewerkt als variant E.

- **Prototype**: branch `prototype/admin-melding-bij-fout` (commit `6314f9c`), bestand `src/prototype_admin_melding.html`. Het opent op variant E. Met **Nu** zie je de huidige meldingen, met **Bron** de herkomst van elk gegeven, en met **Platte tekst** de terugval.
- **Glossarium**: in `CONTEXT.md` is de definitie van Herstelmelding ruimer gemaakt. Hij meldt nu ook het einde van een Storing van Telegram, die niet eerder gemeld kon worden.

### Besluiten

1. **Opbouw**:
   - **In beeld**:
     - een kop met emoji, soort en wat er misging
     - `Reason:` of `Exception:`
     - wie: `User:`, `Visitor:` of `Job:`
     - `Media:` met titel en jaar
     - bij een Storing: `Since:` met het aantal mislukte pogingen
     - bij een Bug buiten de wrapper: "Caught by error_handler, outside the wrapper"
     - bij melden en doorwerken: `Continued:`
     - bij een afgeremde Inrichtingsfout: `Repeat:`
   - **In een uitklapbaar blok** (`<blockquote expandable>`), in deze volgorde, zodat de eerste regels in ingeklapte stand het meest helpen:
     1. de velden waarop de beslissing viel
     2. de eigen code
     3. het tmdb- of tvdb-ID
     4. `user_id`
     5. `user told: yes/no`

     Het blok verschijnt alleen als er iets in staat.
   - **Laatste regel**: `Code: <interaction_id>`.
2. **Traceback**: in de melding staat alleen de eigen code, met de binnenste frame bovenaan, plus de exceptie in de regel `Exception:`. Frames van libraries blijven weg. Staat er geen enkele eigen frame in de traceback, dan komen de laatste 3 frames erin. De volledige traceback staat in `exc` in de logregel (06).
3. **ID**: als inline code, `Code: k7p2qx`, met hetzelfde woord als in de Foutmelding (08).
   - Bij een Storing: `Code: m4t9cw (first failed attempt)`.
   - Bij een Herstelmelding: `Code: m4t9cw → r8h3ze`.
   - Geen hashtags.
4. **Taal**: Engels, net als de logregels. De soorten heten in de kop zoals `fault` in 06, met een hoofdletter:
   - 🐞 **Bug**
   - 🌩 **Disruption**
   - 🔧 **Setup**
   - ✅ **Restored** voor een Herstelmelding
5. **Opmaak**: HTML, met escapen van alleen `< > &` in elke waarde. Dat geldt voor alles wat de nieuwe meldfunctie verstuurt. Admin-meldingen die geen fout zijn, blijven voorlopig MarkdownV2 via `Log.logger()` (buiten scope).
6. **Telegram weigert de melding**:
   - De bot stuurt dezelfde tekst één keer opnieuw zonder `parse_mode`. De tags zijn eruit en de entities zijn teruggezet. Bovenaan staat `⚠️ Telegram rejected the formatting: <reden>`.
   - De weigering zelf is een Bug. Hij krijgt een ERROR-logregel met hetzelfde `interaction_id`, maar geen eigen melding.
   - Mislukt ook de platte tekst, dan blijft het bij de logregel.
7. **Lengte**: altijd één bericht van hooguit 4096 tekens. Het opknippen in stukken van 1024 tekens vervalt. Wordt een melding te lang, dan kort de bot het blok van achteren in en sluit hij af met `… truncated, see log`. Een reden van een dienst wordt afgekapt op 300 tekens.
8. **Storing**: de melding toont `Since:` met het aantal mislukte pogingen en de laatste reden. Getroffen Gebruikers of jobs komen er niet in, want daarvoor zou de bot extra moeten bijhouden. `jq` op `service` en `fault` vindt ze in het log.
9. **Herstelmelding**: toont het begin en eind, de duur, het aantal mislukte pogingen en beide codes.
10. **Na een Telegram-storing** komt er één Herstelmelding (05).
    - Inhoud:
      - begin en eind
      - de duur
      - het aantal mislukte polls
      - een lijst `Not sent meanwhile (N):` met soort, dienst en code van elke Fout waarvan de melding niet aankwam. Hooguit 10, de rest als `+N more`. Herstelmeldingen staan er niet in.
    - Hij heeft geen code, omdat pollen buiten een Interactie valt (08).
    - De bot bewaart alleen soort, dienst en code, niet de melding zelf. Zo blijft het besluit van 05 staan dat meldingen niet bewaard worden voor later.
11. **Geluid**:
    - Een melding over een Bug, Storing of Inrichtingsfout komt met geluid.
    - Een Herstelmelding komt stil binnen (`disable_notification`).
    - Uitzondering: de Herstelmelding na een Telegram-storing komt met geluid als de lijst uit besluit 10 niet leeg is.
12. **Link**: als de dienst Sonarr of Radarr is en het item daar bestaat, is de titel op de regel `Media:` een link naar dat item. Waarschijnlijk is de vorm `/movie/<tmdbId>` en `/series/<titleSlug>`. Dat wordt nagekeken bij de implementatie.

### Voorbeeld

Een Bug door een 4xx, zoals de bot hem verstuurt (HTML):

```html
🐞 <b>Bug</b> · Radarr refused the movie request
Reason: <i>This movie has already been added</i> (HTTP 400)
User: anna
Media: <a href="https://radarr…/movie/693134">Dune: Part Two (2024)</a>
<blockquote expandable><code>src/services/arr.py:98 in post
src/services/radarr.py:31 in add_movie
src/commands/movie.py:84 in start_download
src/commands/media.py:242 in media_choice</code>
tmdb 693134
user_id: 123456789
user told: yes</blockquote>
Code: <code>k7p2qx</code>
```

Een Storing en de Herstelmelding daarna:

```
🌩 Disruption · Radarr is not responding
Reason: Unable to communicate with RadarrAPI (HTTP 503)
Since: 05:02, 14 failed attempts
Code: m4t9cw (first failed attempt)

✅ Restored · Radarr is responding again
Down: 05:02 – 06:07 (1 h 5 min), 23 failed attempts
Code: m4t9cw → r8h3ze
```

De andere gevallen (geen passende state, Bug buiten de wrapper bij een Bezoeker, Inrichtingsfout in een job en bij een Gebruiker, na een Telegram-storing) staan als variant E in het prototype.

### Wat de melding nodig heeft (voor de interface)

- **Uit de Fout**: naast soort, dienst, reden en exceptie (09) ook:
  - de identificatie van het media-item (titel, jaar, tmdb- of tvdb-ID), plus wat nodig is voor de link
  - de velden waarop de beslissing viel
  - bij melden en doorwerken een korte zin voor `Continued:`
- **Uit de context**: of de Gebruiker een Foutmelding kreeg (`user told`), en de eigen frames uit de traceback.
- **De meldfunctie zelf**:
  - houdt per Storing het begin, het aantal pogingen en de laatste reden bij
  - houdt tijdens een Telegram-storing bij welke meldingen niet aankwamen
  - stuurt bij een weigering één keer opnieuw als platte tekst

### Doorgeschoven

- De inhoud van de regel `Repeat:` bij een afgeremde Inrichtingsfout. Ook of het begin van een Storing en de lijst `Not sent meanwhile` een herstart overleven: [Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?](13-herhaalde-fouten-afremmen.md)
- Waar media-item, beslisvelden, `Continued` en `user told` in de interface zitten, en hoe de meldfunctie de terugval en de lijst bijhoudt: [Welke interface krijgt de logmodule?](14-interface-logmodule.md)
