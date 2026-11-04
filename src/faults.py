#!/usr/bin/python3

""" Fouten: a Fault is an exception with its kind. The meldfunctie follows in issue 06. """

from enum import StrEnum


class FaultKind(StrEnum):
    """ The kinds of Fout, written as in the field fault: Bug, Storing and Inrichtingsfout """
    BUG = "bug"
    DISRUPTION = "disruption"
    SETUP = "setup"


class Fault(Exception):
    """ A Fout. Made with Fault.bug, Fault.disruption or Fault.setup, each with only the fields of its kind,
    and raised with `from e` so the original exception and its traceback go along.

    - service: radarr, sonarr, plex, transmission, tmdb, telegram or fallback
    - what: what went wrong, for the head of the admin message ("Radarr refused the movie request")
    - reason: the reason of the service, or the exception
    - http_status: with an HTTP answer
    - check and item, only of an Inrichtingsfout: the check that failed (series_path, tmdb_lookup, setting,
      disk_space) and the tmdb/tvdb ID or the name of the setting. With service they are its key.
    - details: the fields the decision was made on
    - media: the media item, a Radarr or Sonarr item with title, year and tmdbId
    - user_text: a Dutch sentence for the Foutmelding
    """

    def __init__(self, kind: FaultKind, *, what: str, service: str | None = None, reason: str | None = None,
                 http_status: int | None = None, check: str | None = None, item: int | str | None = None,
                 details: dict | None = None, media: dict | None = None, user_text: str | None = None):
        if (kind == FaultKind.SETUP) != (check is not None) or (item is not None and kind != FaultKind.SETUP):
            raise TypeError("only an Inrichtingsfout has a check and an item, and it always has a check")
        if service is None and kind != FaultKind.BUG:
            raise TypeError(f"a Fault of kind {kind} is always of a service")
        super().__init__(what)
        self.kind = kind
        self.service = service
        self.what = what
        self.reason = reason
        self.http_status = http_status
        self.check = check
        self.item = item
        self.details = details
        self.media = media
        self.user_text = user_text

    def __str__(self) -> str:
        return f"{self.what}: {self.reason}" if self.reason else self.what

    @classmethod
    def bug(cls, *, what: str, service: str | None = None, reason: str | None = None, http_status: int | None = None,
            details: dict | None = None, media: dict | None = None, user_text: str | None = None) -> "Fault":
        """ The bot itself does something that is not right; a Bug in the bot's own code has no service """
        return cls(FaultKind.BUG, what=what, service=service, reason=reason, http_status=http_status,
                   details=details, media=media, user_text=user_text)

    @classmethod
    def disruption(cls, *, service: str, what: str, reason: str | None = None, http_status: int | None = None,
                   details: dict | None = None, media: dict | None = None, user_text: str | None = None) -> "Fault":
        """ A service the bot depends on does not respond, or answers with a server error """
        return cls(FaultKind.DISRUPTION, what=what, service=service, reason=reason, http_status=http_status,
                   details=details, media=media, user_text=user_text)

    @classmethod
    def setup(cls, *, service: str, what: str, check: str, item: int | str | None = None, reason: str | None = None,
              http_status: int | None = None, details: dict | None = None, media: dict | None = None,
              user_text: str | None = None) -> "Fault":
        """ Something in the setup of the server is not right, and only the Beheerder can set it right """
        return cls(FaultKind.SETUP, what=what, service=service, reason=reason, http_status=http_status,
                   check=check, item=item, details=details, media=media, user_text=user_text)
