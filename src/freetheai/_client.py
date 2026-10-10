"""The FreeTheAI clients (sync and async)."""

from __future__ import annotations

import asyncio
import builtins
import itertools
import os
import time
from collections.abc import AsyncIterator, Iterable, Iterator, Mapping, Sequence
from typing import Any, Callable

import httpx

from ._errors import (
    APIConnectionError,
    ConcurrencyLimitError,
    FreeTheAIError,
    ModelNotFoundError,
    StreamInterruptedError,
    TaskFailedError,
    error_for,
)
from ._resilience import (
    FALLBACK,
    RAISE,
    AsyncConcurrencyGate,
    ChatAssembler,
    ConcurrencyGate,
    clean_key,
    decide,
    fixable,
    interrupted,
    suggest_models,
)
from ._streaming import aiter_sse, iter_sse
from ._version import __version__

DEFAULT_BASE_URL = "https://api.freetheai.org/v1"
DEFAULT_TIMEOUT = httpx.Timeout(600.0, connect=15.0)
# Task states after which polling stops.
FINISHED = frozenset({"completed", "failed", "cancelled", "expired"})
MODEL_CACHE_SECONDS = 300.0

JSON = dict[str, Any]
Message = Mapping[str, Any]


def _body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _raise_for(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise error_for(response.status_code, _body(response), response.text[:300], response.headers)


def _clean(values: Mapping[str, Any]) -> JSON:
    return {key: value for key, value in values.items() if value is not None}


class _Base:
    def __init__(
        self,
        api_key: str | None,
        base_url: str | None,
        max_retries: int,
        fallback_models: Sequence[str] | None,
        stream_transport: bool,
        default_headers: Mapping[str, str] | None,
    ) -> None:
        api_key = api_key or os.environ.get("FREETHEAI_API_KEY")
        if not api_key:
            raise FreeTheAIError(
                "No API key. Pass api_key=... or set FREETHEAI_API_KEY "
                "(create a key at https://freetheai.org/dashboard/api-keys)."
            )
        self.api_key = clean_key(api_key)
        self.base_url = (base_url or os.environ.get("FREETHEAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.max_retries = max_retries
        self.fallback_models = list(fallback_models or [])
        self.stream_transport = stream_transport
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"freetheai-python/{__version__}",
            **(default_headers or {}),
        }
        self._model_ids: list[str] = []
        self._model_ids_at: float | None = None

    def _chain(self, model: str, fallback_models: Sequence[str] | None) -> list[str]:
        chain = [model]
        for extra in self.fallback_models if fallback_models is None else fallback_models:
            if extra not in chain:
                chain.append(extra)
        return chain


class FreeTheAI(_Base):
    """Client for the FreeTheAI API.

    ```python
    from freetheai import FreeTheAI

    client = FreeTheAI()  # reads FREETHEAI_API_KEY
    reply = client.chat.completions.create(
        model="fta/zai/glm-5.3",
        messages=[{"role": "user", "content": "Hello!"}],
    )
    print(reply["choices"][0]["message"]["content"])
    ```

    ``fallback_models`` are tried in order when a model is busy, filtered,
    over its provider budget, or down. ``max_concurrency`` caps replies in
    flight; without it the client learns the account's limit by itself.
    ``stream_transport`` (on by default) fetches non-streamed chats as a
    stream and assembles them, which keeps long replies from timing out.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float | httpx.Timeout | None = DEFAULT_TIMEOUT,
        max_retries: int = 3,
        fallback_models: Sequence[str] | None = None,
        max_concurrency: int | None = None,
        stream_transport: bool = True,
        default_headers: Mapping[str, str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(api_key, base_url, max_retries, fallback_models, stream_transport, default_headers)
        self._http = http_client or httpx.Client(timeout=timeout)
        self._gate = ConcurrencyGate(max_concurrency)
        self.chat = _Chat(self)
        self.models = _Models(self)
        self.videos = _Videos(self)
        self.images = _Images(self)
        self.tasks = _Tasks(self)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> FreeTheAI:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def search(self, query: str, *, num_results: int | None = None) -> JSON:
        """Searches the web; returns ``results`` with title, url, and text."""
        return self._request("POST", "/search", json=_clean({"query": query, "num_results": num_results}))

    def answer(self, query: str, *, num_results: int | None = None) -> JSON:
        """Answers a question from the web; returns ``answer`` and ``sources``."""
        return self._request("POST", "/answer", json=_clean({"query": query, "num_results": num_results}))

    # Transport ----------------------------------------------------------

    def _once(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._http.request(method, self.base_url + path, headers=self._headers, **kwargs)
        except httpx.TransportError as error:
            raise APIConnectionError(str(error)) from error
        _raise_for(response)
        return response

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self._policy([""], lambda _: self._once(method, path, **kwargs), gated=False)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._send(method, path, **kwargs).json()

    def _open_stream(self, body: JSON) -> httpx.Response:
        request = self._http.build_request(
            "POST", self.base_url + "/chat/completions", headers=self._headers, json=body
        )
        try:
            response = self._http.send(request, stream=True)
        except httpx.TransportError as error:
            raise APIConnectionError(str(error)) from error
        if response.status_code >= 400:
            response.read()
            response.close()
            _raise_for(response)
        return response

    def _policy(self, models: list[str], attempt_fn: Callable[[str], Any], *, gated: bool, hold: bool = False) -> Any:
        """Runs ``attempt_fn`` per model with the retry and fallback rules.

        With ``hold`` the concurrency slot stays taken after success; the
        caller releases it when its stream ends.
        """
        last: Exception | None = None
        index = 0
        while index < len(models):
            attempt = 0
            while True:
                if gated:
                    self._gate.acquire()
                action, delay = RAISE, 0.0
                try:
                    result = attempt_fn(models[index])
                    if gated and not hold:
                        self._gate.release()
                    return result
                except FreeTheAIError as error:
                    if gated:
                        if isinstance(error, ConcurrencyLimitError):
                            self._gate.refused()
                        self._gate.release()
                    if isinstance(error, ModelNotFoundError) and models[index]:
                        fixed = self._suggest(error, models[index])
                        if fixed and fixed not in models:
                            models[index] = fixed
                            continue
                    action, delay = decide(error, attempt, self.max_retries, index + 1 < len(models))
                    if action == RAISE:
                        raise
                    last = error
                if action == FALLBACK:
                    break
                attempt += 1
                time.sleep(delay)
            index += 1
        raise last or FreeTheAIError("no model answered")

    def _suggest(self, error: ModelNotFoundError, model: str) -> str | None:
        try:
            if self._model_ids_at is None or time.monotonic() - self._model_ids_at > MODEL_CACHE_SECONDS:
                self._model_ids = [m["id"] for m in self._once("GET", "/models").json()["data"]]
                self._model_ids_at = time.monotonic()
        except (FreeTheAIError, KeyError, ValueError):
            return None
        error.suggestions = suggest_models(model, self._model_ids)
        if error.suggestions:
            error.message += " Did you mean: " + ", ".join(error.suggestions) + "?"
        return fixable(model, error.suggestions)

    # Chat ---------------------------------------------------------------

    def _chat(self, models: list[str], body: JSON) -> JSON:
        def attempt(model: str) -> JSON:
            payload = {**body, "model": model}
            if not self.stream_transport:
                return self._once("POST", "/chat/completions", json=payload).json()
            response = self._open_stream({**payload, "stream": True})
            assembler = ChatAssembler()
            try:
                for event in iter_sse(response.iter_lines()):
                    assembler.feed(event)
            except httpx.TransportError as error:
                raise interrupted(assembler) from error
            finally:
                response.close()
            if not assembler.finished:
                raise interrupted(assembler)
            return assembler.result()

        return self._policy(models, attempt, gated=True)

    def _chat_stream(self, models: list[str], body: JSON) -> Iterator[JSON]:
        def attempt(model: str) -> Any:
            response = self._open_stream({**body, "model": model, "stream": True})
            events = iter_sse(response.iter_lines())
            first: list[JSON] = []
            try:
                for event in events:
                    first.append(event)
                    if event.get("choices"):
                        break
                else:
                    raise StreamInterruptedError("the reply stream ended before any reply")
            except BaseException:
                response.close()
                raise
            return response, events, first

        response, events, first = self._policy(models, attempt, gated=True, hold=True)
        return self._relay(response, events, first)

    def _relay(self, response: httpx.Response, events: Iterator[JSON], first: list[JSON]) -> Iterator[JSON]:
        assembler = ChatAssembler()
        try:
            for event in itertools.chain(first, events):
                assembler.feed(event)
                yield event
            if not assembler.finished:
                raise interrupted(assembler)
        except StreamInterruptedError as error:
            error.partial = assembler.text()
            raise
        except httpx.TransportError as error:
            raise interrupted(assembler) from error
        finally:
            response.close()
            self._gate.release()


class AsyncFreeTheAI(_Base):
    """Async client for the FreeTheAI API (same options and methods, awaited)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float | httpx.Timeout | None = DEFAULT_TIMEOUT,
        max_retries: int = 3,
        fallback_models: Sequence[str] | None = None,
        max_concurrency: int | None = None,
        stream_transport: bool = True,
        default_headers: Mapping[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key, base_url, max_retries, fallback_models, stream_transport, default_headers)
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._gate = AsyncConcurrencyGate(max_concurrency)
        self.chat = _AsyncChat(self)
        self.models = _AsyncModels(self)
        self.videos = _AsyncVideos(self)
        self.images = _AsyncImages(self)
        self.tasks = _AsyncTasks(self)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncFreeTheAI:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def search(self, query: str, *, num_results: int | None = None) -> JSON:
        return await self._request("POST", "/search", json=_clean({"query": query, "num_results": num_results}))

    async def answer(self, query: str, *, num_results: int | None = None) -> JSON:
        return await self._request("POST", "/answer", json=_clean({"query": query, "num_results": num_results}))

    async def _once(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._http.request(method, self.base_url + path, headers=self._headers, **kwargs)
        except httpx.TransportError as error:
            raise APIConnectionError(str(error)) from error
        _raise_for(response)
        return response

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return await self._policy([""], lambda _: self._once(method, path, **kwargs), gated=False)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        return (await self._send(method, path, **kwargs)).json()

    async def _open_stream(self, body: JSON) -> httpx.Response:
        request = self._http.build_request(
            "POST", self.base_url + "/chat/completions", headers=self._headers, json=body
        )
        try:
            response = await self._http.send(request, stream=True)
        except httpx.TransportError as error:
            raise APIConnectionError(str(error)) from error
        if response.status_code >= 400:
            await response.aread()
            await response.aclose()
            _raise_for(response)
        return response

    async def _policy(
        self, models: list[str], attempt_fn: Callable[[str], Any], *, gated: bool, hold: bool = False
    ) -> Any:
        last: Exception | None = None
        index = 0
        while index < len(models):
            attempt = 0
            while True:
                if gated:
                    await self._gate.acquire_async()
                action, delay = RAISE, 0.0
                try:
                    result = await attempt_fn(models[index])
                    if gated and not hold:
                        self._gate.release()
                    return result
                except FreeTheAIError as error:
                    if gated:
                        if isinstance(error, ConcurrencyLimitError):
                            self._gate.refused()
                        self._gate.release()
                    if isinstance(error, ModelNotFoundError) and models[index]:
                        fixed = await self._suggest(error, models[index])
                        if fixed and fixed not in models:
                            models[index] = fixed
                            continue
                    action, delay = decide(error, attempt, self.max_retries, index + 1 < len(models))
                    if action == RAISE:
                        raise
                    last = error
                if action == FALLBACK:
                    break
                attempt += 1
                await asyncio.sleep(delay)
            index += 1
        raise last or FreeTheAIError("no model answered")

    async def _suggest(self, error: ModelNotFoundError, model: str) -> str | None:
        try:
            if self._model_ids_at is None or time.monotonic() - self._model_ids_at > MODEL_CACHE_SECONDS:
                self._model_ids = [m["id"] for m in (await self._once("GET", "/models")).json()["data"]]
                self._model_ids_at = time.monotonic()
        except (FreeTheAIError, KeyError, ValueError):
            return None
        error.suggestions = suggest_models(model, self._model_ids)
        if error.suggestions:
            error.message += " Did you mean: " + ", ".join(error.suggestions) + "?"
        return fixable(model, error.suggestions)

    async def _chat(self, models: list[str], body: JSON) -> JSON:
        async def attempt(model: str) -> JSON:
            payload = {**body, "model": model}
            if not self.stream_transport:
                return (await self._once("POST", "/chat/completions", json=payload)).json()
            response = await self._open_stream({**payload, "stream": True})
            assembler = ChatAssembler()
            try:
                async for event in aiter_sse(response.aiter_lines()):
                    assembler.feed(event)
            except httpx.TransportError as error:
                raise interrupted(assembler) from error
            finally:
                await response.aclose()
            if not assembler.finished:
                raise interrupted(assembler)
            return assembler.result()

        return await self._policy(models, attempt, gated=True)

    async def _chat_stream(self, models: list[str], body: JSON) -> AsyncIterator[JSON]:
        async def attempt(model: str) -> Any:
            response = await self._open_stream({**body, "model": model, "stream": True})
            events = aiter_sse(response.aiter_lines()).__aiter__()
            first: list[JSON] = []
            try:
                async for event in events:
                    first.append(event)
                    if event.get("choices"):
                        break
                else:
                    raise StreamInterruptedError("the reply stream ended before any reply")
            except BaseException:
                await response.aclose()
                raise
            return response, events, first

        response, events, first = await self._policy(models, attempt, gated=True, hold=True)
        return self._relay(response, events, first)

    async def _relay(
        self, response: httpx.Response, events: AsyncIterator[JSON], first: list[JSON]
    ) -> AsyncIterator[JSON]:
        assembler = ChatAssembler()
        try:
            for event in first:
                assembler.feed(event)
                yield event
            async for event in events:
                assembler.feed(event)
                yield event
            if not assembler.finished:
                raise interrupted(assembler)
        except StreamInterruptedError as error:
            error.partial = assembler.text()
            raise
        except httpx.TransportError as error:
            raise interrupted(assembler) from error
        finally:
            await response.aclose()
            self._gate.release()


# Resources (sync) -------------------------------------------------------


class _Completions:
    def __init__(self, client: FreeTheAI) -> None:
        self._client = client

    def create(
        self,
        *,
        model: str,
        messages: Iterable[Message],
        stream: bool = False,
        fallback_models: Sequence[str] | None = None,
        **params: Any,
    ) -> Any:
        """Creates a chat completion (OpenAI Chat Completions shape).

        Extra keyword arguments (``temperature``, ``max_tokens``, ``tools``,
        ``reasoning_effort``, ``web_search_options``, ...) are sent as is.
        With ``stream=True`` this returns an iterator of chunks; the last
        chunk carries ``usage``. ``fallback_models`` overrides the client's
        list for this call; the reply's ``model`` says which one answered.
        """
        body = {"messages": list(messages), **_clean(params)}
        models = self._client._chain(model, fallback_models)
        if stream:
            return self._client._chat_stream(models, body)
        return self._client._chat(models, body)

    def stream_text(self, *, model: str, messages: Iterable[Message], **params: Any) -> Iterator[str]:
        """Streams only the reply text, piece by piece."""
        for chunk in self.create(model=model, messages=messages, stream=True, **params):
            for choice in chunk.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    yield text


class _Chat:
    def __init__(self, client: FreeTheAI) -> None:
        self.completions = _Completions(client)


class _Models:
    def __init__(self, client: FreeTheAI) -> None:
        self._client = client

    def list(self) -> builtins.list[JSON]:
        """Every model this key can use (``id`` is what you pass as ``model``)."""
        return self._client._request("GET", "/models")["data"]


class _Tasks:
    def __init__(self, client: FreeTheAI) -> None:
        self._client = client

    def list(self, *, limit: int | None = None) -> builtins.list[JSON]:
        return self._client._request("GET", "/tasks", params=_clean({"limit": limit}))["data"]

    def get(self, task_id: str) -> JSON:
        return self._client._request("GET", f"/tasks/{task_id}")

    def wait(self, task_id: str, *, poll_interval: float = 5.0, timeout: float = 1800.0) -> JSON:
        """Polls until the task finishes; raises on failure or timeout."""
        deadline = time.monotonic() + timeout
        while True:
            task = self.get(task_id)
            if task.get("status") in FINISHED:
                return _finished(task)
            if time.monotonic() > deadline:
                raise FreeTheAIError(f"task {task_id} did not finish in {timeout:.0f}s")
            time.sleep(poll_interval)

    def content(self, task_id: str, *, index: int = 0) -> bytes:
        """Downloads a finished task's output (image or video bytes)."""
        return self._client._send("GET", f"/tasks/{task_id}/content", params={"index": index}).content


class _Videos:
    def __init__(self, client: FreeTheAI) -> None:
        self._client = client

    def create(self, *, model: str, prompt: str | None = None, **params: Any) -> JSON:
        """Starts a video task. Poll it with ``client.tasks.wait(task["id"])``."""
        return self._client._request("POST", "/videos", json=_clean({"model": model, "prompt": prompt, **params}))


class _Images:
    def __init__(self, client: FreeTheAI) -> None:
        self._client = client

    def generate(self, *, model: str, prompt: str, **params: Any) -> JSON:
        """Starts an image task. Poll it with ``client.tasks.wait(task["id"])``."""
        return self._client._request(
            "POST", "/images/generations", json=_clean({"model": model, "prompt": prompt, **params})
        )


# Resources (async) ------------------------------------------------------


class _AsyncCompletions:
    def __init__(self, client: AsyncFreeTheAI) -> None:
        self._client = client

    async def create(
        self,
        *,
        model: str,
        messages: Iterable[Message],
        stream: bool = False,
        fallback_models: Sequence[str] | None = None,
        **params: Any,
    ) -> Any:
        body = {"messages": list(messages), **_clean(params)}
        models = self._client._chain(model, fallback_models)
        if stream:
            return await self._client._chat_stream(models, body)
        return await self._client._chat(models, body)

    async def stream_text(self, *, model: str, messages: Iterable[Message], **params: Any) -> AsyncIterator[str]:
        stream = await self.create(model=model, messages=messages, stream=True, **params)
        async for chunk in stream:
            for choice in chunk.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    yield text


class _AsyncChat:
    def __init__(self, client: AsyncFreeTheAI) -> None:
        self.completions = _AsyncCompletions(client)


class _AsyncModels:
    def __init__(self, client: AsyncFreeTheAI) -> None:
        self._client = client

    async def list(self) -> builtins.list[JSON]:
        return (await self._client._request("GET", "/models"))["data"]


class _AsyncTasks:
    def __init__(self, client: AsyncFreeTheAI) -> None:
        self._client = client

    async def list(self, *, limit: int | None = None) -> builtins.list[JSON]:
        return (await self._client._request("GET", "/tasks", params=_clean({"limit": limit})))["data"]

    async def get(self, task_id: str) -> JSON:
        return await self._client._request("GET", f"/tasks/{task_id}")

    async def wait(self, task_id: str, *, poll_interval: float = 5.0, timeout: float = 1800.0) -> JSON:
        deadline = time.monotonic() + timeout
        while True:
            task = await self.get(task_id)
            if task.get("status") in FINISHED:
                return _finished(task)
            if time.monotonic() > deadline:
                raise FreeTheAIError(f"task {task_id} did not finish in {timeout:.0f}s")
            await asyncio.sleep(poll_interval)

    async def content(self, task_id: str, *, index: int = 0) -> bytes:
        return (await self._client._send("GET", f"/tasks/{task_id}/content", params={"index": index})).content


class _AsyncVideos:
    def __init__(self, client: AsyncFreeTheAI) -> None:
        self._client = client

    async def create(self, *, model: str, prompt: str | None = None, **params: Any) -> JSON:
        return await self._client._request("POST", "/videos", json=_clean({"model": model, "prompt": prompt, **params}))


class _AsyncImages:
    def __init__(self, client: AsyncFreeTheAI) -> None:
        self._client = client

    async def generate(self, *, model: str, prompt: str, **params: Any) -> JSON:
        return await self._client._request(
            "POST", "/images/generations", json=_clean({"model": model, "prompt": prompt, **params})
        )


def _finished(task: JSON) -> JSON:
    if task.get("status") != "completed":
        error = task.get("error") or {}
        raise TaskFailedError(
            str(error.get("message") or f"task {task.get('status')}"),
            code=error.get("code"),
            error_id=error.get("error_id"),
            task=task,
        )
    return task
