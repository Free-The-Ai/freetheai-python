---
description: Chat completions with the FreeTheAI Python SDK - messages, streaming, reasoning, parameters, and images.
---

# Chat and streaming

## A chat completion

```python
reply = client.chat.completions.create(
    model="fta/zai/glm-5.3",
    messages=[{"role": "user", "content": "Name three uses for a paperclip."}],
    temperature=0.7,
    max_tokens=400,
)
message = reply["choices"][0]["message"]
print(message["content"])
```

Any extra keyword argument is sent as is, so every Chat Completions parameter works: `temperature`, `top_p`, `max_tokens`, `stop`, `seed`, `tools`, `tool_choice`, `response_format`, `reasoning_effort`, `web_search_options`.

!!! tip "max_tokens=0"
    Sending `max_tokens=0` asks for the longest reply the model allows.

## Streaming text

```python
for text in client.chat.completions.stream_text(
    model="fta/kimi/k3",
    messages=[{"role": "user", "content": "Tell me a short story."}],
):
    print(text, end="", flush=True)
```

## Streaming chunks

`stream=True` returns an iterator of `chat.completion.chunk` dictionaries. The last chunk carries `usage`.

```python
for chunk in client.chat.completions.create(model="fta/kimi/k3", messages=messages, stream=True):
    for choice in chunk["choices"]:
        print(choice["delta"].get("content") or "", end="")
    if chunk.get("usage"):
        print("\n", chunk["usage"])
```

If the stream stops before the model finishes, the iterator raises [`StreamInterruptedError`](../errors.md) with the text received so far in `.partial`.

## Reasoning

Thinking models return their reasoning in `message["reasoning_content"]` (and `delta["reasoning_content"]` when streaming). Turn thinking off with `reasoning_effort="none"`:

```python
reply = client.chat.completions.create(model="fta/zai/glm-5.3", messages=messages, reasoning_effort="none")
```

Some models write their thinking at the start of the reply inside `<think>...</think>`; the client moves it to `reasoning_content` so `content` holds only the answer.

## Images in messages

Models that read images take OpenAI-style content parts:

```python
reply = client.chat.completions.create(
    model="fta/zai/glm-5.3-flash",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "What is in this picture?"},
            {"type": "image_url", "image_url": {"url": "https://example.com/cat.jpg"}},
        ],
    }],
)
```

A text-only model answers with [`ImagesNotSupportedError`](../errors.md); with fallback models set, the next model is tried.

## Which model answered

With [fallback models](../reliability.md#fallback-models), `reply["model"]` names the model that answered.
