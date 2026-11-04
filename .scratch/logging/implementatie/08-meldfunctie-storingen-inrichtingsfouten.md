# 08 Meldfunctie: Storingen en Inrichtingsfouten

Status: dicht
Blocked by: 06
Niet tegelijk met: 11, 12 (`src/faults.py`)

## Wat

Het gedrag van de meldfunctie voor Storingen en Inrichtingsfouten, getest via zijn eigen interface.

**Storing**
- Hij houdt aan bij minstens 2 mislukte pogingen, de laatste minstens 15 minuten na de eerste, zonder geslaagd antwoord ertussen. Dan komt er een melding met `Since:` (begin en aantal pogingen; de laatste reden staat op `Reason:`) en `Code: … (first failed attempt)`.
- Herinneringen na 1, 3 en 7 dagen, bij de eerste mislukte poging na de tussenpoos, met `Repeat: 2nd alert · next alert …`.
- `ok(service)` beëindigt hem. Ging er een melding uit, dan volgt een stille Herstelmelding `✅ Restored` met begin, eind, duur, pogingen en `Code: … → …`. Zonder open Storing kost `ok` bijna niets.
- Elke poging geeft een WARNING-regel: volledig bij de eerste en bij een melding, anders kort.

**Inrichtingsfout**
- De sleutel is dienst + `check` + `item`; bij opslag vol alleen dienst + `check`.
- Hij wordt meteen gemeld, gevolgd door Herinneringen na 1, 3 en 7 dagen, met `Repeat: 3rd alert · failing since … (96×) · next alert …`.
- Hij telt per run, niet per aanroep.
- `fixed(service, check, item, msg)`: ging er een melding uit, dan volgt een stille `✅ Fixed` met wat rechtgezet is, de periode, hoe vaak, en `Code: eerste → nu`. Anders ruimt hij alleen de toestand op.
- Een Inrichtingsfout die 30 dagen niet voorkwam, verdwijnt stil.

Alles staat in `faults.json`. Er is geen noodrem en geen bundeling.

## Spec

- [9. Afremmen en toestand](../spec.md#9-afremmen-en-toestand), [Storingen](../spec.md#storingen) en [Inrichtingsfouten](../spec.md#inrichtingsfouten)
- [De meldfunctie](../spec.md#de-meldfunctie), punt 9
- [10. Admin-melding bij een Fout](../spec.md#10-admin-melding-bij-een-fout), punt 9, 10 en 12

## Klaar als

- [ ] Tests met een nep-klok en een nep-verzendfunctie:
  - een Storing houdt aan na 2 pogingen over 15 minuten
  - `ok` geeft alleen een Herstelmelding als er een melding uitging
  - Herinneringen na 1, 3 en 7 dagen
  - een Inrichtingsfout wordt meteen gemeld, en `fixed` geeft een stille Herstelmelding
  - een Inrichtingsfout verdwijnt na 30 dagen zonder melding
  - twee aanroepen in één run tellen als één keer

## Niet in deze issue

- Storingen van Telegram (niets versturen, `Not sent meanwhile`): 11
- Aanroepen vanuit de diensten: 09, 10, 12

## Besluiten bij de uitvoering

Genomen op 2026-11-04. De eerste drie zijn voorgelegd en besloten op 2026-11-04, en bijgewerkt in de spec ([Voor alle soorten](../spec.md#voor-alle-soorten), punt 12, en [10. Admin-melding bij een Fout](../spec.md#10-admin-melding-bij-een-fout), punt 1 en 8):

- **De eigen code staat alleen in de melding over een Bug**, zoals in variant E van het prototype. Bij een Inrichtingsfout zegt de controle die hem gooit al wat er mis is.
- **De melding over een Storing gaat over de dienst**: zonder `User:`, `Visitor:` of `Job:`, zonder `Media:` en het tmdb- of tvdb-ID, en zonder `user_id`. De Code is die van de eerste mislukte poging.
- **Twee verschrijvingen in de spec**: het voorbeeld `3rd alert … next alert 8 Oct` paste niet bij de tussenpozen (wordt `12 Oct`), en de laatste reden van een Storing staat op `Reason:`, niet in `Since:`.
- **Een Storing van Telegram houdt voorlopig alleen zijn volledige regel.** 11 telt de pogingen, met korte regels, `Not sent meanwhile` en de Herstelmelding. Zo stuurt de meldfunctie ook niets via de dienst die niet reageert.
- **Een melding die niet aankomt, gaat de volgende keer opnieuw**, net als bij een Bug (06): bij een Storing bij de volgende mislukte poging, bij een Inrichtingsfout als hij weer voorkomt. `report()` geeft dan `False`, tenzij er over die Fout al eerder een melding uitging.
- **`repeat` in een korte regel** telt de keren sinds de laatste volledige regel. Een tweede aanroep in dezelfde run krijgt ook een korte regel, maar telt niet mee in "hoe vaak".
- **Tijden en duur**: `Since: 05:02` als het vandaag is, anders `1 Nov 17:37`, met het jaar als het niet dit jaar is. De duur is `45 min`, `1 h 5 min`, of vanaf een dag in hele dagen (`2 days`).
- **De regel `Code:` van een Herstelmelding** toont alleen de Codes die er zijn. Buiten een Interactie is er geen, zoals bij de Herstelmelding na een Telegram-storing (10.11).
- **In `faults.json`** staan naast `bugs` nu `disruptions` (per dienst) en `setup` (per sleutel), elk met `admin_messages`, `last_admin_message` en `repeat`. Een Inrichtingsfout heeft daarnaast `times`, `last_seen`, `last_code` en de Code van de eerste melding, een Storing `attempts`, `last_reason` en de Code van de eerste poging.

Bekende beperking: het tellen per run onthoudt alleen de Code van de laatste run. Raakt een andere Interactie dezelfde Inrichtingsfout tussen twee aanroepen van één run, dan telt die run twee keer. Dat vraagt dezelfde sleutel twee keer in één run met iemand ertussen, en is daarom zo gelaten.

Voor 09, 10 en 12: `ok(service)` hoort bij elk geslaagd antwoord (in de requestregel en `TelegramRequest`), `fixed(service, check, item, msg)` bij elke controle die slaagt, en opslag vol is een `Fault.setup` zonder `item`.
