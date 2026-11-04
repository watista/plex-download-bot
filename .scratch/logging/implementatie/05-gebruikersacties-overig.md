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
