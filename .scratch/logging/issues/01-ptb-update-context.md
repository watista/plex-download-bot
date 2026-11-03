# Hoe onderschep je in python-telegram-bot 21 elke update centraal en geef je context door?

Type: research
Status: resolved
Blocked by: –

## Question

Hoe onderschep je in python-telegram-bot 21.10 elke inkomende update op één centrale plek, en hoe geef je de gebruiker (Telegram user ID) en een interactie-ID door aan alle logregels die tijdens de afhandeling van die update ontstaan?

Uit te zoeken, met de officiële PTB-documentatie, wiki en broncode van v21.10 als bron:

- Welke mechanismen zijn er om elke update te zien vóór de gewone handlers (bijv. `TypeHandler` in group -1, een eigen `Application.process_update`), en wat is de idiomatische keuze?
- Blijft een `contextvars`-waarde staan over de taken die PTB aanmaakt: `concurrent_updates`, `application.create_task`, ConversationHandler-states, JobQueue/APScheduler-jobs?
- Wat krijgt de `error_handler` mee (update, `context.error`, `user_data`), en komen excepties uit jobs en `create_task` daar ook terecht?
- Kun je in de `error_handler` achterhalen in welke handler of conversation-state de fout ontstond?

Context in de code: `src/bot.py` (handlers, `error_handler`), `src/commands/schedule.py` (JobQueue).

## Answer

Bevindingen: branch `research/ptb-update-context` (commit `741ab19`), bestand `.scratch/logging/research/01-ptb-update-context.md`. De worktree staat in `.claude/worktrees/agent-afb62e797b94014d9`. De bronnen zijn PTB 21.10 en APScheduler 3.11.2 (docs en broncode).

- **Centrale plek**: een eigen `BaseUpdateProcessor` (`do_process_update`), ingesteld via `ApplicationBuilder.concurrent_updates(MijnProcessor(1))`. Dat is de enige gedocumenteerde plek met een moment vóór én ná de afhandeling, en met `1` blijft de verwerking sequentieel zoals nu. Een `TypeHandler` in groep -1 ziet ook elke update, maar biedt geen moment om de context te resetten.
- **Naar logregels**: zet `user_id` en `interaction_id` in `ContextVar`s, met `token = var.set(...)` en `finally: var.reset(token)` per update. Een `logging.Filter` op elke handler kopieert ze naar het record (sluit aan op ticket 02).
- **Taken**: `application.create_task`, `block=False`-handlers en per-update-taken erven de context van de update. ConversationHandler-states hebben geen eigen context: elke stap is een nieuwe update. Wil je één ID per gesprek, dan moet je dat zelf bewaren (bijv. in `user_data`).
- **JobQueue-jobs erven níet betrouwbaar**: APScheduler start jobs vanuit een callback die draait in de context van wie de scheduler het laatst wekte. In deze bot gebeurt dat bij elke `run_once` voor de `conversation_timeout`. Een job kan dus de user ID van een willekeurige eerdere update meedragen. Jobs moeten daarom zelf expliciet context zetten, bijv. via een decorator of een `JobQueue`-subclass. Niet getest, alleen afgeleid uit de broncode.
- **Error handler** krijgt `(update, context)` met `context.error`, plus `context.job` bij jobfouten en `context.coroutine` bij `create_task`. Fouten uit handlers, `create_task(update=...)`, jobs (`update=None`) en polling komen erin terecht. De kale `asyncio.create_task` van de heartbeat (`src/bot.py`) niet. Contextvars zijn in de error handler wél leesbaar.
- **Handler of state van een fout** is niet direct beschikbaar: `ConversationHandler` heeft geen publieke API voor de huidige state, en de states in `src/states.py` zijn kale ints. Er zijn drie opties: (1) de traceback doorlopen tot het eerste frame in `src/`, (2) elke callback bij registratie wrappen zodat handler- en state-naam in een contextvar komen, (3) `context.job.name` of `context.coroutine.__qualname__` gebruiken.
- **Bijvangst (geen logging)**: na een exceptie in een blocking state-callback blijft het gesprek in de oude state, terwijl de timeout-job al verwijderd is. Voor dat gesprek geldt dan geen `conversation_timeout` meer tot de volgende geslaagde stap. Niet getest.
