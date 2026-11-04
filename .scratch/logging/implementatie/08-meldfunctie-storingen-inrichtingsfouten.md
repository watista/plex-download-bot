# 08 Meldfunctie: Storingen en Inrichtingsfouten

Status: bezig (branch `logging/08-meldfunctie-storingen-inrichtingsfouten`, sinds 2026-11-04)
Blocked by: 06
Niet tegelijk met: 11, 12 (`src/faults.py`)

## Wat

Het gedrag van de meldfunctie voor Storingen en Inrichtingsfouten, getest via zijn eigen interface.

**Storing**
- Hij houdt aan bij minstens 2 mislukte pogingen, de laatste minstens 15 minuten na de eerste, zonder geslaagd antwoord ertussen. Dan komt er een melding met `Since:` (begin, aantal pogingen, laatste reden) en `Code: … (first failed attempt)`.
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
