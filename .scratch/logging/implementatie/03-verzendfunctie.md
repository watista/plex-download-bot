# 03 Verzendfunctie en Gebruikersberichten

Status: dicht
Blocked by: 02
Niet tegelijk met: –

## Wat

Eén verzendfunctie naar Telegram, en elk Gebruikersbericht met een eigen regel.

- **`Fault` en `FaultKind`** in `src/faults.py`, met de velden en drie constructors uit de spec. Alleen het type; de meldfunctie volgt in 06.
- **`src/telegram_out.py`**:
  - `send(chat_id, text, fmt, silent=False)`:
    - maskeert en kapt af op 4096 tekens
    - weigert Telegram de opmaak, dan gaat het bericht één keer opnieuw als platte tekst met de regel `⚠️ Telegram rejected the formatting: <reden>`, en komt er een ERROR-regel met `fault: bug`, zonder melding
    - zet `NetworkError`, `TimedOut` en `RetryAfter` om in `Fault.disruption(service="telegram")`
    - geeft bij `Forbidden` "niet afgeleverd" terug, met de reden
  - `send_admin_message(text)`: de inhoud en MarkdownV2 blijven, en het bericht schrijft `admin_message_sent` zonder `fault`, met in `msg` waar het over ging maar niet de tekst
  - `send_user_message(user_id, kind, text, media=None)`: schrijft `user_message` op INFO met `user_id` en `account` van de ontvanger, of op WARNING met `reason` als het bericht niet aankomt
- **Omzetten**:
  - de Gebruikersberichten in `check_notify_list`, met de soorten `online`, `new_season` en `new_episodes`. De admin-melding "User notified" gaat via `send_admin_message`.
  - `/message` (`message`) en `/message_all` (`broadcast`). Een ontvanger van `/message_all` voor wie het mislukt, geeft een `user_message` op WARNING in plaats van een admin-melding.
  - `notify_admin_startup` en de start-, stop- en Conflict-berichten aan de groep: via `send_admin_message`, met dezelfde inhoud

## Spec

- [6. Gebruikersberichten en andere berichten aan de Beheerder](../spec.md#6-gebruikersberichten-en-andere-berichten-aan-de-beheerder)
- [Telegram](../spec.md#telegram), punt 11 tot en met 13
- [De Fault](../spec.md#de-fault)

## Klaar als

- [ ] Er gaat geen Gebruikersbericht uit zonder regel `user_message`.
- [ ] De omgezette berichten aan de Beheerder schrijven `admin_message_sent` en niet meer hun tekst in het log.
- [ ] Tests voor de gevallen onder "Verzendfunctie" in [Tests](../spec.md#tests):
  - de terugval op platte tekst, plus de Bug-regel
  - een `NetworkError` wordt een Fault, en `Forbidden` geeft "niet afgeleverd"
  - het maskeren en de grens van 4096 tekens
  - de regel `user_message`, of een WARNING als het mislukt

## Niet in deze issue

- Admin-berichten van Gebruikersacties (aanvraag, kwaliteitsverzoek, /help, accountaanvraag): 04, 05
- Admin-meldingen over Fouten: 06 en verder
- `faults.ok("telegram")`, en tellen tijdens een Storing van Telegram: 11
- `sent` en `not_delivered` tellen: 13

## Aanwijzingen

- Tot 07 er is, komt een Fault uit `send` terecht in `error_handler`, net als een exceptie nu.
- Admin-meldingen gaan live naar `CHAT_ID_GROUP` en in dev naar `CHAT_ID_ADMIN` (`src/log.py:100`).
- De Gebruikersberichten staan in `src/commands/schedule.py:115-120`, `:183-187` en `:236-241`, en in `src/commands/message.py`. De HTML-broadcast valt nu terug op platte tekst (`message.py:40`); dat blijft zo.
- De afmeldmelding gebruikt `self.log.escape_markdown` (`src/bot.py:376`). Die escape gaat mee naar `send_admin_message`.
