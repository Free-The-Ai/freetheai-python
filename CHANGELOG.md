# Changelog

## 0.2.0 (2026-11-23)

- New `freetheai` command. `freetheai init` sets up Claude Code or Codex CLI to use FreeTheAI: it checks your key with the API, backs up the tool's settings, and changes only FreeTheAI's own entries (`--remove` takes them out again). `freetheai whoami` shows the key's balance and spend.
- orjson is now a dependency (fast JSON for the settings files the command edits).

## 0.1.1 (2026-11-13)

- The package description and docs now describe FreeTheAI as the AI model marketplace it is (the free tier closed on 2026-11-10). No code changes.

## 0.1.0 (2026-10-10)

First release.

- Chat completions (plain and streamed), models, web search and answers, image and video tasks, sync and async clients.
- Built-in handling for the FreeTheAI API: fallback models, a learned concurrency limit, retries on busy models with `Retry-After`, non-streamed chats fetched as a stream, cut-off stream detection, model ID suggestions and prefix fixes, key cleanup, and a specific error class for each common API answer.
