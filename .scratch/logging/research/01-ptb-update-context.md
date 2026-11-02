# 01: Centrale update-context voor logging in python-telegram-bot 21.10

> Onderzoeksticket voor het logging-redesign · 2026-11-02 · branch `research/ptb-update-context`
> Versies: python-telegram-bot 21.10, APScheduler 3.11.2 (geïnstalleerd; de `job-queue`-extra van PTB 21.10 vraagt `apscheduler>=3.10.4,<3.12.0`), Python 3.12.

**Vraag.** Hoe onderschep je in PTB 21.10 elke inkomende update op één centrale plek, en hoe geef je de Telegram user-ID en een interaction-ID mee aan elk logrecord dat ontstaat terwijl die update wordt afgehandeld?

**Bronnotatie.** `PTB <bestand>:<regels>` verwijst naar de broncode van de geïnstalleerde wheel `python-telegram-bot==21.10` (`env/lib/python3.12/site-packages/telegram/ext/…`, dezelfde bestanden als tag [v21.10 op GitHub](https://github.com/python-telegram-bot/python-telegram-bot/tree/v21.10/telegram/ext)). `APS <bestand>:<regels>` verwijst naar `site-packages/apscheduler/…` (3.11.2). `repo <bestand>:<regels>` verwijst naar deze repository.

---

## Antwoord

- **Centrale plek.** Het idioom dat de PTB-docs beschrijven is een `TypeHandler(Update, callback)` in groep `-1` (blocking). Die ziet elke `Update` vóór groep 0. Er is alleen geen moment ná de afhandeling, dus een `ContextVar` kun je daar wel zetten maar niet netjes resetten. De schoonste *gedocumenteerde* plek met een moment ervóór én erna is een eigen `BaseUpdateProcessor` (`do_process_update(update, coroutine)`), in te stellen via `ApplicationBuilder.concurrent_updates(MijnProcessor(1))`. Met `1` blijft de huidige sequentiële verwerking precies hetzelfde. `Application.process_update` overschrijven via `application_class` werkt ook, maar is niet als extensiepunt gedocumenteerd.
- **Naar de logrecords.** Zet `user_id` en `interaction_id` in `contextvars.ContextVar`s en kopieer ze naar elk `LogRecord` met een `logging.Filter` op elke handler (of met `logging.setLogRecordFactory`). Dan krijgen ook de records van `telegram.*`, `httpx` en dergelijke die velden.
- **Sequentiële verwerking (deze repo) vraagt om reset.** Met `concurrent_updates(False)` draait de afhandeling van alle updates in één langlevende fetcher-task. Een `set()` zonder `reset()` blijft daar dus staan tot de volgende update, met verouderde (stale) IDs tot gevolg. Gebruik daarom altijd `token = var.set(...)` met `finally: var.reset(token)`.
- **contextvars in PTB-tasks.** asyncio kopieert de context op het moment dat een task *wordt aangemaakt*. Per-update-tasks (`concurrent_updates>1`), `application.create_task(...)` en `block=False`-handlers (ook binnen een `ConversationHandler`) erven daardoor de waarden van de update. Wat zo'n task daarna zelf zet, lekt niet terug.
- **ConversationHandler-states** hebben geen eigen context. Elke stap is een nieuwe update die via de centrale plek nieuwe waarden krijgt. Wil je één ID per gesprek, dan moet je dat zelf bewaren (bijvoorbeeld in `user_data`).
- **JobQueue-jobs erven níet betrouwbaar.** APScheduler start een job met `loop.create_task` vanuit een callback die via `call_soon_threadsafe`/`call_later` is ingepland. Die callback draait in de context van degene die de scheduler het laatst heeft "gewekt", bijvoorbeeld elke `run_once` voor `conversation_timeout=1800` binnen een update. Een job kan dus de user-ID van een willekeurige eerdere update meedragen. Oplossing: zet in elke job expliciet eigen waarden, met een decorator of met een `JobQueue`-subclass die `job_callback` overschrijft.
- **Wat de error handler krijgt.** De aanroep is `(update, context)`, met `context.error`. Daarnaast `context.user_data`/`chat_data` (afgeleid van `update`, of van `job.user_id`/`job.chat_id`), `context.job` bij jobfouten en `context.coroutine` bij `create_task`/`block=False`. Het is een *nieuw* `CallbackContext`-object, dus eigen attributen op de handler-context zijn verdwenen. Het draait wel in dezelfde asyncio-task als de fout (of in een kopie daarvan), dus contextvars zijn wél leesbaar.
- **Welke fouten de error handler bereiken, en met welke `update`.** Handlerfouten: ja, met die update. `block=False` en `application.create_task(coro, update=...)`: ja, met de meegegeven `update` (standaard `None`). Jobs: ja, met `update=None` en `context.job` gevuld. Pollingfouten: ja, met `update=None`. Een kale `asyncio.create_task` (de heartbeat in `bot.py`): nee.
- **In welke handler of state ging het mis?** Dat krijg je niet direct: `process_error` krijgt geen handler mee, en `ConversationHandler` heeft geen publieke API voor de huidige state. Praktische opties: (1) de traceback doorlopen (`traceback.extract_tb`, eerste frame in `src/`); (2) elke callback bij registratie wrappen, zodat handler- en state-naam in een contextvar komen of via `add_note` aan de exceptie hangen; (3) voor jobs en tasks `context.job.name` of `context.coroutine.__qualname__` gebruiken.
- **Bijvangst.** Na een exceptie in een blocking state-callback blijft het gesprek in de oude state. De timeout-job is dan al verwijderd zonder vervanging, dus voor dat gesprek geldt geen `conversation_timeout` meer tot de volgende geslaagde stap.

---

## 1. Context in deze repo

- `repo src/bot.py:92-101`: de builder gebruikt `.concurrent_updates(False)`. Dat wordt `SimpleUpdateProcessor(1)` (`PTB _applicationbuilder.py:1103-1112`), wat ook de default is (`PTB _applicationbuilder.py:204-208`).
- `repo src/bot.py:104-113`: één `ConversationHandler`, plus `/help` en `/privacy` als losse handlers, allemaal in groep 0. Er zijn geen negatieve groepen en nergens `block=False`.
- `repo src/bot.py:116`, `504-534`: de error handler gebruikt `update` niet en logt alleen de traceback (`533`).
- `repo src/bot.py:119-120`: twee `run_once`-jobs (lambda's die `application.create_task(...)` aanroepen). `124-126`: drie `run_repeating`-jobs.
- `repo src/bot.py:214`: `conversation_timeout=1800`. `repo src/states.py`: de states zijn kale ints uit `range(30)`, dus hun namen zijn tijdens runtime niet meer beschikbaar.
- `repo src/bot.py:317`: een kale `asyncio.create_task` voor de heartbeat, aangemaakt in `post_init`.
- `repo src/log.py`: het format `"%(asctime)s - %(levelname)s - %(name)s: %(message)s"`, zonder velden voor user of interaction. Alle handlers (bestand, debugbestand, console) hangen aan de root-logger.

## 2. Elke update op één plek onderscheppen

### 2.1 Hoe PTB een update verwerkt

1. De fetcher-task (eenmalig aangemaakt in `start()`, `PTB _application.py:628-629`) haalt updates uit `update_queue` (`PTB _application.py:1224-1244`).
2. Is `max_concurrent_updates > 1`, dan maakt de fetcher per update een task met `self.create_task(self.__process_update_wrapper(update), ...)`. Anders `await`-t hij die wrapper direct in de fetcher-task (`PTB _application.py:1236-1244`).
3. De wrapper roept `self._update_processor.process_update(update, self.process_update(update))` aan (`PTB _application.py:1257-1261`). `BaseUpdateProcessor.process_update` neemt een semafoor en roept `do_process_update` aan (`PTB _baseupdateprocessor.py:142-157`). `SimpleUpdateProcessor.do_process_update` doet alleen `await coroutine` (`PTB _baseupdateprocessor.py:170-182`).
4. `Application.process_update` (`PTB _application.py:1263-1343`):
   - doorloopt de groepen in oplopende volgorde (`add_handler` sorteert de dict, `1404-1406`);
   - gebruikt per groep hooguit één handler (`break`, `1326`);
   - bouwt één `CallbackContext` per update (`1293-1306`);
   - `await`-t blocking handlers en maakt voor `block=False` een task met `self.create_task(...)` (`1309-1325`);
   - stopt bij `ApplicationHandlerStop` met alle volgende groepen (`1329-1331`);
   - stuurt andere excepties naar `process_error` (`1333-1337`).

Docs: [Application.process_update](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.application.html#telegram.ext.Application.process_update), [Application.add_handler](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.application.html#telegram.ext.Application.add_handler), [ApplicationBuilder.concurrent_updates](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.applicationbuilder.html#telegram.ext.ApplicationBuilder.concurrent_updates).

### 2.2 Optie A: `TypeHandler` in groep -1 (het PTB-idioom)

- De wiki-pagina [Frequently requested design patterns, "Type Handler and Groups" / "Boilerplate Code"](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Frequently-requested-design-patterns#type-handler-and-groups) registreert een `TypeHandler(Update, callback)` met `app.add_handler(handler, -1)`. Ze schrijft "A lower group means a higher priority." en "An update can be processed by (at most) one handler in each group."
- Het officiële voorbeeld [contexttypesbot.py](https://docs.python-telegram-bot.org/en/v21.10/examples.contexttypesbot.html) doet `application.add_handler(TypeHandler(Update, track_users), group=-1)`.
- `TypeHandler.check_update` is gewoon `isinstance(update, self.type)` (`PTB _handlers/typehandler.py:96-98`), dus het matcht elke `Update`.

Wat dit betekent voor ons doel:

- **+** Het is het gedocumenteerde patroon. Je kunt er ook `ApplicationHandlerStop` mee gooien, bijvoorbeeld voor toegangscontrole.
- **+** Een `ContextVar.set()` in de callback blijft na terugkeer gelden in dezelfde task, want een `await` maakt geen nieuwe context (zie §3.1).
- **−** Er is geen moment ná de afhandeling. Bij sequentiële verwerking blijft de waarde in de fetcher-task staan tot de volgende update. Een voorbeeld: PTB's eigen `_LOGGER.debug("Processing update %s", update)` (`PTB _application.py:1234`) voor update N+1 draagt dan nog de IDs van update N. Een "opruim"-`TypeHandler` in een hoge groep is geen garantie, want een `ApplicationHandlerStop` stopt alle volgende groepen (`PTB _application.py:1329-1331`), en de `ConversationHandler` geeft een `ApplicationHandlerStop` uit een state-callback ook door (`PTB _handlers/conversationhandler.py:853-855, 884-894`).
- **−** De handler moet `block=True` blijven. Met `block=False` draait de callback in een eigen task (`PTB _application.py:1309-1322`) en blijft de `set()` daar opgesloten. Zie ook de waarschuwing in de [TypeHandler-docs](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.typehandler.html): "When setting block to False, you cannot rely on adding custom attributes to telegram.ext.CallbackContext."
- Variant: een eigen attribuut op `context` zetten. Dat kan, want PTB maakt één context per update ([CallbackContext-note](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.callbackcontext.html), `PTB _callbackcontext.py:53-66`; `__slots__` bevat `"__dict__"`, `116-126`). Maar een logrecord kan daar niet bij, en de error handler krijgt een nieuw contextobject (§4.1). Voor logging valt deze variant dus af.

### 2.3 Optie B: eigen `BaseUpdateProcessor` (aanbevolen voor set + reset)

- Docs: [BaseUpdateProcessor](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.baseupdateprocessor.html) zegt "An abstract base class for update processors. You can use this class to implement your own update processor." Over `do_process_update`: "Custom implementation of how to process an update. Must be implemented by a subclass."
- [ApplicationBuilder.concurrent_updates](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.applicationbuilder.html#telegram.ext.ApplicationBuilder.concurrent_updates) accepteert een `bool`, een `int` of een `BaseUpdateProcessor`-instantie. De wiki [Concurrency](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Concurrency) ("Tailor-made Concurrency") beschrijft het subclassen. De design-patterns-wiki ([rate-limit-tip](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Frequently-requested-design-patterns#how-do-i-rate-limit-users-of-my-bot)) verwijst ernaar voor bewerkingen die vóór alle handlers moeten gebeuren.
- `max_concurrent_updates=1` is toegestaan; alleen waarden onder 1 geven een `ValueError` (`PTB _baseupdateprocessor.py:70-74`). Bij 1 `await`-t de fetcher direct (`PTB _application.py:1236-1244`), dus het gedrag blijft gelijk aan nu. Dat is belangrijk, want de [ConversationHandler-docs](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.conversationhandler.html) waarschuwen dat de handler "heavily relies on incoming updates being processed one by one".
- `coroutine` is `self.process_update(update)` en wordt pas binnen `do_process_update` ge-`await`. Alle blocking handlers vallen daardoor binnen je `try/finally`, net als `process_error` voor hun fouten (`PTB _application.py:1334-1335`).
- **−** Dit dekt alleen updates die via `update_queue` binnenkomen (polling en webhook), niet handmatige aanroepen van `application.process_update(...)`. Die komen in deze repo niet voor.
- **−** `update` is getypeerd als `object`, dus je hebt een `isinstance(update, Update)`-check nodig. Verder suggereert de naam dat de klasse voor concurrency bedoeld is. Het gebruik als "middleware" past binnen de documentatie, maar is ongebruikelijk.

### 2.4 Optie C: subclass van `Application` die `process_update` overschrijft

- [ApplicationBuilder.application_class](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.applicationbuilder.html#telegram.ext.ApplicationBuilder.application_class) ("Sets a custom subclass instead of telegram.ext.Application.", `PTB _applicationbuilder.py:340-365`) maakt een subclass officieel mogelijk.
- `process_update` is een publieke, gedocumenteerde methode. **Docs zwijgen** echter over het overschrijven ervan als haak. Technisch dekt het hetzelfde als optie B plus handmatige `process_update`-aanroepen. Het risico is dat je afhankelijk wordt van PTB's interne volgorde.

### 2.5 Vergelijking

| | A: `TypeHandler` groep -1 | B: `BaseUpdateProcessor` | C: `process_update` overschrijven |
|---|---|---|---|
| Gedocumenteerd patroon | ja (wiki + voorbeeld) | ja (extensiepunt) | subclass wel, overschrijven niet |
| Moment ervóór | ja | ja | ja |
| Moment erna / `reset()` | nee | ja (`try/finally`) | ja (`try/finally`) |
| Error handler bij blocking fouten ziet de waarden | ja | ja | ja |
| Kan update stoppen (`ApplicationHandlerStop`) | ja | nee | n.v.t. |
| Lek naar de volgende update bij sequentiële verwerking | ja, tenzij elke update overschrijft | nee | nee |

### 2.6 Van contextvar naar logrecord

- In de Python logging cookbook gebruiken ["Use of contextvars"](https://docs.python.org/3.12/howto/logging-cookbook.html#use-of-contextvars) en ["Using Filters to impart contextual information"](https://docs.python.org/3.12/howto/logging-cookbook.html#using-filters-to-impart-contextual-information) een `logging.Filter` die de contextvars leest en als attributen op het `LogRecord` zet. In het contextvars-voorbeeld hangt die filter aan een *handler*.
- Hang de filter aan de handlers, niet aan de root-logger. De [logging-docs (Filter Objects)](https://docs.python.org/3.12/library/logging.html#filter-objects) zeggen: "events which have been generated by descendant loggers will not be filtered by a logger's filter setting, unless the filter has also been applied to those descendant loggers." In `src/log.py` hangen alle handlers aan root, dus een filter per handler ziet ook de doorgepropageerde records van `telegram.*`, `httpx` en `apscheduler`.
- Een alternatief is [`logging.setLogRecordFactory`](https://docs.python.org/3.12/library/logging.html#logging.setLogRecordFactory). Dan krijgt elk record de attributen, ongeacht welke handler het verwerkt.
- PTB's eigen loggers heten onder meer `telegram.ext.Application`, `telegram.ext.ConversationHandler` en `telegram.ext.JobQueue` (`telegram/_utils/logging.py:30-40`; `PTB _application.py:82`, `_jobqueue.py:51`, `_handlers/conversationhandler.py:47`).
- **User-ID.** `update.effective_user` kan `None` zijn, bijvoorbeeld bij channel posts en polls ([Update.effective_user](https://docs.python-telegram-bot.org/en/v21.10/telegram.update.html#telegram.Update.effective_user)). PTB leidt `user_data` op dezelfde manier af (`PTB _callbackcontext.py:345-352`).
- **Interaction-ID.** `update.update_id` is volgens de [Bot API](https://core.telegram.org/bots/api#update) uniek en oplopend, maar wordt willekeurig gekozen als er een week geen updates zijn geweest. Jobs hebben er bovendien geen. Een zelf gegenereerd kort ID (uuid) is dus robuuster; `update_id` kun je één keer ernaast loggen. Dit is een ontwerpkeuze voor de volgende stap.

### 2.7 Schets (niet uitgevoerd, alleen ter illustratie)

```python
import contextvars, logging, uuid
from telegram import Update
from telegram.ext import BaseUpdateProcessor, JobQueue

user_id_var = contextvars.ContextVar("user_id", default="-")
interaction_id_var = contextvars.ContextVar("interaction_id", default="-")

class ContextFilter(logging.Filter):           # aan elke handler in log.py hangen
    def filter(self, record):
        record.user_id = user_id_var.get()
        record.interaction_id = interaction_id_var.get()
        return True

class LoggingUpdateProcessor(BaseUpdateProcessor):
    async def do_process_update(self, update, coroutine):
        user = update.effective_user if isinstance(update, Update) else None
        t_user = user_id_var.set(user.id if user else "-")
        t_iid = interaction_id_var.set(uuid.uuid4().hex[:8])
        try:
            await coroutine                      # process_update + error handler voor blocking fouten
        finally:
            interaction_id_var.reset(t_iid)
            user_id_var.reset(t_user)
    async def initialize(self): pass
    async def shutdown(self): pass

class LoggingJobQueue(JobQueue):                 # zie §3.4
    @staticmethod
    async def job_callback(job_queue, job):
        user_id_var.set(job.user_id or "-")
        interaction_id_var.set(f"job-{uuid.uuid4().hex[:8]}")
        await JobQueue.job_callback(job_queue, job)

# Application.builder()...concurrent_updates(LoggingUpdateProcessor(1)).job_queue(LoggingJobQueue())
```

## 3. Overleven contextvars de tasks die PTB aanmaakt?

### 3.1 De asyncio-regels

- [`asyncio.create_task`](https://docs.python.org/3.12/library/asyncio-task.html#asyncio.create_task) en [`loop.create_task`](https://docs.python.org/3.12/library/asyncio-eventloop.html#asyncio.loop.create_task): "The current context copy is created when no context is provided." Uit de [`Task`-docs](https://docs.python.org/3.12/library/asyncio-task.html#asyncio.Task): "If no context is provided, the Task copies the current context and later runs its coroutine in the copied context."
- [`loop.call_soon`](https://docs.python.org/3.12/library/asyncio-eventloop.html#asyncio.loop.call_soon) en [`loop.call_later`](https://docs.python.org/3.12/library/asyncio-eventloop.html#asyncio.loop.call_later); `call_soon_threadsafe` heeft hetzelfde `context=`-argument. Een callback draait in de context van het moment waarop hij werd ingepland. In CPython doet [`Handle.__init__`](https://github.com/python/cpython/blob/3.12/Lib/asyncio/events.py) `context = contextvars.copy_context()` als er geen context is meegegeven, en `Handle._run` doet `self._context.run(...)`.
- Een `await coro` maakt geen nieuwe context. De coroutine draait in de context van de omringende task, want de task plant elke stap in met `call_soon(self.__step, context=self._context)` ([`Lib/asyncio/tasks.py`](https://github.com/python/cpython/blob/3.12/Lib/asyncio/tasks.py)). [`ContextVar.set`](https://docs.python.org/3.12/library/contextvars.html#contextvars.ContextVar.set) werkt "in the current context". Een `set()` in een ge-`await`-te callback is daarom na terugkeer ook zichtbaar voor de aanroeper in dezelfde task.
- Een kopie is een momentopname ([`copy_context`](https://docs.python.org/3.12/library/contextvars.html#contextvars.copy_context)). Een latere `set()` of [`reset(token)`](https://docs.python.org/3.12/library/contextvars.html#contextvars.ContextVar.reset) in de oorspronkelijke context raakt een al gemaakte task niet, en omgekeerd ook niet.
- Terzijde: [`asyncio.to_thread`](https://docs.python.org/3.12/library/asyncio-task.html#asyncio.to_thread) geeft de context mee aan de thread ("the current contextvars.Context is propagated").

### 3.2 Per mechanisme

| Mechanisme | Hoe PTB het start | Erft de waarden van de update? | Bron |
|---|---|---|---|
| Sequentieel (`concurrent_updates(False)`, deze repo) | `await` in de ene fetcher-task | Ja, dezelfde task. Zonder `reset()` ziet de *volgende* update ze ook. | `PTB _application.py:628-629, 1236-1244` |
| `concurrent_updates(n>1)` | `self.create_task(__process_update_wrapper(update))` per update | Ja: kopie van de fetcher-context. Wat je in `do_process_update` of een `TypeHandler` zet, blijft in die task. | `PTB _application.py:1236-1242` |
| `application.create_task(coro)` | `asyncio.create_task(self.__create_task_callback(...))` | Ja, een momentopname bij de aanroep | `PTB _application.py:1141-1169` (r. 1152) |
| Handler met `block=False` | `self.create_task(coroutine, update=update, ...)` | Ja | `PTB _application.py:1309-1322` |
| CH: blocking state-callback | `await handler.handle_update(...)`; de CH zelf is altijd blocking | Ja, dezelfde task | `PTB _handlers/conversationhandler.py:308-312, 841-844` |
| CH: `block=False` state-callback | `application.create_task(handler.handle_update(...), update=update)` | Ja | `PTB _handlers/conversationhandler.py:845-852` |
| CH: timeout inplannen na `block=False` | `application.create_task(self._schedule_job_delayed(...))` | Ja (maar de job zelf: zie 3.4) | `PTB _handlers/conversationhandler.py:869-878` |
| CH: `WAITING`-handlers | Gewone afhandeling binnen de update | Ja | `PTB _handlers/conversationhandler.py:752-759` |
| CH: timeout / `TIMEOUT`-handlers | JobQueue-job (`run_once(self._trigger_timeout, ...)`) | **Nee**, zie 3.4 | `PTB _handlers/conversationhandler.py:683-704, 921-958` |
| JobQueue (`run_once`, `run_repeating`, ...) | APScheduler `AsyncIOExecutor`, `loop.create_task` | **Niet betrouwbaar**, zie 3.4 | `APS executors/asyncio.py:41-45` |
| Error handler | In dezelfde task als de fout, of in een nieuwe task die daarvan een kopie is | Ja | §4.1 |
| Kale `asyncio.create_task` (heartbeat) | — | Kopie van het moment van aanmaken (`post_init`: leeg) | `repo src/bot.py:317` |

### 3.3 ConversationHandler in detail

- De `ConversationHandler` zet zijn eigen `self.block` altijd op `True`, "so that CH can take care of any non-blocking logic internally" (`PTB _handlers/conversationhandler.py:308-312`). `process_update` `await`-t de CH dus altijd binnen de update-task.
- Welke `block` een state-handler krijgt, volgt de volgorde handler → CH → `Defaults` (`PTB _handlers/conversationhandler.py:827-838`). `block=True` betekent `await` (842-844), `block=False` betekent `application.create_task(..., update=update)` (845-852). In beide gevallen zijn de waarden van de huidige update zichtbaar.
- Een state is alleen data in `_conversations` en heeft geen eigen task of context. De volgende stap van hetzelfde gesprek is een nieuwe update en krijgt via de centrale plek (§2) nieuwe waarden. Een ID dat het hele gesprek moet overspannen, moet je dus zelf opslaan (bijvoorbeeld in `context.user_data` bij het entry point). **Docs zwijgen** hierover.
- Deze repo gebruikt nergens `block=False`. Alle callbacks draaien dus nu in de update-task.

### 3.4 JobQueue / APScheduler in detail (de belangrijkste valkuil)

De keten, uit de broncode:

1. `JobQueue.run_once`, `run_repeating` en de andere `run_*`-methodes roepen `self.scheduler.add_job(self.job_callback, ...)` aan (`PTB _jobqueue.py:318`; idem `444`, `521`, `604`, `667`).
2. Draait de scheduler al, dan roept `_real_add_job` `self.wakeup()` aan (`APS schedulers/base.py:1092-1094`). Dat gebeurt ook in `modify_job` (`587-588`) en `start` (`217-218`). Vóór de start worden jobs alleen geparkeerd (`APS schedulers/base.py:505-506`). Dat is het geval voor de `run_*`-aanroepen in `Bot.__init__`.
3. `AsyncIOScheduler.wakeup` is gedecoreerd met `run_in_event_loop`, en dat doet `self._eventloop.call_soon_threadsafe(wrapped)` (`APS schedulers/asyncio.py:9-15, 66-70`). De wakeup draait dus in een momentopname van de context van *degene die `add_job` aanriep*.
4. In die context loopt `_process_jobs()` en daarin `executor.submit_job(...)` (`APS schedulers/base.py:1195`). Vervolgens maakt `AsyncIOExecutor._do_submit_job` de job-task aan met `self._eventloop.create_task(coro)` (`APS executors/asyncio.py:41-45`), dus met een kopie van die context. Daarna zet `_start_timer` de volgende wakeup klaar met `call_later(wait_seconds, self.wakeup)` (`APS schedulers/asyncio.py:56-59`), opnieuw in dezelfde context. Die context blijft zo hangen in de timer-keten tot iemand anders `wakeup()` aanroept.
5. PTB: `job_callback` → `Job.run` → `asyncio.shield(self._run(...))`, wat nog een kopie oplevert (`PTB _jobqueue.py:223-245, 966-980`). Bij een fout volgt `application.create_task(application.process_error(None, exc, job=self))` (`PTB _jobqueue.py:998-1002`).

**Gevolg in deze repo.** Bij vrijwel elke conversatiestap roept `ConversationHandler._schedule_job` `run_once(self._trigger_timeout, 1800, ...)` aan, binnen de context van die update (`PTB _handlers/conversationhandler.py:856-880, 683-704`). De eerstvolgende run van `check_notify_list` of `scan_missing_media` start daarna in een kopie van die context. Zonder eigen waarden logt zo'n job dus met de user- en interaction-ID van een ongerelateerde, eerdere update. Ook APScheduler's eigen `"Running job ..."`-log (`APS executors/base.py:179`) valt vóór `await job.func(...)` (`181`) en draagt die oude waarden altijd. Hetzelfde geldt voor de logs in `_process_jobs`.

**Verificatie.** Dit is afgeleid uit de broncode van PTB 21.10, APScheduler 3.11.2 en de asyncio-docs. Ik heb het niet empirisch gedraaid: de WSL-venv kon in deze sessie niet uitgevoerd worden. Een kleine test in de implementatiefase (twee updates, daarna een job die `user_id_var.get()` logt) bevestigt het snel. **De docs (PTB en APScheduler) zwijgen** over contextpropagatie naar jobs.

**Opties:**
- Een decorator rond elke eigen job-callback die eigen waarden zet. Die dekt de interne CH-timeoutjob (`_trigger_timeout`) niet.
- Een `JobQueue`-subclass met een eigen `job_callback`, ingesteld via [`ApplicationBuilder.job_queue`](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.applicationbuilder.html#telegram.ext.ApplicationBuilder.job_queue). Die dekt álle jobs, ook de CH-timeout. Dit werkt omdat `add_job` `self.job_callback` gebruikt (`PTB _jobqueue.py:318, 667`). [`JobQueue.job_callback`](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.jobqueue.html#telegram.ext.JobQueue.job_callback) is gedocumenteerd; de Tip noemt hem bewust static "rather than a bound method" om de APScheduler-integratie hanteerbaar te maken. Maar **docs zwijgen** over het overschrijven ervan als extensiepunt.
- Bij `job.user_id` en `job.chat_id` krijg je alleen iets als je ze bij `run_*` meegeeft. De CH-timeoutjob geeft ze niet mee (`PTB _handlers/conversationhandler.py:698-702`).

## 4. De error handler

### 4.1 Wat hij krijgt

- Signatuur: `async def callback(update: Optional[object], context: CallbackContext)`; de fout staat in `context.error` ([add_error_handler](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.application.html#telegram.ext.Application.add_error_handler), `PTB _application.py:1789-1822`).
- `process_error(update, error, job=None, coroutine=None)` bouwt per error handler een context met `CallbackContext.from_error(...)` (`PTB _application.py:1833-1879`). `from_error` werkt zo (`PTB _callbackcontext.py:272-323`):
  - is `update` niet `None`, dan `from_update`: `chat_id`/`user_id` komen uit `effective_chat`/`effective_user`, dus `context.user_data` en `context.chat_data` werken (`325-353`);
  - anders, als er een `job` is, `from_job`: `user_id`/`chat_id` komen uit `job.user_id`/`job.chat_id` en `context.job` wordt gezet (`355-377`);
  - anders een kale context.
  - Daarna worden `context.error` en `context.coroutine` gezet.
- Zie de [CallbackContext-attributen](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.callbackcontext.html). `coroutine` is er "Only present in error handlers if the error was caused by an awaitable run with Application.create_task or a handler callback with block=False". `job` is er ook in error handlers "if the error is caused by a job".
- Het is een **nieuw** contextobject. Eigen attributen die je op de handler-context hebt gezet, en `args` en `matches`, zijn er dus niet. Het officiële [errorhandlerbot-voorbeeld](https://docs.python-telegram-bot.org/en/v21.10/examples.errorhandlerbot.html) gebruikt `context.error`, `update.to_dict()`, `context.chat_data` en `context.user_data`.
- **In welke task de error handler draait, en dus welke contextvars hij ziet:**
  - Fout in een blocking handler: inline in `process_update` (`PTB _application.py:1334-1335`), dus in dezelfde task. Met optie B zit hij nog binnen de `try` en zijn de waarden gezet.
  - `create_task` of `block=False`: in die task zelf (`PTB _application.py:1217`).
  - Job: in een nieuwe task die vanuit de job-task is aangemaakt, dus met een kopie (`PTB _jobqueue.py:998-1002`).
  - Error handler met `block=False`: in een nieuwe task met een kopie (`PTB _application.py:1891-1902`).
  - Let op: reset je een var in een `finally` *binnen* de falende callback, dan is die waarde al weg voordat de error handler draait.

### 4.2 Welke fouten bereiken hem, en met welke `update`

| Bron van de fout | Bereikt error handler? | `update` | `context.job` | `context.coroutine` | `user_data` | Bron |
|---|---|---|---|---|---|---|
| Blocking handler-callback (incl. CH-states) | ja | de `Update` | `None` | `None` | via update | `PTB _application.py:1333-1337` |
| Handler met `block=False` (ook binnen CH) | ja | de `Update` (PTB geeft hem mee) | `None` | `handler.handle_update(...)`-coroutine | via update | `PTB _application.py:1315-1317, 1217`; `conversationhandler.py:846-851` |
| `application.create_task(coro)` zonder `update` | ja | `None` | `None` | jouw coroutine | `None` | `PTB _application.py:1101-1139, 1217` |
| `application.create_task(coro, update=u)` | ja | `u` | `None` | jouw coroutine | via `u` | idem; [docs](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.application.html#telegram.ext.Application.create_task) |
| Job-callback | ja | `None` | de `Job` | `None` | via `job.user_id` (anders `None`) | `PTB _jobqueue.py:998-1002`; [wiki](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Exceptions,-Warnings-and-Logging) |
| CH-timeout (`TIMEOUT`-handlers) | ja, als jobfout | `None` (de update zit privé in `job.data`) | interne job | `None` | `None` | `PTB _handlers/conversationhandler.py:51-61, 698-702, 921-958` |
| Polling (`getUpdates`) | ja | `None` | `None` | `None` | `None` | `PTB _application.py:865-866` |
| Fout in de error handler zelf | nee, alleen `_LOGGER.exception` | — | — | — | — | `PTB _application.py:1904-1913, 1206-1211` |
| `ApplicationHandlerStop` in non-blocking code | nee, alleen een waarschuwing | — | — | — | — | `PTB _application.py:1199-1203` |
| Bouwen van de `CallbackContext` mislukt | nee, `_LOGGER.critical` en de update wordt overgeslagen | — | — | — | — | `PTB _application.py:1296-1305` |
| Kale `asyncio.create_task` (heartbeat) | nee; asyncio logt hooguit "never retrieved" bij garbage collection | — | — | — | — | [asyncio-dev](https://docs.python.org/3.12/library/asyncio-dev.html#detect-never-retrieved-exceptions) |

Specifiek voor deze repo: in `run_once(lambda _: self.application.create_task(self.publish_command_list()))` (`repo src/bot.py:119-120`) komt een fout in `publish_command_list` binnen met `update=None` *en zonder* `context.job`. De job is dan namelijk al klaar, en de task is los gestart zonder job-informatie. Alleen `context.coroutine` (`__qualname__` = `Bot.publish_command_list`) verraadt de bron.

De [wiki "Exceptions, Warnings and Logging"](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Exceptions,-Warnings-and-Logging) noemt handler- en job-callbacks, en `update=None` bij jobs. **Hij zwijgt** over `create_task` en `block=False`; dat gedrag komt uit de docstrings van `create_task` en `CallbackContext.coroutine` en uit de broncode.

## 5. Kan de error handler zien in welke handler of state het misging?

### 5.1 Wat PTB níet biedt

- `process_error` krijgt alleen `update`, `error`, `job` en `coroutine` mee (`PTB _application.py:1833-1839`), geen handler.
- De [ConversationHandler-docs](https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.conversationhandler.html) hebben geen publiek attribuut voor de actuele state van een gesprek. `states` is alleen de mapping van state naar handlers. De live state staat in het private `_conversations` (en de key komt uit het private `_get_key`). Daarop bouwen is af te raden.
- Bij blocking fouten is `context.coroutine` `None`. Bij `block=False` is het de `handle_update`-coroutine van de handler (`PTB _application.py:1307, 1315`), en `BaseHandler.handle_update` doet zelf `await self.callback(...)` (`PTB _handlers/basehandler.py:135-158`). `__qualname__` geeft dan `BaseHandler.handle_update` en niet je callback.

### 5.2 Praktische opties

1. **Traceback doorlopen.** De exceptie is door de frame van je callback heen gepropageerd. Met [`traceback.extract_tb(context.error.__traceback__)`](https://docs.python.org/3.12/library/traceback.html#traceback.extract_tb) neem je de frames waarvan het pad onder `src/` valt; de bovenste daarvan is (meestal) de callback, bijvoorbeeld `Movie.request_media`. Dit vraagt geen extra code in de handlers en werkt voor alle bronnen. De repo formatteert de traceback al (`repo src/bot.py:533`).
2. **Wrappen bij registratie.** In `_build_normal_conversation` (`repo src/bot.py:153-217`) is per state-key bekend welke callbacks er zijn. Een helper zoals `track("REQUEST_MOVIE", self.movie.request_media)` kan `handler`- en `state`-contextvars zetten. Gebruik namen als strings, want de states zijn ints uit `range(30)`. De error handler draait in dezelfde task (§4.1) en ziet ze dus. Reset ze dan *niet* in een `finally`, of hang de informatie aan de exceptie met [`BaseException.add_note`](https://docs.python.org/3.12/library/exceptions.html#BaseException.add_note) (Python 3.11+); notes verschijnen automatisch in de geformatteerde traceback. Bijkomend voordeel: elke logregel binnen een state krijgt dan ook de state-naam.
3. **Jobs en tasks.** Bij jobs geven `context.job.name` (default `callback.__name__`) en `context.job.callback` de bron. Bij `create_task` geeft `context.coroutine.__qualname__` (zie [inspect: coroutine-attributen](https://docs.python.org/3.12/library/inspect.html#types-and-members)) de functienaam.
4. **Onofficieel, met voorbehoud.** PTB geeft non-blocking handler-tasks de naam `Application:<bot_id>:process_update_non_blocking:<handler>`, waarbij `repr(handler)` er als `ClassName[callback=<qualname>]` uitziet (`PTB _application.py:1318-1321`; `_handlers/basehandler.py:100-112`). Omdat de error handler in die task draait (`1217`), geeft `asyncio.current_task().get_name()` dan de callback. Die naamgeving is echter geen gedocumenteerde API. Voor CH-interne `block=False`-tasks staat er alleen het `update_id` in (`PTB _handlers/conversationhandler.py:851`).
5. **Werkt niet:** een eigen attribuut op de handler-context, want de error handler krijgt een nieuw object (§4.1).

### 5.3 Bijvangst: de state van een gesprek na een exceptie

- **Blocking.** De exceptie verlaat `handle_update` bij `await handler.handle_update(...)` (`PTB _handlers/conversationhandler.py:842`), dus `_update_state` (`888-889`) wordt niet bereikt en de state blijft ongewijzigd. De oude timeout-job is aan het begin al verwijderd (`820-825`) en er wordt geen nieuwe ingepland (`856-880` wordt niet bereikt). Gevolg: er geldt geen `conversation_timeout` meer voor dat gesprek tot de volgende geslaagde stap.
- **`block=False`.** `PendingState.resolve` valt bij een exceptie terug op de oude state (`PTB _handlers/conversationhandler.py:79-97`), en `_schedule_job_delayed` plant geen timeout in (`666-674`).
- **Docs zwijgen** hierover; dit volgt alleen uit de broncode.

## 6. Waar de docs zwijgen (samengevat)

- Nergens in de PTB-docs of de wiki-pagina [Concurrency](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Concurrency) staat iets over `contextvars`.
- Er is geen gedocumenteerde "middleware" of haak voor na een update. Voor ervóór is er `TypeHandler` in groep -1; voor eigen verwerking is er `BaseUpdateProcessor`.
- Contextpropagatie naar JobQueue-jobs: niets in de docs van PTB of APScheduler. De conclusie in §3.4 komt puur uit de broncode plus de asyncio-docs, en is niet empirisch getest.
- Het overschrijven van `JobQueue.job_callback` en `Application.process_update` is niet expliciet als extensiepunt beschreven.
- De state van een `ConversationHandler` na een exceptie is niet gedocumenteerd.
- De wiki "Exceptions, Warnings and Logging" noemt geen fouten uit `create_task` of `block=False`.

## 7. Bronnen

**PTB-documentatie v21.10**
- https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.typehandler.html
- https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.application.html (`process_update`, `add_handler`, `create_task`, `process_error`, `add_error_handler`)
- https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.applicationbuilder.html (`application_class`, `concurrent_updates`, `job_queue`)
- https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.baseupdateprocessor.html
- https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.basehandler.html
- https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.callbackcontext.html
- https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.conversationhandler.html
- https://docs.python-telegram-bot.org/en/v21.10/telegram.ext.jobqueue.html#telegram.ext.JobQueue.job_callback
- https://docs.python-telegram-bot.org/en/v21.10/telegram.update.html#telegram.Update.effective_user
- https://docs.python-telegram-bot.org/en/v21.10/examples.contexttypesbot.html
- https://docs.python-telegram-bot.org/en/v21.10/examples.errorhandlerbot.html

**PTB-wiki**
- https://github.com/python-telegram-bot/python-telegram-bot/wiki/Frequently-requested-design-patterns (#type-handler-and-groups, #boilerplate-code, #how-do-i-rate-limit-users-of-my-bot)
- https://github.com/python-telegram-bot/python-telegram-bot/wiki/Concurrency
- https://github.com/python-telegram-bot/python-telegram-bot/wiki/Exceptions,-Warnings-and-Logging

**Broncode**
- PTB 21.10 (geïnstalleerde wheel; tag: https://github.com/python-telegram-bot/python-telegram-bot/tree/v21.10): `telegram/ext/_application.py`, `_applicationbuilder.py`, `_baseupdateprocessor.py`, `_callbackcontext.py`, `_jobqueue.py`, `_handlers/typehandler.py`, `_handlers/basehandler.py`, `_handlers/conversationhandler.py`, `telegram/_utils/logging.py`
- APScheduler 3.11.2 (geïnstalleerd): `apscheduler/schedulers/asyncio.py`, `apscheduler/schedulers/base.py`, `apscheduler/executors/asyncio.py`, `apscheduler/executors/base.py`
- CPython 3.12: https://github.com/python/cpython/blob/3.12/Lib/asyncio/events.py, https://github.com/python/cpython/blob/3.12/Lib/asyncio/tasks.py

**Python-documentatie 3.12**
- https://docs.python.org/3.12/library/asyncio-task.html (`create_task`, `Task`, `to_thread`)
- https://docs.python.org/3.12/library/asyncio-eventloop.html (`call_soon`, `call_later`, `create_task`)
- https://docs.python.org/3.12/library/asyncio-dev.html#detect-never-retrieved-exceptions
- https://docs.python.org/3.12/library/contextvars.html
- https://docs.python.org/3.12/howto/logging-cookbook.html#use-of-contextvars
- https://docs.python.org/3.12/library/logging.html#filter-objects, #logging.setLogRecordFactory
- https://docs.python.org/3.12/library/traceback.html#traceback.extract_tb
- https://docs.python.org/3.12/library/exceptions.html#BaseException.add_note
- https://docs.python.org/3.12/library/inspect.html#types-and-members

**Telegram Bot API**
- https://core.telegram.org/bots/api#update (`update_id`)
