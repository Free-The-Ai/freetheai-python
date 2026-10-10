---
description: Image and video generation tasks with the FreeTheAI Python SDK.
---

# Images and video

Image and video models run as tasks: you create one, it runs in the background, and you poll it until it finishes. Media models appear in `client.models.list()` as they go live.

## Video

```python
task = client.videos.create(
    model=VIDEO_MODEL_ID,
    prompt="a paper boat drifting on a pond",
    input_reference="https://example.com/boat.jpg",  # or a data: URL
)
task = client.tasks.wait(task["id"])  # polls every 5 s; raises TaskFailedError on failure
with open("boat.mp4", "wb") as file:
    file.write(client.tasks.content(task["id"]))
```

## Images

```python
task = client.images.generate(model=IMAGE_MODEL_ID, prompt="a lighthouse at dusk, watercolor")
task = client.tasks.wait(task["id"])
for index, _ in enumerate(task.get("data", [])):
    with open(f"lighthouse-{index}.png", "wb") as file:
        file.write(client.tasks.content(task["id"], index=index))
```

## Listing tasks

```python
for task in client.tasks.list(limit=10):
    print(task["id"], task["status"], task["model"])
```

A task that fails gives its free request back. Outputs are kept for a limited time (`expires_at`).
