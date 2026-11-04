#!/usr/bin/python3

""" Requestregel: one request to a service, with its attempts, an http_call per attempt, and the Fault it ends in """

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any

import aiohttp

from src.faults import Fault, FaultKind, cut_reason, service_name
from src.log import get_logger

if TYPE_CHECKING:
    from src.faults import FaultReporter


log = get_logger(__name__)

# The seconds between two attempts, after a Storing
RETRY_WAIT = 3

# The setting with the key of a service, which a 401 or 403 says is wrong
KEYS = {"radarr": "RADARR_API", "sonarr": "SONARR_API"}

# What an attempt raises when the service cannot be reached: a Storing. A client converts the exceptions of its
# library to one of these.
UNREACHABLE = (aiohttp.ClientError, ConnectionError, TimeoutError)


@dataclass(frozen=True)
class Answer:
    """ The answer to one attempt: the HTTP status, the body (JSON or text), and the reason the service gave """
    status: int
    body: Any = None
    reason: str | None = None


async def call(service: str, action: str, attempt: Callable[[], Awaitable[Answer]], faults: "FaultReporter",
               retries: int = 3, *, method: str | None = None, url: str | None = None, request: Any = None) -> Any:
    """ The whole course of a request to a service, in up to retries attempts: gives back the body of its answer.

    attempt does one attempt and gives back its Answer; action says what the request is for, like "movie request".
    The answer, or the exception of a service that cannot be reached, is sorted out as in the table of the spec:
    a Storing is tried again and only raised after the last attempt, a 4xx is a Bug, and a 401 or 403 an
    Inrichtingsfout of the key. Any other exception falls through as it is. A successful answer ends a Storing of
    the service in faults, the meldfunctie, and passes the check of its key.

    Every attempt gets an http_call on DEBUG with method, url (without the key) and request, which say what was sent.
    """

    def http_call(number: int, started: float, answer: Answer | None = None, error: Exception | None = None) -> None:
        """ The line of one attempt, on DEBUG: what was sent, and the answer or the exception """
        duration_ms = round((monotonic() - started) * 1000)
        if not log.enabled_for(logging.DEBUG):
            return
        sent = " ".join(part for part in (method, url) if part)
        if answer:
            outcome = f"HTTP {answer.status}"
        else:
            outcome = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
        log.debug(f"{service} {action}: {sent + ': ' if sent else ''}{outcome} in {duration_ms} ms, "
                  f"attempt {number} of {retries}",
                  event="http_call", service=service, method=method, url=url,
                  http_status=answer.status if answer else None, duration_ms=duration_ms, request=_body(request),
                  response=_body(answer.body) if answer else None, exc_type=type(error).__name__ if error else None)

    for number in range(1, retries + 1):
        started = monotonic()
        try:
            answer = await attempt()
        except UNREACHABLE as error:
            http_call(number, started, error=error)
            if number < retries:
                await asyncio.sleep(RETRY_WAIT)
                continue
            raise Fault.disruption(service=service, what=f"{service_name(service)} is not responding") from error
        except Exception as error:
            http_call(number, started, error=error)
            raise
        http_call(number, started, answer=answer)

        fault = _fault(service, action, answer)
        if fault is None:
            await faults.ok(service)
            if key := KEYS.get(service):
                await faults.fixed(service, "setting", key, msg=f"{service_name(service)} accepts {key} again")
            return answer.body
        if number == retries or fault.kind != FaultKind.DISRUPTION:
            raise fault
        await asyncio.sleep(RETRY_WAIT)


def _fault(service: str, action: str, answer: Answer) -> Fault | None:
    """ The Fault an answer is, None for a successful one """
    status, name = answer.status, service_name(service)
    reason = cut_reason(answer.reason) if answer.reason else None
    if 200 <= status < 300:
        return None
    if status >= 500:
        return Fault.disruption(service=service, what=f"{name} is not responding", reason=reason, http_status=status)
    if status in (401, 403):
        key = KEYS.get(service)
        return Fault.setup(service=service, what=f"{name} does not accept {key or 'its key'}", check="setting",
                           item=key, reason=reason, http_status=status)
    if 400 <= status < 500:
        return Fault.bug(service=service, what=f"{name} refused the {action}", reason=reason, http_status=status)
    return Fault.bug(service=service, what=f"{name} gave an unexpected answer to the {action}", reason=reason,
                     http_status=status)


def _body(value: Any) -> str | None:
    """ A request or response body for an http_call, cut at LOG_MAX_BODY characters (0 for no cut) """
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    try:
        max_length = int(os.getenv("LOG_MAX_BODY", "2000"))
    except ValueError:
        max_length = 2000
    if max_length <= 0 or len(text) <= max_length:
        return text
    return f"{text[:max_length]}... [truncated, {len(text)} chars total]"
