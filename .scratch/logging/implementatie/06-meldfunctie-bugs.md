# 06 Meldfunctie: Bugs en de admin-melding

Status: bezig (branch `logging/06-meldfunctie-bugs`, sinds 2026-11-04)
Blocked by: 03
Niet tegelijk met: 08 (`src/faults.py`)

## Wat

De meldfunctie, met eerst alleen het pad voor een Bug, getest via zijn eigen interface. Hij wordt nog nergens aangesloten.

- **`FaultReporter.report(fault, user_told=False, continued=None) -> bool`** in `src/faults.py`:
  - **De logregel** van elke Fout: het niveau volgt de soort, met `fault`, `service`, `reason`, `http_status`, `details`, de media-velden, `exc_type` en `exc` (alleen bij een Bug). `src` is de binnenste eigen frame. Volledig bij de eerste keer en bij een melding, daartussen kort met `repeat: n`.
  - **Bug**:
    - de handtekening: dienst, type exceptie, binnenste eigen frame, en bij een 4xx de status
    - hooguit één melding per 24 uur per handtekening
    - de regel `Repeat: 4× since the last alert (…)`
  - **Storing en Inrichtingsfout**: voorlopig alleen de logregel, zonder melding, en `report()` geeft `False` terug. Het echte gedrag komt in 08.
  - Geeft `True` terug als de Beheerder van deze Fout weet.
- **De toestand** in `faults.json` (dev: `faults.dev.json`), bijgewerkt onder één lock. Hij overleeft een herstart.
- **De HTML-melding**:
  - een kop met 🐞 **Bug** en `what`
  - `Exception:` of `Reason:` (hooguit 300 tekens)
  - `User:`, `Visitor:` of `Job:`
  - `Media:`
  - `Continued:`, en een vlag voor "Caught by error_handler, outside the wrapper"
  - een uitklapbaar blok met de beslisvelden, de eigen frames (de binnenste bovenaan, of de laatste 3 frames als er geen eigen frame is), het tmdb- of tvdb-ID, `user_id` en `user told`
  - `Code:` als inline code
  - escapen van `< > &`, inkorten tot 4096 tekens met `… truncated, see log`
  - verstuurd via `send`, met `admin_message_sent` en `fault`
- **`working_on(media)`** in `src/interaction.py`. De meldfunctie neemt het media-item uit de context als de Fault er zelf geen heeft.
- **`.gitignore`** en de `.stignore`-patronen in de README krijgen `faults.json` en `faults.dev.json`.

## Spec

- [De meldfunctie](../spec.md#de-meldfunctie), punt 8
- [Bugs](../spec.md#bugs), [Voor alle soorten](../spec.md#voor-alle-soorten) (punt 12 tot en met 14)
- [10. Admin-melding bij een Fout](../spec.md#10-admin-melding-bij-een-fout)
- [13. Buiten de code](../spec.md#13-buiten-de-code)

## Klaar als

- [ ] Tests met een nep-verzendfunctie en een nep-klok:
  - een Bug geeft één melding per 24 uur per handtekening
  - de toestand overleeft een nieuwe reporter op hetzelfde bestand
  - een volledige of korte regel met `repeat`
  - wat `report()` teruggeeft
  - de opbouw van de HTML-melding, met het voorbeeld uit de spec (Radarr 400)

## Niet in deze issue

- Aansluiten op handlers en jobs: 07
- Storingen, Inrichtingsfouten, Herinneringen, `ok` en `fixed`: 08
- Telegram tijdens een Storing en `Not sent meanwhile`: 11
- `report_crash`: 12
- De link naar Sonarr of Radarr op de regel `Media:`: 09

## Aanwijzingen

- Het prototype van de melding staat op de branch `prototype/admin-melding-bij-fout` (`src/prototype_admin_melding.html`, variant E). Die branch staat niet op de Mac, maar waarschijnlijk in WSL.
- Jobs en updates lopen door elkaar op dezelfde event loop, vandaar het lock.
