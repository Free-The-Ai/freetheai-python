"""Server-sent events parsing for streamed chat completions."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from ._errors import StreamInterruptedError


def _flush(buffer: list[str]) -> str | None:
    data = "\n".join(buffer)
    return data if data else None


def _line(line: str, buffer: list[str]) -> str | None:
    """Feeds one line; returns a complete event's data when one ends."""
    line = line.rstrip("\r")
    if line == "":
        data = _flush(buffer)
        buffer.clear()
        return data
    if line.startswith("data:"):
        buffer.append(line[5:].lstrip(" "))
    return None  # comments (keepalives), event names, and ids are ignored


def iter_sse(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Yields each JSON event of an SSE stream until ``[DONE]``."""
    buffer: list[str] = []
    for line in lines:
        data = _line(line, buffer)
        if data is None:
            continue
        if data.strip() == "[DONE]":
            return
        yield decode(data)
    data = _flush(buffer)
    if data and data.strip() != "[DONE]":
        yield decode(data)


async def aiter_sse(lines: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """Async version of :func:`iter_sse`."""
    buffer: list[str] = []
    async for line in lines:
        data = _line(line, buffer)
        if data is None:
            continue
        if data.strip() == "[DONE]":
            return
        yield decode(data)
    data = _flush(buffer)
    if data and data.strip() != "[DONE]":
        yield decode(data)


def decode(data: str) -> dict[str, Any]:
    try:
        event = json.loads(data)
    except ValueError as error:
        raise StreamInterruptedError("the reply stream sent a broken event") from error
    if isinstance(event, dict) and "error" in event and "choices" not in event:
        # A stream that breaks after it started ends with an error event.
        detail = event["error"] if isinstance(event["error"], dict) else {"message": str(event["error"])}
        raise StreamInterruptedError(
            str(detail.get("message") or "stream interrupted"), error_id=detail.get("error_id")
        )
    return event
