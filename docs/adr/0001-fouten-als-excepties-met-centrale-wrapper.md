# Fouten als excepties met een soort, afgevangen in een wrapper om elke handler en job

Diensten gaven een fout terug als `False`/`None` plus `last_error`, en elke aanroeper logde en meldde zelf. Daardoor ging de plek verloren waar een fout ontstond, en gaf één fout soms drie admin-meldingen. We gooien voortaan een `Fout`-exceptie met een soort (Bug, Storing, Inrichtingsfout). Die soort bepaalt de requestfunctie van de dienst; alleen een Inrichtingsfout die pas de aanroeper ziet, gooit de aanroeper zelf. Eén wrapper vangt de Fout af, schrijft de logregel, laat de admin-melding uitgaan en stuurt de Foutmelding. Die wrapper komt in `src/bot.py` bij het registreren om elke handler en job. Lokaal afvangen mag alleen om door te werken, en dan via dezelfde meldfunctie.

De vangplek is bewust niet PTB's `error_handler`. Die kan geen `ConversationHandler.END` teruggeven, dus na een fout blijft de Gebruiker in een halve state van het Gesprek hangen. `error_handler` blijft alleen het vangnet voor wat buiten de wrapper ontstaat (polling-fouten, Conflict, een fout in de wrapper zelf).

Uitgewerkt in `.scratch/logging/issues/09-excepties-lokaal-of-centraal.md`.
