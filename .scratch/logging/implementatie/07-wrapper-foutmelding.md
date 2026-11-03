# 07 Wrapper, Foutmelding en error_handler

Status: open
Blocked by: 06
Niet tegelijk met: 04, 05, 09, 14 (handlers en `src/bot.py`)

## Wat

Fouten worden centraal afgevangen. Daarna stuurt de bot een Foutmelding met een Code en eindigt het Gesprek.

- **`guard(callback)`** in `src/interaction.py`:
  - vangt een Fault af, en elke andere exceptie als `Fault.bug`
  - roept `report(fault, user_told=…)` aan
  - stuurt daarna de Foutmelding via `send`
  - geeft altijd `ConversationHandler.END` terug
- **De Foutmelding** (Nederlands):
  1. `user_text`, of anders een standaardzin per soort
  2. "De serverbeheerder is hiervan op de hoogte" als `report()` `True` gaf, en anders dat het later nog eens kan
  3. "Stuur /start om opnieuw te beginnen."
  4. `Code: <code>`

  Bij een Storing van Telegram probeert de wrapper geen Foutmelding.
- **Eén helper in `src/bot.py`** wikkelt elke callback bij het registreren in: alle handlers in beide ConversationHandlers en de losse handlers.
- **`guard_job`** vangt ook Fouten af: hij meldt via `report()`, stuurt geen Foutmelding, en de run stopt.
- **`error_handler` als vangnet**: alles wat niet van het pollen komt en geen Conflict is, wordt een Bug met de vlag "outside the wrapper". Een Foutmelding gaat alleen uit als er een `update` met een chat is.
- **De Bugs in de handlers omzetten** naar `Fault.bug`, of de exceptie laten doorvallen. Dezelfde handlers sturen dan ook geen eigen Foutmelding of admin-melding meer.

| Geval | Waar | Fault |
|---|---|---|
| geen passende state | `src/commands/media.py:335` | `details` = de velden die het filter bekeek |
| tmdbId niet te parsen | `src/commands/serie.py:195`, `subscribe.py:116` | |
| request type niet te parsen | `src/commands/start.py:222` | |
| veld ontbreekt in de payload | `src/commands/movie.py:89`, `serie.py:87` | |
| `stats.json` niet te schrijven | `src/commands/media.py:489` | |

Daarnaast verdwijnen de eigen Foutmeldingen (`media.py:422`, `:430`, `serie.py:194`, `subscribe.py:115`) en de zin "op de hoogte" (`media.py:334`, `:412`, `start.py:221`).

## Spec

- [Afvangen](../spec.md#afvangen) en [Foutmelding](../spec.md#foutmelding)
- [De Interactie en de wrappers](../spec.md#de-interactie-en-de-wrappers), punt 17 en 18
- [ADR 0001](../../../docs/adr/0001-fouten-als-excepties-met-centrale-wrapper.md)

## Klaar als

- [ ] Elke callback in `src/bot.py` loopt via `guard` of `guard_job`.
- [ ] Tests voor de gevallen onder "Interactie" in [Tests](../spec.md#tests):
  - een Fault in een handler geeft `END` en een Foutmelding, met of zonder "op de hoogte" en met de regel `Code:`
  - bij een Storing van Telegram komt er geen Foutmelding
  - een onbekende exceptie is een Bug
- [ ] Op dev geeft een geforceerde Bug in een handler één ERROR-regel, één admin-melding en één Foutmelding met dezelfde Code.

## Niet in deze issue

- De diensten omzetten: 09, 10
- Pollfouten in `error_handler`: 11
- `guard_task`: 12

## Aanwijzingen

- PTB gooit de teruggegeven waarde van een losse handler weg, dus `END` kan daar geen kwaad. In een ConversationHandler houdt `None` de huidige state vast.
- Na een exceptie in een state-callback bleef een Gesprek tot nu toe in de oude state, zonder timeout (01). Met `END` speelt dat niet meer.
