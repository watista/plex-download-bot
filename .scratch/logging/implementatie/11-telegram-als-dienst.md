# 11 Telegram als dienst

Status: open
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
