# 15 Log opruimen

Status: open
Blocked by: 03, 04, 05, 07, 09, 10, 11, 12, 13
Niet tegelijk met: –

## Wat

De dunne laag uit 01 verdwijnt, en daarmee de klasse `Log`.

- De klasse `Log` met `logger`, `debug_call`, `send_telegram_message`, `clean_message`, `truncate` en `escape_markdown` verdwijnt. `escape_markdown` gaat mee naar de plek die hem nog nodig heeft (`src/bot.py:376`).
- De parameter `logger` verdwijnt uit de constructors. Waar de meldfunctie nodig is, komt `faults` ervoor in de plaats. Tests geven een nep-meldfunctie mee, zoals `tests/test_movie_states.py` nu een `MagicMock`.
- De README en `dot-env.template` worden nagelopen op resten.

## Spec

- [Wat verdwijnt](../spec.md#wat-verdwijnt)
- [Logregels schrijven](../spec.md#logregels-schrijven), punt 2

## Klaar als

- [ ] `grep -rn "self.log\.\|debug_call\|last_error\|NoLibraryChatter\|LOOKUP_ALERT_THRESHOLD" src main.py dot-env.template README.md` geeft niets.
- [ ] Alle tests zijn groen, en de bot start op dev in normal mode en in maintenance mode.
