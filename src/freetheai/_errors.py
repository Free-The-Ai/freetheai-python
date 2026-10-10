"""Errors raised by the client, and how each API answer maps onto them.

The API's error bodies are stable, so the client recognises the common
cases (daily check-in, daily limit, a busy model, a content filter, ...)
and raises a specific class you can catch, with the error id to quote when
you ask for support.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping, Sequence
from typing import Any

CHECKIN_URL = "https://freetheai.org/checkin"
KEYS_URL = "https://freetheai.org/dashboard/api-keys"
PLAN_URL = "https://freetheai.org/dashboard/plan"


class FreeTheAIError(Exception):
    """Base class for every error this package raises."""


class APIConnectionError(FreeTheAIError):
    """The request never got an answer (network error or timeout)."""


class StreamInterruptedError(FreeTheAIError):
    """A streamed reply stopped before the model said it was finished.

    ``partial`` holds the text that arrived before the cut.
    """

    def __init__(self, message: str, *, error_id: str | None = None, partial: str = "") -> None:
        super().__init__(message if not error_id else f"{message} (error id {error_id})")
        self.error_id = error_id
        self.partial = partial


class TaskFailedError(FreeTheAIError):
    """An image or video task ended without output."""

    def __init__(self, message: str, *, code: str | None = None, error_id: str | None = None, task: Any = None) -> None:
        super().__init__(message if not error_id else f"{message} (error id {error_id})")
        self.code = code
        self.error_id = error_id
        self.task = task


class APIStatusError(FreeTheAIError):
    """The API answered with an error status."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str | None = None,
        error_id: str | None = None,
        body: Any = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.error_id = error_id
        self.body = body
        self.retry_after = retry_after

    def __str__(self) -> str:
        text = f"{self.status_code}: {self.message}"
        if self.error_id and self.error_id not in self.message:
            text += f" (error id {self.error_id})"
        return text


class BadRequestError(APIStatusError):
    """400: the request was invalid."""


class ContentFilterError(BadRequestError):
    """400: the model's content filter refused the request or its reply.
    Rephrasing or another model usually works."""


class ImagesNotSupportedError(BadRequestError):
    """400: the model reads text only; remove images or pick another model."""


class RequestTooLargeError(APIStatusError):
    """413: the request body is over the size limit (shorten the chat or drop images)."""


class AuthenticationError(APIStatusError):
    """401: the API key is missing, wrong, or revoked."""


class IncompleteKeyError(AuthenticationError):
    """The key is only part of a key (a copied prefix, or cut off).
    Keys are shown once; create a new one if you lost it."""


class PermissionDeniedError(APIStatusError):
    """403: this key may not do this."""


class CheckinRequiredError(PermissionDeniedError):
    """403: free models need the daily check-in on the website first."""

    checkin_url = CHECKIN_URL


class EmailNotVerifiedError(PermissionDeniedError):
    """403: confirm the account's email address before using the API."""


class NotFoundError(APIStatusError):
    """404: unknown task or route."""


class ModelNotFoundError(NotFoundError):
    """404: no model has this ID. ``suggestions`` lists close model IDs."""

    suggestions: Sequence[str] = ()


class RateLimitError(APIStatusError):
    """429: too many requests."""


class ConcurrencyLimitError(RateLimitError):
    """429: the account already has as many replies running as its plan allows."""


class DailyLimitError(RateLimitError):
    """429: today's free requests are used up; ``resets_at`` is 00:00 UTC."""

    plan_url = PLAN_URL

    @property
    def resets_at(self) -> _dt.datetime:
        now = _dt.datetime.now(_dt.timezone.utc)
        return (now + _dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


class ProviderBudgetError(RateLimitError):
    """429: today's token budget for this model's provider is used up.
    Models from other providers still work."""


class InternalServerError(APIStatusError):
    """5xx: the service or model is temporarily unavailable."""


class ModelBusyError(InternalServerError):
    """503: every route for this model is busy; retry later or use another model."""


def _seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def error_for(
    status_code: int,
    body: Any,
    fallback_text: str = "",
    headers: Mapping[str, str] | None = None,
) -> APIStatusError:
    """Builds the matching error from a status code and a decoded body."""
    headers = headers or {}
    message, code, error_id = "", None, None
    if isinstance(body, dict):
        detail = body.get("error", body)
        if isinstance(detail, dict):
            message = str(detail.get("message") or "")
            code = detail.get("code") or detail.get("type")
            error_id = detail.get("error_id")
        elif isinstance(detail, str):
            message = detail
    if not message:
        # Not our JSON: usually an edge page (Cloudflare 52x) during a restart.
        message = "request failed" if body is not None else (fallback_text.strip()[:200] or "request failed")
        if status_code >= 500 or "<html" in fallback_text.lower():
            message = "the service is temporarily unreachable"
    error_id = error_id or headers.get("x-error-id")
    text = message.lower()
    cls: type = APIStatusError
    if status_code == 400:
        if code == "content_filter" or text.startswith("content filtered"):
            cls = ContentFilterError
        elif "accepts text only" in text:
            cls = ImagesNotSupportedError
        else:
            cls = BadRequestError
    elif status_code == 401:
        cls = IncompleteKeyError if "not a complete freetheai api key" in text else AuthenticationError
    elif status_code == 403:
        if "daily check-in" in text:
            cls = CheckinRequiredError
        elif "confirm your email" in text:
            cls = EmailNotVerifiedError
        else:
            cls = PermissionDeniedError
    elif status_code == 404:
        cls = (
            ModelNotFoundError
            if code == "model_not_found" or "was not found" in text or "model not found" in text
            else NotFoundError
        )
    elif status_code == 413:
        cls = RequestTooLargeError
    elif status_code == 429:
        if "daily free request limit" in text:
            cls = DailyLimitError
        elif "token budget" in text:
            cls = ProviderBudgetError
        elif "concurrency limit" in text:
            cls = ConcurrencyLimitError
        else:
            cls = RateLimitError
    elif status_code >= 500:
        cls = ModelBusyError if "busy" in text or "at capacity" in text else InternalServerError
    return cls(
        message,
        status_code=status_code,
        code=code,
        error_id=error_id,
        body=body,
        retry_after=_seconds(headers.get("retry-after")),
    )
