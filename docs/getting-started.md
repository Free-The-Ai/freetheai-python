---
description: Install the FreeTheAI Python SDK, create an API key, add funds, and send your first request.
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
3. Add funds to your wallet (from $5, crypto or card) and follow a provider at [freetheai.org/providers](https://freetheai.org/providers). Each request bills the tokens it used at the listed price.

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

A model ID is the model name, such as `glm-5.3`; `<provider>/<model>` picks one provider. Browse them on [freetheai.org/models](https://freetheai.org/models) or list them in code:

```python
from freetheai import FreeTheAI

client = FreeTheAI()
for model in client.models.list():
    print(model["id"])
```

## 4. Send a request

```python
reply = client.chat.completions.create(
    model="glm-5.3",
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
