---
description: Web search and sourced answers with the FreeTheAI Python SDK.
---

# Web search

Two endpoints, both counted against a daily web search allowance (each response shows `daily_used` and `daily_limit`).

## Search results

```python
results = client.search("python 3.14 release notes", num_results=5)
for hit in results["results"]:
    print(hit["title"])
    print(hit["url"])
    print(hit["text"][:200], "\n")
```

## Answers with sources

```python
answer = client.answer("What changed in Python 3.14?")
print(answer["answer"])
for source in answer["sources"]:
    print("-", source)
```

## Search inside a chat

Models with built-in search take `web_search_options={}`; their sources come back as `annotations` on the message:

```python
reply = client.chat.completions.create(
    model="fta/dog/gpt-5.4-mini",
    messages=[{"role": "user", "content": "What is the weather in Tokyo today?"}],
    web_search_options={},
)
print(reply["choices"][0]["message"].get("annotations"))
```

For any other model, call `client.search(...)` and pass the results to the model yourself.
