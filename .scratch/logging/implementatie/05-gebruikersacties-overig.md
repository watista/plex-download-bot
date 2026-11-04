# 05 Gebruikersacties: commands, login, account, help en admin

Status: bezig (branch `logging/05-gebruikersacties-overig`, sinds 2026-11-04)
Blocked by: 03
Niet tegelijk met: 07, 14 (`src/bot.py`, `start.py`)

## Wat

De rest van de catalogus, en vangnetten zodat ook genegeerde invoer en een verlopen Gesprek een regel krijgen.

| `event` | Gegevens | Uitkomst |
|---|---|---|
| `command` | welk command, ook `/stop` | in maintenance mode: onderhoudsbericht |
| `menu_choice` | welke knop in het startmenu of het /help-menu | in maintenance mode: onderhoudsbericht |
| `login` | nooit de tekst | gelukt + accountnaam / fout (poging n van 3) / geblokkeerd / geweigerd |
| `general_updates` | aan of uit | gewijzigd / stond al zo |
| `account_request` | alleen de naam letterlijk; bij e-mail, telefoon en "via" alleen "beantwoord" | – |
| `help_question` | tekst letterlijk | – |
| `admin_command` | `/message`, `/message_all`, `/add_movie` met hun gegevens | `/message_all`: aantal verstuurd en overgeslagen |
| `outside_conversation` | niet de tekst | `/start` getoond |
| `ignored` | soort invoer, stap van het Gesprek, waarde van de knop of het command; niet de tekst | – |
| `conversation_expired` | de stap waarin het Gesprek was | – |

- **Een vangnet voor `ignored`**: tekst terwijl de bot op een knopdruk wacht, een knop uit een oud bericht, een onbekend command.
- **`conversation_expired`** via een `ConversationHandler.TIMEOUT`-state.
- **De admin-berichten in deze bestanden die geen fout zijn**, gaan via `send_admin_message`: geblokkeerde login, eerste login, geblokkeerd, de /help-keuzes, een vraag en een accountaanvraag. E-mail en telefoon uit een accountaanvraag komen zo niet meer in het log.

## Besluiten bij de uitvoering

Genomen op 2026-11-04. De eerste drie wijken af van de letter van de spec en zijn voorgelegd (zie [Open](#open)):

- **Een command of knop in een menu krijgt altijd zijn regel** `command` of `menu_choice`; een admin-command alleen `admin_command`. Volgt er in dezelfde Interactie een regel van een andere soort, dan staat die er los achter: `/aanmelden_updates` geeft `command` plus `general_updates`, en een geblokkeerde Bezoeker die op 🎬 Film drukt geeft `menu_choice` plus `login` (`refused`).
- **Het vangnet staat na alle handlers**, buiten de ConversationHandler. Zo vangt het ook wat buiten een Gesprek binnenkomt: een knop uit een oud bericht, `/stop` zonder Gesprek, en een command midden in een Gesprek dat daar niet werkt, zoals `/start` of `/message`. Van een command komt alleen het command zelf in de regel, zonder argumenten en zonder `@botnaam`.
- **In maintenance mode** krijgt een Gebruiker die op 🎬 Film drukt `menu_choice` met `outcome: maintenance`. Een Bezoeker logt eerst in en krijgt de onderhoudsmelding daarna; zijn regel `login` heeft gewoon `outcome: success`, en geen regel noemt de onderhoudsmelding.
- **`conversation_expired` heeft geen Code**: een Gesprek verloopt in een job, buiten een Interactie. De regel krijgt zelf `user_id` met `account` of `tg_name`.
- **Een handler schrijft zijn regel zelf**, zodat `logger` en `src` van die handler zijn. `src/conversation.py` levert alleen de inhoud van de regels die meerdere handlers delen: `log.info(**command_or_choice_line(update))` en `ignored_line(update, step)`.
- **De velden**:

  | `event` | Velden |
  |---|---|
  | `command` | `command` (`/start`), `outcome: maintenance` |
  | `menu_choice` | `menu` (`start`, `help`), `button` (de callback_data), `outcome: maintenance` |
  | `login` | `outcome`: `success` met `logged_in_as`, `wrong_password` met `attempt`, `blocked` met `attempt: 3`, `refused` |
  | `general_updates` | `choice` (`on`, `off`), `outcome` (`changed`, `unchanged`) |
  | `account_request` | `question` (`name`, `email`, `phone`, `via`); alleen bij `name` ook `name` |
  | `help_question` | `text` |
  | `admin_command` | `command`, plus per stap `recipient`, `text`, `tmdb_id`; `/message_all` met `sent`, `not_delivered` en `skipped`; een ID dat geen getal is: `outcome: not_a_number`, zonder de invoer |
  | `outside_conversation` | `outcome: start_shown` |
  | `ignored` | `input` (`text`, `command`, `button`, `other`), `step`, en `button` of `command` |
  | `conversation_expired` | `step` |

  `step` is de naam van de state in kleine letters, zoals `verify_pwd`.

## Open

Voorgelegd op 2026-11-04:

- **Het debug-bestand bevat wel wachtwoorden.** Bij `LOG_TYPE=DEBUG` schrijft PTB op DEBUG de tekst van elk bericht weg: `telegram.Bot` de respons van elke `getUpdates` en de parameters van elke `sendMessage`, en `telegram.ext.Application` elke update ("Processing update"). Zo komen wachtwoorden, en e-mail en telefoon uit een accountaanvraag (ook via de admin-melding), in het debug-bestand. Het debug-bestand krijgt volgens de spec alles van libraries vanaf DEBUG ([3. Bestanden](../spec.md#3-bestanden)), en dat botst met [Nooit in een logregel](../spec.md#nooit-in-een-logregel). De eigen regels en het hoofdbestand hebben het wachtwoord niet.
- **`/stop` zonder Gesprek en een bekend command midden in een Gesprek worden `ignored`.** De spec noemt `/stop` "een gewone command-actie" en `ignored` alleen voor "een onbekend command".
- **Twee regels voor één actie**: `command` of `menu_choice`, met daarachter `general_updates` of `login`. Uitgangspunt 5 wil de uitkomst "in dezelfde regel".
- **Een Bezoeker in maintenance mode**: geen regel noemt de onderhoudsmelding na het inloggen.

## Spec

- [5. Gebruikersacties](../spec.md#5-gebruikersacties)
- [Nooit in een logregel](../spec.md#nooit-in-een-logregel)

## Klaar als

- [ ] Op dev geeft elke soort uit de tabel één INFO-regel. Ook in maintenance mode.
- [ ] Een wachtwoord komt in geen enkele vorm in het log, ook niet bij een verkeerde poging of als het na een time-out opnieuw gestuurd wordt.
- [ ] Een test voor het vangnet: een knop uit een oud bericht geeft `ignored` met de waarde van de knop.

## Niet in deze issue

- `/log` en zijn regel `admin_command`: 14
- Fouten in deze handlers: 07

## Aanwijzingen

- Genegeerde invoer heeft nu geen handler: de ConversationHandler laat die stil vallen (`src/bot.py:153`).
- Nu niet gelogd: algemene updates aan of uit (`src/commands/message.py:51`), en foute wachtwoordpogingen 1 en 2 (`src/commands/start.py:166`).
- E-mail en telefoon staan nu in het log via de kopie van de admin-melding (`src/commands/account.py:89`).
- Een knop uit een oud bericht terwijl de bot wacht op de keuze van een serie om af te melden, vangt `Subscribe.afmelden_optie` zelf af ("Deze knop hoort niet bij de lijst", `src/commands/subscribe.py`). Het vangnet ziet die dus niet: hij heeft daar een eigen regel `ignored` nodig. Issue 04 liet hem liggen voor 05.
