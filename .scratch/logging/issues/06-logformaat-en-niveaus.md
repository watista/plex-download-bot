# Welk formaat en welke logniveaus krijgen logregels?

Type: grilling
Status: resolved
Blocked by: 02
Assignee: Wouter

## Question

In welk formaat schrijven we logregels, welke velden staan er altijd in, en welk logniveau gebruiken we waarvoor?

Te beslissen:

- Tekst, JSON lines, of beide.
- Vaste velden: tijd, niveau, module, gebruiker, interactie-ID, soort gebeurtenis, en wat nog meer.
- Niveaubeleid: wat is DEBUG, INFO, WARNING, ERROR in deze bot.
- Taal van logregels (nu Engels).
- Behoud van newlines in tracebacks en JSON. Die worden nu platgeslagen door `clean_message()` in `src/log.py`, dat ook alle niet-ASCII-tekens verwijdert.

Randvoorwaarde: leesbaar via SSH (`grep`/`jq`/`less`) én machinaal leesbaar voor `/log <gebruiker>`.

## Answer

Besloten in een grilling met de beheerder op 2026-11-03, in twee rondes. Er zijn geen nieuwe begrippen bijgekomen in `CONTEXT.md`.

### Formaat

1. **Alleen JSON Lines**: in het logbestand staat één JSON-object per regel. Er komt geen tweede tekstbestand. Om via SSH te lezen, komt er een `jq`-regel in de README, zoals `jq -r '"\(.ts) \(.level) \(.account // "-") \(.event // "-") \(.msg)"'`. Of journald ernaast een rol krijgt, beslist 07.
2. **Console bij `--verbose`** (alleen voor ontwikkelen): tekst, met dezelfde weergave als die `jq`-regel: `ts level account event msg`.
3. **Taal**: alles Engels, dus veldnamen, soortnamen en berichten. Regels van de libraries zijn ook Engels, en zo bevat geen regel een mengtaal.
4. **Tekens**: UTF-8, letterlijk (`ensure_ascii=False`), dus "Amélie" en emoji blijven staan en zijn met `grep` te vinden. Newlines en andere stuurtekens escapet JSON, dus één record is altijd één regel. `clean_message()` vervalt.
5. **Opmaak van de regel**: velden zonder waarde worden weggelaten (geen `null`). Achter `,` en `:` staat een spatie, zoals `json.dumps` standaard doet.

### Niveaus

Het niveau volgt uit wat er gebeurt en bij een Fout uit de soort. Of er een admin-melding uitgaat (aanhouden, afremmen), verandert het niveau niet.

| Niveau | Wanneer | Voorbeelden |
|---|---|---|
| ERROR | Bug of Inrichtingsfout: de Beheerder moet iets rechtzetten | Radarr 400 "already added", geen passende state, serie zonder pad, lege TMDB-lookup, 401/403 |
| WARNING | Storing (elke mislukte poging), of iets onverwachts dat geen Fout is | Radarr 503, timeout, Telegram onbereikbaar, Conflict bij de start, één ontvanger van `/message_all` mislukt |
| INFO | Normale gang van zaken | elke gebruikersactie uit de catalogus van 04, gesprek verlopen, admin-melding verstuurd, Herstelmelding, start en stop van de bot |
| DEBUG | Details om te debuggen | requests en responses, tussenstappen |
| CRITICAL | niet gebruikt | |

Een Storing die aanhoudt, blijft per poging WARNING. Dat hij is opgeschaald, zie je aan de regel `admin_message_sent`. Live draait op INFO, dus alles wat `/log` moet tonen, staat op INFO of hoger.

### Velden

In deze volgorde: eerst wat je in `less` wilt zien, en de lange velden achteraan.

| Veld | Wanneer | Inhoud |
|---|---|---|
| `ts` | altijd | lokale tijd met offset en milliseconden, ISO 8601: `2026-11-03T14:05:12.345+01:00` |
| `level` | altijd | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `user_id` | als er een persoon bij is | Telegram user ID, als getal |
| `account` | bij een Gebruiker | accountnaam |
| `tg_name` | alleen bij een Bezoeker | Telegram-naam |
| `event` | bij een eigen gebeurtenis | soort, zie de tabel hieronder |
| `msg` | altijd | korte Engelse zin, platte tekst |
| per soort | waar nodig | bijv. `query`, `media_type`, `media_title`, `media_year`, `tmdb_id`, `results`, `outcome`, `duration_ms`, `http_status`, `reason` |
| `fault` | bij een Fout | `bug`, `disruption` of `setup` |
| `service` | bij een Fout of een `http_call` | `radarr`, `sonarr`, `plex`, `transmission`, `tmdb`, `telegram`, `fallback` |
| `interaction_id` | zodra 08 het invult | betekenis en vorm: 08 |
| `logger` | altijd | module van de bot of naam van de library |
| `src` | altijd | `pad:regel in functie` van de code die de regel schrijft, niet van de wrapper |
| `exc_type` | bij een exceptie | bijv. `ConnectTimeout` |
| `exc` | bij een Bug of onverwachte exceptie | volledige traceback, inclusief gekoppelde excepties |

- **Persoon**: dit verfijnt punt 2 van 04. De Telegram-naam van een Bezoeker staat niet op de plaats van de accountnaam, maar in een eigen veld `tg_name`. Een Bezoeker met de Telegram-naam "Wouter" verschijnt zo niet onder de accountnaam "Wouter". Ook regels van libraries krijgen `user_id`, `account` en `tg_name` mee, via de contextvars uit 01.
- **Niet in een regel**: de host of instantie (elk bestand staat al op zijn eigen host) en de pid.
- **Voorbeeld** van een gebruikersactie:

```json
{"ts": "2026-11-03T14:05:12.345+01:00", "level": "INFO", "user_id": 123456789, "account": "wouter", "event": "search_term", "msg": "searched 'dune' for movie: 7 results", "query": "dune", "media_type": "movie", "results": 7, "logger": "commands.media", "src": "src/commands/media.py:60 in search"}
```

### Soort Fout

Het glossarium zet "outage" en "error" op de lijst van woorden die je niet gebruikt. Daarom krijgen de soorten Fout Engelse namen die daar niet mee botsen. Het glossarium blijft gelden voor hoe we over Fouten praten.

| `CONTEXT.md` | `fault` |
|---|---|
| Bug | `bug` |
| Storing | `disruption` |
| Inrichtingsfout | `setup` |

### Soortnamen (`event`)

Een voorstel voor de namen: de taal is besloten, de afzonderlijke namen zijn niet apart besproken. De soorten volgen de catalogus van 04.

| Soort (04) | `event` |
|---|---|
| command | `command` |
| menukeuze | `menu_choice` |
| login | `login` |
| zoekterm | `search_term` |
| zoekknop | `search_button` |
| aanvraag | `media_request` |
| melding | `notify_choice` |
| kwaliteitsverzoek | `quality_request` |
| serie-updates | `series_updates` |
| algemene updates | `general_updates` |
| accountaanvraag | `account_request` |
| help-vraag | `help_question` |
| admin | `admin_command` |
| buiten gesprek | `outside_conversation` |
| genegeerd | `ignored` |
| gesprek verlopen | `conversation_expired` |
| admin-melding verstuurd | `admin_message_sent`, met `fault`; bij een Herstelmelding `restored: true` |
| start en stop van de bot | `bot_started`, `bot_stopped` |
| request en response naar een dienst (DEBUG) | `http_call` |

### Inhoud

1. **Een leesbare zin plus velden.** Elke regel heeft een `msg` die op zichzelf leesbaar is in `less` en met `grep`. Alles waarop `/log` en `jq` filteren, staat daarnaast in aparte velden. Dat de informatie dubbel staat, is de bedoeling: regels van libraries hebben alleen `msg`.
2. **Platte tekst.** `msg` wordt nooit geëscapet voor MarkdownV2.
3. **Uitsluitingen van 04 gelden voor alle velden**, ook `msg`: geen wachtwoord, e-mail, telefoon of tekst buiten een Gesprek.
4. **Geen grote gegevens boven DEBUG.** Een complete response of een compleet mediaobject staat nooit in een regel boven DEBUG. Wel:
   - de identificatie: titel, jaar, tmdbId
   - bij een 4xx de reden van de dienst in `reason`, zoals "This movie has already been added"
   - bij een Bug de velden waarop de beslissing viel, zoals bij "geen passende state" de velden die het filter bekeek
   
   Bij geval 5 uit 03 stond de complete JSON er wel, en toch was niet terug te vinden waarom niets paste.
5. **`http_call` op DEBUG** vervangt de tekstregel van `debug_call`, met `service`, `method`, `url`, `http_status`, `duration_ms`, en `request` en `response` afgekapt op `LOG_MAX_BODY`.
6. **Tracebacks.** Bij een Bug of een onverwachte exceptie komen `exc_type` en een volledige `exc`, met gekoppelde excepties ("During handling of the above exception"); `jq -r .exc` toont hem weer over meerdere regels. Bij een Storing of Inrichtingsfout komen alleen `exc_type` en de tekst van de exceptie in `msg`. Een traceback wordt nooit met de hand in `msg` geplakt.

### Feiten uit de code (voor de implementatie)

- Eigen regels lopen nu via `Log.log_to_file()` in `src/log.py`, dat `logging.error()` en dergelijke direct aanroept. Daardoor is `logger` altijd `root` en wijst de codeplek altijd naar `src/log.py`. De nieuwe interface moet de aanroeper doorgeven, bijvoorbeeld met `stacklevel` of met een logger per module.
- `Log.logger()` escapet de tekst voor MarkdownV2 en schrijft die geëscapete tekst ook naar het bestand. Live staat daardoor bijvoorbeeld `Notify: New episode\(s\)` in het log.
- Een traceback met `traceback.format_exc()` in de tekst, ook bij timeouts: `src/services/arr.py:114`, `:121`, `:174`, `:181`, `src/services/plex.py:54`, `:100`, `:126`, `src/services/transmission.py:59`, `src/commands/media.py:489`, `src/bot.py:533`.
- De byte-check van `/log` uit 02 (`"user_id": 123`) hangt af van de separators. Die liggen nu vast: een spatie na `:`.

### Doorgeschoven

- Bestandsnamen en extensie, het debug-bestand en journald: [Hoe worden logbestanden opgeslagen en geroteerd?](07-opslag-en-rotatie.md)
- Wat `interaction_id` betekent en hoe het eruitziet: [Hoe koppelen we logregels van één interactie, en een melding aan de logregel?](08-interactie-id-en-fout-id.md)
- Of `/log` zoekt op `account`, `tg_name` of `user_id`: [Wat toont /log <gebruiker>, en voor wie?](11-log-command.md)
- Op welk niveau regels van libraries binnenkomen, en de startcrash: [Wat komt er van buiten de eigen code in de logregels?](12-ruis-buiten-eigen-code.md)
- Herhaalde regels voor dezelfde Fout: [Hoe remmen we herhaalde admin-meldingen en logregels bij fouten af?](13-herhaalde-fouten-afremmen.md)
- Hoe de code deze regels schrijft: "Hoe de code straks logt" in Not yet specified.
