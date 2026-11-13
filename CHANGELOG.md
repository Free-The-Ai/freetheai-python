# Changelog

## 0.1.1 (2026-11-13)

- The package description and docs now describe FreeTheAI as the AI model marketplace it is (the free tier closed on 2026-11-10). No code changes.

## 0.1.0 (2026-10-10)

First release.

- Chat completions (plain and streamed), models, web search and answers, image and video tasks, sync and async clients.
- Built-in handling for the FreeTheAI API: fallback models, a learned concurrency limit, retries on busy models with `Retry-After`, non-streamed chats fetched as a stream, cut-off stream detection, model ID suggestions and prefix fixes, key cleanup, and a specific error class for each common API answer.
