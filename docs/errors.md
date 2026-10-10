---
description: Every error class in the FreeTheAI Python SDK, when it is raised, and what to do about it.
---

# Errors

All errors inherit from `FreeTheAIError`. API errors (`APIStatusError` and its subclasses) carry `status_code`, `message`, `code`, `error_id`, and `body`.

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

| Error | Status | When | What to do |
| --- | --- | --- | --- |
| `IncompleteKeyError` | 401 | The key is only part of a key | Copy the whole key, or create a new one |
| `AuthenticationError` | 401 | The key is wrong or revoked | Check the key on the [API keys page](https://freetheai.org/dashboard/api-keys) |
| `CheckinRequiredError` | 403 | Free models need today's check-in | Visit `error.checkin_url` |
| `EmailNotVerifiedError` | 403 | The account's email isn't confirmed | Confirm it on the website |
| `PermissionDeniedError` | 403 | The key's scope or IP list doesn't allow this | Check the key's settings |
| `ModelNotFoundError` | 404 | No model has this ID | See `error.suggestions` |
| `NotFoundError` | 404 | Unknown task or route | |
| `BadRequestError` | 400 | The request is invalid | Read `error.message` |
| `ContentFilterError` | 400 | The model's content filter refused | Rephrase or use another model |
| `ImagesNotSupportedError` | 400 | The model reads text only | Remove images or pick another model |
| `RequestTooLargeError` | 413 | Over 8 MiB | Shorten the chat or drop images |
| `ConcurrencyLimitError` | 429 | Too many replies running (only after the client's own queueing gives up) | Wait for running replies |
| `DailyLimitError` | 429 | Today's free requests are used | Wait until `error.resets_at` |
| `ProviderBudgetError` | 429 | This provider's daily token budget is used | Use a model from another provider |
| `RateLimitError` | 429 | Too many requests | Slow down |
| `ModelBusyError` | 503 | Every route for the model is busy | Retry later or add fallback models |
| `InternalServerError` | 5xx | The service is temporarily unavailable | Retry later |
| `StreamInterruptedError` | | A stream stopped early | `error.partial` has the text so far |
| `TaskFailedError` | | An image or video task ended without output | Read `error.message` |
| `APIConnectionError` | | No answer (network or timeout) | Check your connection |

Include `error.error_id` when you ask for help.
