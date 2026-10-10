---
description: API reference for the FreeTheAI Python SDK.
---

# API reference

## Clients

::: freetheai.FreeTheAI
    options:
      members: [search, answer, close]

::: freetheai.AsyncFreeTheAI
    options:
      members: [search, answer, close]

## Resources

| Attribute | Methods |
| --- | --- |
| `client.chat.completions` | `create(model, messages, stream=False, fallback_models=None, **params)`, `stream_text(model, messages, **params)` |
| `client.models` | `list()` |
| `client.videos` | `create(model, prompt=None, **params)` |
| `client.images` | `generate(model, prompt, **params)` |
| `client.tasks` | `list(limit=None)`, `get(task_id)`, `wait(task_id, poll_interval=5, timeout=1800)`, `content(task_id, index=0)` |

The async client has the same resources with awaitable methods.

## Errors

::: freetheai._errors
    options:
      show_root_heading: false
      members_order: source
      filters: ["!^_", "!error_for"]
