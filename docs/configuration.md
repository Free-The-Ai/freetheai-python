---
description: Configuration options for the FreeTheAI Python SDK client.
---

# Configuration

```python
import httpx
from freetheai import FreeTheAI

client = FreeTheAI(
    api_key=None,           # default: FREETHEAI_API_KEY
    base_url=None,          # default: FREETHEAI_BASE_URL or https://api.freetheai.org/v1
    max_retries=3,          # retries per model for retryable errors
    fallback_models=None,   # models tried in order after the first one fails
    max_concurrency=None,   # fixed cap on replies in flight; learned when left out
    stream_transport=True,  # fetch non-streamed chats as a stream and assemble them
    timeout=httpx.Timeout(600, connect=15),
    default_headers=None,   # extra headers on every request
    http_client=None,       # your own httpx.Client (proxies, transports, ...)
)
```

| Environment variable | Used for |
| --- | --- |
| `FREETHEAI_API_KEY` | The API key when `api_key` isn't passed |
| `FREETHEAI_BASE_URL` | The API address when `base_url` isn't passed |

## Your own HTTP client

Pass an `httpx.Client` for proxies, custom TLS, or event hooks:

```python
client = FreeTheAI(http_client=httpx.Client(proxy="http://localhost:8080", timeout=120))
```

The client sets the `Authorization` and `User-Agent` headers itself.

## Closing

Use the client as a context manager, or call `close()`:

```python
with FreeTheAI() as client:
    ...
```
