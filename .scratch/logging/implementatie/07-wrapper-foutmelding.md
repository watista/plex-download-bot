# 07 Wrapper, Foutmelding en error_handler

Status: bezig (branch `logging/07-wrapper-foutmelding`, sinds 2026-11-04)
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

## Besluiten bij de uitvoering

Genomen op 2026-11-04. Het eerste is voorgelegd en besloten op 2026-11-04.

- **Een mislukte `queue_download` is tot 09 een Bug.** Radarr en Sonarr geven tot 09 `None` terug in plaats van een Fault te gooien. `start_download` gooit dan `Fault.bug` ("Radarr did not queue the download", met `last_error` als reden), zodat de Gebruiker de Foutmelding met de Code krijgt. `queue_download` stuurt zelf geen admin-melding meer, dus er gaat één melding uit. Tot 09 telt een onbereikbare Radarr hier als Bug in plaats van als Storing, en delen alle mislukte aanvragen bij één dienst één handtekening.
- **`stats.json` niet te schrijven: melden en doorwerken** ([Afvangen](../spec.md#afvangen), punt 5). `write_to_stats` meldt een `Fault.bug` met `continued: went on without counting the request`, en het Gesprek gaat door. De aanvraag zelf is dan al gelukt, en de Gebruiker heeft al een vraag met knoppen gekregen.
- **De melding over de opslag (`:412`) blijft tot 09 een bericht van de handler**, alleen zonder "op de hoogte". 09 maakt er een Inrichtingsfout `disk_space` met `user_text` van.
- **De Foutmelding**, in HTML. De Code staat in `<code>`, zodat de Gebruiker hem met een tik kopieert:

  ```
  <b>😵 Oeps, daar ging iets fout</b>

  De serverbeheerder is hiervan op de hoogte. Stuur /start om opnieuw te beginnen.

  Code: <code>k7p2qx</code>
  ```

  Gaf `report()` `False`, dan staat er "Probeer het later nog eens." De standaardzin is bij een Bug "Oeps, daar ging iets fout", bij een Storing "Een onderdeel van de Plęx server reageert op dit moment niet" en bij een Inrichtingsfout "Er is een probleem met de inrichting van de Plęx server".
- **Geen Foutmelding buiten een Interactie.** De timeout van een Gesprek loopt in een job, zonder Interactie en dus zonder Code. Een Fout daar gaat alleen naar de meldfunctie, die hem een eigen Code geeft. Een Gesprek verloopt stil, dus de Gebruiker krijgt dan geen bericht.
- **Van het pollen** is in `error_handler` alleen een `NetworkError`, `RetryAfter` of `Conflict` zonder update, job of taak. Die blijven tot 11 zoals ze waren. Al het andere is een Bug buiten de wrapper, ook een fout bij het wegschrijven van `bot_state.pkl`: die geeft PTB ook zonder update door.
- **De interfaces**: `guard(callback, faults, send)` en `guard_job(callback, faults)`, want er komt geen object op moduleniveau ([Logregels schrijven](../spec.md#logregels-schrijven), punt 2). `error_handler` gebruikt `report_outside_wrapper(update, error, faults, send)`. `telegram_disruption(error)` in `src/telegram_out.py` is de ene regel voor "Telegram reageert niet", voor de verzendfunctie en de wrappers. `faults` komt in `Media`, `Movie` en `Serie` achter `telegram`; `logger` verdwijnt pas in 15.
- **Eén helper in `src/bot.py`**: `_guarded(handler)` wikkelt de callback in, en bij een Gesprek die van elke handler erin: de entry points, de states met de timeout, en de fallbacks. Zo kan geen handler vergeten worden. Een test controleert dat elke callback precies één keer via `guard` loopt.
- **De wrapper staat niet in de traceback.** Hij haalt zijn eigen frame eraf, zodat de eigen code in de admin-melding bij de handler begint. Een fout van de wrapper zelf houdt dat frame.
- **`media_request` met `failed`, ook als de actie een Fout gooit.** `media_option` schrijft de regel van de keuze voordat de Fout doorvalt, zodat de uitkomsten uit 04 blijven kloppen. Het zet ook `working_on(chosen)`, zodat elke Fout daarna het media-item heeft.
- **Een veld dat ontbreekt in de payload** (`tmdbId`, `tvdbId`, `title`) valt door als `KeyError`, en de wrapper maakt er een Bug van.
- **"Geen passende state"** heeft als `details` de velden die de states bekijken (`filter_fields`): bij een film `id`, `movieFileId`, `monitored` en `status`, bij een serie `path`, `monitored` en `status`.

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
