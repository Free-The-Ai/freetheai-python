"""Built-in handling for the FreeTheAI API's known behaviours.

- Keys: stray spaces, quotes, and a pasted "Bearer " are removed; a key
  that is only part of a key fails at once instead of on every request.
- Concurrency: free accounts run one or two replies at a time. When the API
  says the account is at its limit, the client lowers its own limit to what
  the account allows and queues the rest instead of failing them.
- Busy models: retried after the server's Retry-After, or moved straight to
  the next model in ``fallback_models``.
- Long replies without streaming are fetched as a stream and assembled, so
  a slow reply never runs into an idle timeout on the way.
- Cut-off streams: a stream that ends without a finish reason is an error,
  never a silently short answer. When nothing was shown yet, it is retried.
- Unknown model IDs: the error lists close IDs from /v1/models, and an ID
  missing only its "fta/" prefix is fixed automatically.
"""

from __future__ import annotations

import asyncio
import difflib
import random
import re
import threading
import time
from collections.abc import Sequence
from typing import Any

from ._errors import (
    APIConnectionError,
    APIStatusError,
    ConcurrencyLimitError,
    ContentFilterError,
    FreeTheAIError,
    ImagesNotSupportedError,
    IncompleteKeyError,
    InternalServerError,
    ModelBusyError,
    ModelNotFoundError,
    ProviderBudgetError,
    RateLimitError,
    StreamInterruptedError,
)

KEY_PATTERN = re.compile(r"^ftai_[0-9a-fA-F]{48}$")
# How long a lowered concurrency limit holds before the client tries more again.
LIMIT_RELAX_SECONDS = 600.0
# Retry-After from a busy model is capped so a call never hangs for minutes.
MAX_BUSY_WAIT = 30.0
CONCURRENCY_RETRIES = 6


def clean_key(raw: str) -> str:
    """Removes copy-paste debris and refuses a key that is only part of one."""
    key = raw.strip().strip("\"'").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    if key.startswith("ftai_") and not KEY_PATTERN.match(key):
        raise IncompleteKeyError(
            "This is not a complete FreeTheAI API key. A key starts with ftai_ and is 53 characters long; "
            "it is shown only once, when you create it. Create a new key at "
            "https://freetheai.org/dashboard/api-keys.",
            status_code=401,
        )
    return key


# Retry and fallback rules ----------------------------------------------------

RETRY, FALLBACK, RAISE = "retry", "fallback", "raise"


def decide(error: Exception, attempt: int, max_retries: int, has_fallback: bool) -> tuple[str, float]:
    """What to do after ``error`` on the ``attempt``-th try of one model."""
    if isinstance(error, ConcurrencyLimitError):
        if attempt < max(max_retries, CONCURRENCY_RETRIES):
            return RETRY, backoff(attempt, base=1.0, cap=10.0)
        return RAISE, 0.0
    if isinstance(error, (ContentFilterError, ImagesNotSupportedError, ProviderBudgetError, ModelNotFoundError)):
        return (FALLBACK, 0.0) if has_fallback else (RAISE, 0.0)
    if isinstance(error, ModelBusyError):
        if has_fallback:
            return FALLBACK, 0.0
        if attempt < max_retries:
            wait = error.retry_after if error.retry_after is not None else backoff(attempt, base=5.0, cap=MAX_BUSY_WAIT)
            return RETRY, min(wait, MAX_BUSY_WAIT)
        return RAISE, 0.0
    retryable = (
        isinstance(error, (APIConnectionError, InternalServerError, StreamInterruptedError))
        or (isinstance(error, RateLimitError) and type(error) is RateLimitError)
        or (isinstance(error, APIStatusError) and error.status_code in (408, 409))
    )
    if retryable:
        if attempt < max_retries:
            delay = error.retry_after if isinstance(error, APIStatusError) else None
            return RETRY, min(delay, MAX_BUSY_WAIT) if delay is not None else backoff(attempt)
        return (FALLBACK, 0.0) if has_fallback else (RAISE, 0.0)
    return RAISE, 0.0


def backoff(attempt: int, *, base: float = 0.5, cap: float = 8.0) -> float:
    return min(base * 2**attempt, cap) + random.random() * 0.25


# Adaptive concurrency --------------------------------------------------------


class ConcurrencyGate:
    """Limits replies in flight to what the account allows.

    It starts open (or at ``fixed``). After a concurrency refusal it lowers
    the limit to the replies that were running alongside, and after
    LIMIT_RELAX_SECONDS without another refusal it opens again, so a plan
    upgrade is picked up without a restart.
    """

    def __init__(self, fixed: int | None = None) -> None:
        self.fixed = fixed
        self.learned: int | None = None
        self.lowered_at = 0.0
        self.in_flight = 0
        self._cond = threading.Condition()

    def limit(self) -> int | None:
        if self.learned is not None and time.monotonic() - self.lowered_at > LIMIT_RELAX_SECONDS:
            self.learned = None
        limits = [value for value in (self.fixed, self.learned) if value]
        return min(limits) if limits else None

    def acquire(self) -> None:
        with self._cond:
            while (limit := self.limit()) is not None and self.in_flight >= limit:
                self._cond.wait(timeout=1.0)
            self.in_flight += 1

    def release(self) -> None:
        with self._cond:
            self.in_flight = max(0, self.in_flight - 1)
            self._cond.notify_all()

    def refused(self) -> None:
        """Called (while still holding a slot) after a concurrency refusal."""
        with self._cond:
            self.learned = max(1, self.in_flight - 1)
            self.lowered_at = time.monotonic()


class AsyncConcurrencyGate(ConcurrencyGate):
    def __init__(self, fixed: int | None = None) -> None:
        super().__init__(fixed)
        self._event: asyncio.Event | None = None

    async def acquire_async(self) -> None:
        while (limit := self.limit()) is not None and self.in_flight >= limit:
            if self._event is None:
                self._event = asyncio.Event()
            self._event.clear()
            try:
                await asyncio.wait_for(self._event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
        self.in_flight += 1

    def release(self) -> None:
        self.in_flight = max(0, self.in_flight - 1)
        if self._event is not None:
            self._event.set()

    def refused(self) -> None:
        self.learned = max(1, self.in_flight - 1)
        self.lowered_at = time.monotonic()


# Streams ---------------------------------------------------------------------

_THINK = re.compile(r"^\s*<(think|thinking)>(.*?)</\1>\s*", re.S)


class ChatAssembler:
    """Builds one chat completion from streamed chunks."""

    def __init__(self) -> None:
        self.head: dict[str, Any] = {}
        self.choices: dict[int, dict[str, Any]] = {}
        self.usage: dict[str, Any] | None = None

    @property
    def finished(self) -> bool:
        return bool(self.choices) and all(c["finish_reason"] for c in self.choices.values())

    def text(self) -> str:
        return "".join("".join(c["content"]) for c in self.choices.values())

    def feed(self, chunk: dict[str, Any]) -> None:
        for key in ("id", "created", "model"):
            if chunk.get(key) and key not in self.head:
                self.head[key] = chunk[key]
        if chunk.get("usage"):
            self.usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            slot = self.choices.setdefault(
                choice.get("index", 0),
                {"role": "assistant", "content": [], "reasoning": [], "tools": {}, "finish_reason": None},
            )
            delta = choice.get("delta") or {}
            if delta.get("content"):
                slot["content"].append(delta["content"])
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(reasoning, str) and reasoning:
                slot["reasoning"].append(reasoning)
            for call in delta.get("tool_calls") or []:
                tool = slot["tools"].setdefault(
                    call.get("index", len(slot["tools"])),
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                tool["id"] = call.get("id") or tool["id"]
                function = call.get("function") or {}
                tool["function"]["name"] += function.get("name") or ""
                tool["function"]["arguments"] += function.get("arguments") or ""
            if choice.get("finish_reason"):
                slot["finish_reason"] = choice["finish_reason"]
            if choice.get("annotations") or delta.get("annotations"):
                slot.setdefault("annotations", []).extend(choice.get("annotations") or delta.get("annotations"))

    def result(self) -> dict[str, Any]:
        choices = []
        for index in sorted(self.choices):
            slot = self.choices[index]
            content = "".join(slot["content"])
            reasoning = "".join(slot["reasoning"])
            match = _THINK.match(content)
            if match:  # some models put their thinking at the start of the reply
                reasoning = reasoning or match.group(2).strip()
                content = content[match.end() :]
            message: dict[str, Any] = {"role": slot["role"], "content": content}
            if reasoning:
                message["reasoning_content"] = reasoning
            if slot["tools"]:
                message["tool_calls"] = [slot["tools"][k] for k in sorted(slot["tools"])]
            if slot.get("annotations"):
                message["annotations"] = slot["annotations"]
            choices.append({"index": index, "message": message, "finish_reason": slot["finish_reason"]})
        result: dict[str, Any] = {"object": "chat.completion", **self.head, "choices": choices}
        if self.usage:
            result["usage"] = self.usage
        return result


def interrupted(assembler: ChatAssembler, error_id: str | None = None) -> StreamInterruptedError:
    return StreamInterruptedError(
        "the reply stream stopped before the model finished", error_id=error_id, partial=assembler.text()
    )


# Model IDs -------------------------------------------------------------------


def suggest_models(model: str, ids: Sequence[str]) -> list[str]:
    """Close model IDs for an unknown one, best first."""
    if not ids:
        return []
    exact = [i for i in ids if i == f"fta/{model}" or i.endswith(f"/{model}")]
    if exact:
        return exact[:5]
    tails = {i.rsplit("/", 1)[-1]: i for i in ids}
    close = difflib.get_close_matches(model, ids, n=5, cutoff=0.6)
    for tail in difflib.get_close_matches(model.rsplit("/", 1)[-1], list(tails), n=5, cutoff=0.6):
        if tails[tail] not in close:
            close.append(tails[tail])
    return close[:5]


def fixable(model: str, suggestions: Sequence[str]) -> str | None:
    """The one ID the model clearly meant (only the "fta/" prefix missing)."""
    if model.startswith(("fta/", "freetheai/")):
        return None
    return f"fta/{model}" if f"fta/{model}" in suggestions else None


def unreachable() -> FreeTheAIError:
    return FreeTheAIError("no model answered")
