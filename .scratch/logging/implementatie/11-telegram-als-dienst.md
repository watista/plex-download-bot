# 11 Telegram als dienst

Status: dicht
Blocked by: 07, 08
Niet tegelijk met: 12 (`src/faults.py`, `src/bot.py`)

## Wat

Telegram wordt een dienst met Storingen, zoals de andere diensten. Een melding die tijdens een Storing niet aankwam, valt daarna toch op.

- **`TelegramRequest`**, een subklasse van `HTTPXRequest`, ingesteld via `.request()` en `.get_updates_request()`:
  - roept bij elk geslaagd antwoord `faults.ok("telegram")` aan, ook bij het pollen
  - geeft `getUpdates` geen `http_call`; de andere requests wel, op DEBUG
  - telt mislukte pogingen niet zelf
- **`error_handler`**:
  - elke `NetworkError` bij het pollen is een mislukte poging van een Storing van Telegram: WARNING, `fault: disruption`, `service: telegram`, zonder `interaction_id`
  - een `TimedOut` bij het pollen blijft een DEBUG-regel van PTB
  - een Conflict bij de start blijft één WARNING zonder `fault`
- **Tijdens een Storing van Telegram** telt `report()` de poging en verstuurt hij niets. Een `NetworkError` bij het versturen van een admin-melding of Foutmelding telt ook als poging.
- **`Not sent meanwhile`**: per Fout waarvan de melding niet aankwam, soort, dienst en code; niet de melding zelf. De lijst staat in `faults.json`.
- **De Herstelmelding na de Storing** komt als hij aanhield of als de lijst niet leeg is:
  - begin, eind, duur en het aantal mislukte polls
  - `Not sent meanwhile (N):`, hooguit 10, de rest als `+N more`
  - geen Code
  - met geluid als de lijst niet leeg is, anders stil
- **De volgorde bij de start**: de meldfunctie heeft de verzendfunctie nodig, die de `Bot`, en die `TelegramRequest`, die `faults.ok` aanroept. Een van de drie krijgt zijn partner pas na het aanmaken.

## Spec

- [4. Regels van buiten de eigen code](../spec.md#4-regels-van-buiten-de-eigen-code), punt 4
- [Storingen](../spec.md#storingen), punt 3
- [Telegram](../spec.md#telegram), punt 14
- [10. Admin-melding bij een Fout](../spec.md#10-admin-melding-bij-een-fout), punt 11 en 12

## Klaar als

- [ ] Een test: een Storing van Telegram verstuurt niets, houdt `Not sent meanwhile` bij, en geeft daarna de Herstelmelding met de lijst.
- [ ] Op dev, met het netwerk even weg: per mislukte poll één regel (kort na de eerste), en daarna één Herstelmelding als het lang genoeg duurde.

## Aanwijzingen

- PTB vangt `RetryAfter` en `TimedOut` bij het pollen zelf af. Elke andere `TelegramError` gaat naar `error_handler`. De wachttijd loopt op van 1 tot 30 seconden.
- `HTTPXRequest.do_request` en `ApplicationBuilder.request()` en `.get_updates_request()` bestaan in PTB 21.10.0.
- In oktober waren er 805 WARNING-regels in bijna een etmaal storing.
- Een `http_call` van `TelegramRequest` met `request` en `response` zou de tekst van berichten weer in het debug-bestand zetten: wachtwoorden in de updates, en e-mail en telefoon in de admin-melding van een accountaanvraag. Issue 05 liet daarom de DEBUG-regels van PTB met berichttekst weg (`WithoutMessageText` in `src/log/__init__.py`, en [Nooit in een logregel](../spec.md#nooit-in-een-logregel)). Leg voor wat een `http_call` van Telegram dan wel krijgt, bijvoorbeeld alleen de methode, de status en de duur.

## Besluiten bij de uitvoering

Genomen op 2026-11-04. De eerste drie zijn voorgelegd en besloten op 2026-11-04, en bijgewerkt in de spec ([Inhoud](../spec.md#inhoud), punt 4, [Storingen](../spec.md#storingen), punt 3, en [10. Admin-melding bij een Fout](../spec.md#10-admin-melding-bij-een-fout), punt 11):

- **Een `http_call` van Telegram** heeft `method` (`POST`), `url` met het token als `***` (het eind is de methode van de Bot API, zoals `sendMessage`), `http_status` en `duration_ms`, of bij een exceptie `exc_type`. Geen `request` en `response`. `msg` heeft dezelfde vorm als bij de requestregel van 09: `telegram sendMessage: POST https://api.telegram.org/bot***/sendMessage: HTTP 200 in 84 ms`.
- **De regel `Down:` van de Herstelmelding na een Telegram-storing** telt alle mislukte pogingen, polls en verzendingen, met dezelfde woorden als bij de andere diensten: `… 23 failed attempts`. Bij één poging: `1 failed attempt`.
- **Tijdens een Storing van Telegram probeert de meldfunctie niets te versturen.** Een admin-melding over een Fout komt op `Not sent meanwhile`, één keer per Fout: dezelfde handtekening (Bug), sleutel (Inrichtingsfout) of dienst (Storing), met de Code van de eerste keer. De melding wordt teruggenomen zoals bij elke melding die niet aankomt, dus komt de Fout na de Storing terug, dan gaat zijn melding alsnog uit. Zo geeft een kapotte heartbeat (12) tijdens een internetstoring niet elke 5 seconden een verzendpoging en een regel op de lijst.
- **De regels tijdens een Storing van Telegram** (voorgelegd na de review en besloten op 2026-11-04): de meldfunctie beslist dan geen melding, dus een Fout die terugkomt krijgt na zijn eerste regel korte regels met `repeat`, zoals [Voor alle soorten](../spec.md#voor-alle-soorten) punt 14 zegt. De eerste keer na de Storing gaat zijn melding uit, met een volledige regel. Een Bug waarvan nog geen melding uitging, blijft daarvoor in `faults.json` staan met `last_admin_message: null`; zijn melding heeft dan geen regel `Repeat:`, want er was nog geen eerdere.
- **Wat er op de lijst staat**: `Bug · Radarr · <code>k7p2qx</code>`, met alleen de dienst en de Code die er zijn (een Storing buiten een Interactie heeft geen Code). Bij een Storing is de Code die van de poging waarbij de melding uit had moeten gaan; die heeft een volledige regel in het log.
- **Een admin-melding die niet uitgaat** krijgt één WARNING `admin message not sent: <waarover>: Telegram is not responding`: alleen de eerste keer per Fout, en bij elke Herstelmelding van een andere dienst. Die Herstelmeldingen komen niet op de lijst, zoals de spec zegt.
- **Aanhouden** wordt bij Telegram net zo bekeken als bij de andere diensten, bij elke mislukte poging (`persisted` in `faults.json`). De lijst staat als `not_sent` bij de Storing van Telegram in `faults.json`, met per Fout `key`, `fault`, `service` en `code`.
- **Komt de Herstelmelding zelf niet aan** omdat Telegram weer niet reageert, dan loopt de Storing door in de nieuwe: met zijn begin, zijn pogingen, of hij aanhield, en zijn lijst. Zo komt de Herstelmelding na een lange Storing toch, ook met een lege lijst, en noemt hij de hele periode (gevonden in de review).
- **Een Fout bij het beëindigen van de Storing** in `TelegramRequest` (bijv. `faults.json` niet te schrijven) is een Bug met `Continued: gave PTB the answer of Telegram`, en bereikt PTB niet: PTB zou er een `NetworkError` van maken, een Storing van Telegram die geen geslaagd antwoord meer kan beëindigen.
- **`error_handler`**: een fout van het pollen die `telegram_disruption` als Storing ziet (`NetworkError`, maar niet `BadRequest`) is een poging. `TimedOut` en `RetryAfter` handelt PTB bij het pollen zelf af, dus daar is geen eigen tak voor. Een `BadRequest` bij het pollen is een Bug buiten de wrapper. De Conflict-regel gaat via de nieuwe logger: `Telegram Conflict: another bot instance is polling`, met de tekst van Telegram in `reason`.
- **De volgorde bij de start**: `TelegramRequest` krijgt de meldfunctie na het aanmaken (`request.faults = …`); tot dan gaat een antwoord alleen naar PTB. De twee requests krijgen de poolgroottes die PTB zijn eigen requests geeft (256 en 1), en de `read_timeout` van 300 seconden die eerder via de builder ging.

Nog te doen: de controle op dev met het netwerk even weg (Klaar als, punt 2). Dat kan alleen de Beheerder.
