# Implementatie van de logging-spec

Opgeknipt uit [spec.md](../spec.md) op 2026-11-03. Elke issue is groot genoeg voor één sessie, en na elke issue werkt de bot nog. Issue 01 laat de klasse `Log` tijdelijk bestaan als dunne laag op de nieuwe logging. De volgende issues zetten de aanroepen om, en 15 haalt de laag weg.

Een issue kan beginnen als alles onder "Blocked by" dicht is en niemand hem geclaimd heeft. "Niet tegelijk met" noemt issues die dezelfde bestanden raken: die draaien beter na elkaar, ook als ze niet op elkaar wachten.

Een issue heeft drie statussen: `open`, `bezig` en `dicht`. Er kunnen sessies tegelijk lopen, dus claim een issue voordat je eraan begint:

1. Controleer dat de issue `Status: open` heeft en dat er nog geen branch voor bestaat: `git branch -a --list '*logging/NN-*'`. Is een van beide niet zo, dan is hij geclaimd: kies een andere.
2. Maak de branch `logging/NN-<naam>` aan. Zo ziet ook een sessie in een andere worktree de claim meteen, want branches zijn gedeeld.
3. Zet in de issue ``Status: bezig (branch `logging/NN-<naam>`, sinds JJJJ-MM-DD)``, en commit alleen die regel meteen als eerste commit op de branch ("Claim issue NN").
4. Is de issue af, dan wordt het `Status: dicht`. Stop je zonder dat hij af is, zet hem dan terug op `open` en zeg waar het werk staat.

| # | Issue | Blocked by | Niet tegelijk met |
|---|---|---|---|
| 01 | [Logregels in JSONL-dagbestanden](01-logregels-jsonl.md) | – | – |
| 02 | [Interactie-context en Code](02-interactie-context.md) | 01 | – |
| 03 | [Verzendfunctie en Gebruikersberichten](03-verzendfunctie.md) | 02 | – |
| 04 | [Gebruikersacties: zoeken en aanvragen](04-gebruikersacties-zoeken-aanvragen.md) | 03 | 07, 09 |
| 05 | [Gebruikersacties: commands, login, account, help en admin](05-gebruikersacties-overig.md) | 03 | 07, 14 |
| 06 | [Meldfunctie: Bugs en de admin-melding](06-meldfunctie-bugs.md) | 03 | 08 |
| 07 | [Wrapper, Foutmelding en error_handler](07-wrapper-foutmelding.md) | 06 | 04, 05, 09, 14 |
| 08 | [Meldfunctie: Storingen en Inrichtingsfouten](08-meldfunctie-storingen-inrichtingsfouten.md) | 06 | 11, 12 |
| 09 | [Requestregel met Radarr en Sonarr](09-requestregel-arr.md) | 07, 08 | 04, 10, 13 |
| 10 | [Plex en Transmission via de requestregel](10-plex-transmission.md) | 09 | 13 |
| 11 | [Telegram als dienst](11-telegram-als-dienst.md) | 07, 08 | 12 |
| 12 | [Crash en heartbeat](12-crash-heartbeat.md) | 11 | – |
| 13 | [Geplande taken](13-geplande-taken.md) | 09, 10 | – |
| 14 | [/log](14-log-command.md) | 02 | 05, 07 |
| 15 | [Log opruimen](15-log-opruimen.md) | 03, 04, 05, 07, 09, 10, 11, 12, 13 | – |

Afspraken voor elke issue:

- De spec is de bron. Een issue noemt de onderdelen die hij uitvoert, en herhaalt ze alleen kort.
- Tests met `unittest`, zonder nieuwe dependency: `python -m unittest discover -s tests`.
- Elke issue op een eigen branch. Niet pushen of mergen zonder het te vragen.
- Is een issue af, dan zet de laatste commit op zijn branch `Status: dicht` in de issue. Een issue die daarop wacht, kan dan beginnen vanaf die branch, ook als die nog niet in `main` zit.
- Wijkt de code af van wat de spec of een issue zegt, of blijkt een besluit niet te werken: niet zelf beslissen, maar het voorleggen.
