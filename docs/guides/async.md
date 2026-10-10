---
description: Async usage of the FreeTheAI Python SDK with asyncio.
---

# Async

`AsyncFreeTheAI` has the same options and methods, awaited.

```python
import asyncio
from freetheai import AsyncFreeTheAI

async def main():
    async with AsyncFreeTheAI() as client:
        reply = await client.chat.completions.create(
            model="fta/zai/glm-5.3",
            messages=[{"role": "user", "content": "Hello!"}],
        )
        print(reply["choices"][0]["message"]["content"])

        async for text in client.chat.completions.stream_text(
            model="fta/zai/glm-5.3",
            messages=[{"role": "user", "content": "Count to five."}],
        ):
            print(text, end="")

asyncio.run(main())
```

## Many requests at once

Fire as many as you like with `asyncio.gather`. The client learns how many replies your account may run at once and queues the rest, so you don't get concurrency errors:

```python
questions = ["What is DNS?", "What is TLS?", "What is HTTP/3?"]
replies = await asyncio.gather(*(
    client.chat.completions.create(model="fta/zai/glm-5.3-flash", messages=[{"role": "user", "content": q}])
    for q in questions
))
```
