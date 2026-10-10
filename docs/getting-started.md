---
description: Install the FreeTheAI Python SDK, create a free API key, do the daily check-in, and send your first request.
---

# Getting started

## 1. Install

```bash
pip install freetheai
```

Python 3.9 or newer. The only dependency is `httpx`.

## 2. Get a key

1. Sign up at [freetheai.org](https://freetheai.org).
2. Open [API keys](https://freetheai.org/dashboard/api-keys) and create a key. It starts with `ftai_` and is shown once, so copy all of it.
3. Free models need the [daily check-in](https://freetheai.org/checkin), one quick captcha a day.

The free tier is 50 requests a day, reset at 00:00 UTC. The [plan page](https://freetheai.org/dashboard/plan) shows how to raise it.

Put the key in the environment:

=== "macOS / Linux"

    ```bash
    export FREETHEAI_API_KEY="ftai_..."
    ```

=== "Windows (PowerShell)"

    ```powershell
    $env:FREETHEAI_API_KEY = "ftai_..."
    ```

## 3. Pick a model

Model IDs look like `fta/<provider>/<model>`. Browse them on [freetheai.org/models](https://freetheai.org/models) or list them in code:

```python
from freetheai import FreeTheAI

client = FreeTheAI()
for model in client.models.list():
    print(model["id"])
```

## 4. Send a request

```python
reply = client.chat.completions.create(
    model="fta/zai/glm-5.3",
    messages=[
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": "What is an API gateway?"},
    ],
)
print(reply["choices"][0]["message"]["content"])
print(reply["usage"])
```

Replies use the OpenAI Chat Completions shape, returned as plain dictionaries.

## Already using the OpenAI SDK?

FreeTheAI speaks the OpenAI wire format, so the `openai` package works with a different base URL:

```python
from openai import OpenAI

client = OpenAI(base_url="https://api.freetheai.org/v1", api_key="ftai_...")
```

That gives you the plain client without the handling described on [Reliability](reliability.md).
