---
description: Tool and function calling with the FreeTheAI Python SDK.
---

# Tool calls

Tools use the OpenAI format.

```python
import json

tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]

messages = [{"role": "user", "content": "Is it raining in Paris?"}]
reply = client.chat.completions.create(model="fta/zai/glm-5.3", messages=messages, tools=tools)
message = reply["choices"][0]["message"]
messages.append(message)

for call in message.get("tool_calls", []):
    args = json.loads(call["function"]["arguments"])
    result = {"city": args["city"], "raining": False}  # call your real function here
    messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})

final = client.chat.completions.create(model="fta/zai/glm-5.3", messages=messages, tools=tools)
print(final["choices"][0]["message"]["content"])
```

When streaming, tool call pieces arrive in `delta["tool_calls"]`; non-streamed replies come back already assembled.

!!! note "Which models take tools"
    Most models do. If your key is set to *tool-capable models only* on the [API keys page](https://freetheai.org/dashboard/api-keys), `client.models.list()` lists only those.
