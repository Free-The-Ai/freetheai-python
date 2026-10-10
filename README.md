# FreeTheAI Python SDK

[![PyPI](https://img.shields.io/pypi/v/freetheai?color=111111)](https://pypi.org/project/freetheai/)
[![Python](https://img.shields.io/pypi/pyversions/freetheai?color=111111)](https://pypi.org/project/freetheai/)
[![Tests](https://github.com/Free-The-Ai/freetheai-python/actions/workflows/test.yml/badge.svg)](https://github.com/Free-The-Ai/freetheai-python/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-111111)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white)](https://discord.gg/secrets)

The official Python client for **[FreeTheAI](https://freetheai.org)**, a free OpenAI-compatible AI API. One key gives you dozens of chat models, streaming, tool calls, web search with sourced answers, and image and video tasks.

The client is built around how the FreeTheAI API actually behaves: it handles busy models, the per-account concurrency limit, cut-off streams, and the daily check-in for you, so your code deals with answers instead of retries.

```bash
pip install freetheai
```

## Quickstart

1. Create an account at [freetheai.org](https://freetheai.org) and make a key under [API keys](https://freetheai.org/dashboard/api-keys).
2. Free models need the [daily check-in](https://freetheai.org/checkin) (one quick captcha a day). The free tier is 50 requests a day, reset at 00:00 UTC.
3. Pick a model ID from [the model list](https://freetheai.org/models) or `client.models.list()`.

```python
from freetheai import FreeTheAI

client = FreeTheAI()  # reads FREETHEAI_API_KEY

reply = client.chat.completions.create(
    model="fta/zai/glm-5.3",
    messages=[{"role": "user", "content": "Write a haiku about open models."}],
)
print(reply["choices"][0]["message"]["content"])
```

### Streaming

```python
for text in client.chat.completions.stream_text(
    model="fta/kimi/k3",
    messages=[{"role": "user", "content": "Explain SSE in two sentences."}],
):
    print(text, end="", flush=True)
```

Raw chunks (OpenAI `chat.completion.chunk` shape, usage in the last one): `client.chat.completions.create(..., stream=True)`.

### Fallback models

```python
client = FreeTheAI(fallback_models=["fta/zai/glm-5.3-flash", "fta/mmx/minimax-m3"])

reply = client.chat.completions.create(model="fta/kimi/k3", messages=messages)
print(reply["model"])  # the model that answered
```

When a model is busy, refused by its content filter, can't read images, is over its provider's daily budget, or is down, the next model is tried at once.

### Web search and answers

```python
results = client.search("latest python release", num_results=5)
for hit in results["results"]:
    print(hit["title"], hit["url"])

answer = client.answer("What changed in Python 3.14?")
print(answer["answer"])
for source in answer["sources"]:
    print("-", source)
```

Chat models with built-in search take `web_search_options={}` on `chat.completions.create`.

### Tool calls

```python
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
}]
reply = client.chat.completions.create(model="fta/zai/glm-5.3", messages=messages, tools=tools)
calls = reply["choices"][0]["message"].get("tool_calls", [])
```

### Images and video

Image and video models run as tasks: create one, then poll until it finishes. Media models appear in `client.models.list()` as they go live.

```python
task = client.videos.create(model=VIDEO_MODEL_ID, prompt="a paper boat on a pond", input_reference=image_url)
task = client.tasks.wait(task["id"])          # polls until it finishes
open("boat.mp4", "wb").write(client.tasks.content(task["id"]))
```

### Async

```python
from freetheai import AsyncFreeTheAI

async with AsyncFreeTheAI() as client:
    reply = await client.chat.completions.create(model="fta/zai/glm-5.3", messages=messages)
    async for text in client.chat.completions.stream_text(model="fta/zai/glm-5.3", messages=messages):
        print(text, end="")
```

## Built for the FreeTheAI API

These are the things that trip up generic OpenAI clients on FreeTheAI, and what this client does about them:

| What happens | What the client does |
| --- | --- |
| A model is busy (503 with `Retry-After`) | Moves to the next fallback model, or waits the server's `Retry-After` (at most 30 s) and retries |
| The account already has as many replies running as its plan allows (429) | Lowers its own limit to what the account allows and queues the rest, instead of failing them. The limit relaxes again after 10 minutes, so plan upgrades are picked up |
| A long reply without streaming idles past a proxy timeout | Non-streamed chats are fetched as a stream and assembled into one normal completion (`stream_transport=True`, the default) |
| A stream ends without a finish reason (a cut-off reply) | Raises `StreamInterruptedError` with the partial text, never returns a silently short answer. When nothing was shown yet, it retries |
| The model's content filter refuses a request | Raises `ContentFilterError`, or tries the next fallback model |
| A model ID is mistyped or missing its `fta/` prefix | Fixes a missing prefix automatically; otherwise `ModelNotFoundError.suggestions` lists close IDs |
| The daily check-in isn't done, or today's free requests are used | Raises `CheckinRequiredError` / `DailyLimitError` right away (no pointless retries); `resets_at` tells you when |
| A key is pasted with quotes, `Bearer `, or cut off | Cleans it; a key that is only part of a key fails before any request is sent |
| Edge errors during a deploy (HTML 502/530 pages) | Retried with backoff, reported as `InternalServerError` if they last |
| Some models put their thinking inside the reply as `<think>...</think>` | Moved to `message["reasoning_content"]` |

Every API error keeps its `error_id` (also sent as the `X-Error-ID` header). Quote it in [Discord](https://discord.gg/secrets) or a support ticket and we can find the exact failure.

## Errors

```python
from freetheai import CheckinRequiredError, DailyLimitError, FreeTheAIError

try:
    reply = client.chat.completions.create(model="fta/zai/glm-5.3", messages=messages)
except CheckinRequiredError as error:
    print("Do the daily check-in:", error.checkin_url)
except DailyLimitError as error:
    print("Free requests are used up until", error.resets_at)
except FreeTheAIError as error:
    print("Failed:", error)
```

| Class | When |
| --- | --- |
| `AuthenticationError`, `IncompleteKeyError` | 401: wrong, revoked, or partial key |
| `CheckinRequiredError`, `EmailNotVerifiedError`, `PermissionDeniedError` | 403 |
| `ModelNotFoundError`, `NotFoundError` | 404 |
| `BadRequestError`, `ContentFilterError`, `ImagesNotSupportedError` | 400 |
| `RequestTooLargeError` | 413: over 8 MiB |
| `RateLimitError`, `ConcurrencyLimitError`, `DailyLimitError`, `ProviderBudgetError` | 429 |
| `InternalServerError`, `ModelBusyError` | 5xx |
| `StreamInterruptedError` | a stream stopped early (`.partial` has the text so far) |
| `TaskFailedError` | an image or video task ended without output |
| `APIConnectionError` | no answer at all (network or timeout) |

## Options

```python
FreeTheAI(
    api_key=None,            # or FREETHEAI_API_KEY
    base_url=None,           # or FREETHEAI_BASE_URL; default https://api.freetheai.org/v1
    max_retries=3,
    fallback_models=None,    # tried in order, see above
    max_concurrency=None,    # fixed cap on replies in flight; learned when left out
    stream_transport=True,   # fetch non-streamed chats as a stream
    timeout=httpx.Timeout(600, connect=15),
)
```

## Using the OpenAI SDK instead

FreeTheAI speaks the OpenAI wire format, so the official `openai` package works too:

```python
from openai import OpenAI

client = OpenAI(base_url="https://api.freetheai.org/v1", api_key="ftai_...")
```

You get the plain client without the handling above.

## Links

- Website: [freetheai.org](https://freetheai.org)
- API docs: [freetheai.org/docs](https://freetheai.org/docs) and [OpenAPI](https://api.freetheai.org/openapi.json)
- Models: [freetheai.org/models](https://freetheai.org/models)
- Setup guides for apps (SillyTavern, JanitorAI, Claude Code, Cline, ...): [freetheai.org/setup](https://freetheai.org/setup)
- Status: [freetheai.org/status](https://freetheai.org/status)
- Other SDKs: [JavaScript / TypeScript](https://github.com/Free-The-Ai/freetheai-js), [Go](https://github.com/Free-The-Ai/freetheai-go)
- Examples: [freetheai-cookbook](https://github.com/Free-The-Ai/freetheai-cookbook)

## License

MIT. See [LICENSE](LICENSE).
