<p align="center">
  <a href="https://free-the-ai.github.io/freetheai-python/"><img src=".github/banner.jpg" alt="FreeTheAI Python SDK" width="100%"></a>
</p>

<p align="center">
  <a href="https://pypi.org/project/freetheai/"><img src="https://img.shields.io/pypi/v/freetheai?color=111111" alt="PyPI"></a>
  <a href="https://pypi.org/project/freetheai/"><img src="https://img.shields.io/pypi/pyversions/freetheai?color=111111" alt="Python versions"></a>
  <a href="https://github.com/Free-The-Ai/freetheai-python/actions/workflows/test.yml"><img src="https://github.com/Free-The-Ai/freetheai-python/actions/workflows/test.yml/badge.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-111111" alt="MIT license"></a>
  <a href="https://discord.gg/secrets"><img src="https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <b><a href="https://free-the-ai.github.io/freetheai-python/">Documentation</a></b> ·
  <a href="https://free-the-ai.github.io/freetheai-python/getting-started/">Getting started</a> ·
  <a href="https://freetheai.org/models">Models</a> ·
  <a href="https://freetheai.org">freetheai.org</a>
</p>

# FreeTheAI Python SDK

The official Python client for [FreeTheAI](https://freetheai.org), a free OpenAI-compatible AI API. One key gives you dozens of chat models, streaming, tool calls, web search with sourced answers, and image and video tasks.

```bash
pip install freetheai
```

## Quickstart

Create a key at [freetheai.org](https://freetheai.org/dashboard/api-keys), do the [daily check-in](https://freetheai.org/checkin) for free models, and set `FREETHEAI_API_KEY`.

```python
from freetheai import FreeTheAI

client = FreeTheAI()

reply = client.chat.completions.create(
    model="fta/zai/glm-5.3",
    messages=[{"role": "user", "content": "Write a haiku about open models."}],
)
print(reply["choices"][0]["message"]["content"])
```

Stream it:

```python
for text in client.chat.completions.stream_text(model="fta/kimi/k3", messages=messages):
    print(text, end="", flush=True)
```

Search the web:

```python
answer = client.answer("What changed in Python 3.14?")
print(answer["answer"], answer["sources"])
```

## Built for the FreeTheAI API

Generic OpenAI clients treat every error the same. This one knows how the FreeTheAI API answers:

- **Busy models** wait for the server's `Retry-After`, or move straight to your `fallback_models`.
- **Concurrency limits** are learned on the first refusal; extra calls queue instead of failing.
- **Long replies** are fetched as a stream and assembled, so they don't hit idle timeouts.
- **Cut-off streams** raise `StreamInterruptedError` with the partial text, never a silently short answer.
- **The daily check-in and daily limit** raise `CheckinRequiredError` and `DailyLimitError` at once, with the link or reset time.
- **Mistyped model IDs** come back with suggestions; a missing `fta/` prefix is fixed for you.

```python
client = FreeTheAI(fallback_models=["fta/zai/glm-5.3-flash", "fta/mmx/minimax-m3"])
```

Read [Reliability](https://free-the-ai.github.io/freetheai-python/reliability/) for the full list.

## Documentation

| Guide | |
| --- | --- |
| [Getting started](https://free-the-ai.github.io/freetheai-python/getting-started/) | Key, check-in, first request |
| [Chat and streaming](https://free-the-ai.github.io/freetheai-python/guides/chat/) | Parameters, streaming, reasoning, images |
| [Tool calls](https://free-the-ai.github.io/freetheai-python/guides/tools/) | Function calling step by step |
| [Web search](https://free-the-ai.github.io/freetheai-python/guides/web-search/) | Results and sourced answers |
| [Images and video](https://free-the-ai.github.io/freetheai-python/guides/media/) | Media tasks |
| [Async](https://free-the-ai.github.io/freetheai-python/guides/async/) | `AsyncFreeTheAI` |
| [Errors](https://free-the-ai.github.io/freetheai-python/errors/) | Every error class and what to do |
| [Configuration](https://free-the-ai.github.io/freetheai-python/configuration/) | All client options |

## More from FreeTheAI

- [JavaScript / TypeScript SDK](https://github.com/Free-The-Ai/freetheai-js) and [Go SDK](https://github.com/Free-The-Ai/freetheai-go)
- [Cookbook](https://github.com/Free-The-Ai/freetheai-cookbook): runnable examples
- [Setup guides](https://freetheai.org/setup) for SillyTavern, JanitorAI, Claude Code, Cline, and more
- [API status](https://freetheai.org/status) and [Discord](https://discord.gg/secrets)

## License

MIT
