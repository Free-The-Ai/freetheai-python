import json

import httpx
import pytest

import freetheai._client as client_module
from freetheai import (
    AsyncFreeTheAI,
    AuthenticationError,
    CheckinRequiredError,
    ContentFilterError,
    DailyLimitError,
    FreeTheAI,
    FreeTheAIError,
    IncompleteKeyError,
    InternalServerError,
    ModelBusyError,
    ModelNotFoundError,
    RateLimitError,
    StreamInterruptedError,
    TaskFailedError,
    __version__,
)

KEY = "ftai_" + "ab12" * 12


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda s: None)


def make(handler, **kwargs):
    return FreeTheAI(api_key=KEY, http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def make_async(handler, **kwargs):
    return AsyncFreeTheAI(api_key=KEY, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kwargs)


def sse(*events, done=True):
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + ("data: [DONE]\n\n" if done else "")
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def chunk(text=None, finish=None, **delta):
    if text is not None:
        delta["content"] = text
    return {"id": "chatcmpl-1", "model": "m", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def reply(text="hi"):
    return sse(chunk(text), chunk(finish="stop"), {"choices": [], "usage": {"total_tokens": 3}})


def err(status, message, code=None, headers=None):
    body = {"error": {"message": message, "code": code, "error_id": "freetheai-abc"}}
    return httpx.Response(status, json=body, headers=headers or {})


def body_of(request):
    return json.loads(request.content)


# Basics ----------------------------------------------------------------------


def test_chat_is_fetched_as_a_stream_and_assembled():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers["authorization"], agent=request.headers["user-agent"])
        seen["body"] = body_of(request)
        return reply("Hello")

    result = make(handler).chat.completions.create(
        model="fta/zai/glm-5.3", messages=[{"role": "user", "content": "yo"}], temperature=0.5, top_p=None
    )
    assert result["choices"][0]["message"]["content"] == "Hello"
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["usage"] == {"total_tokens": 3}
    assert result["model"] == "m"
    assert seen["url"] == "https://api.freetheai.org/v1/chat/completions"
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["agent"] == f"freetheai-python/{__version__}"
    assert seen["body"] == {
        "model": "fta/zai/glm-5.3",
        "messages": [{"role": "user", "content": "yo"}],
        "temperature": 0.5,
        "stream": True,
    }


def test_plain_transport_when_turned_off():
    def handler(request):
        assert "stream" not in body_of(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "plain"}}]})

    result = make(handler, stream_transport=False).chat.completions.create(model="m", messages=[])
    assert result["choices"][0]["message"]["content"] == "plain"


def test_assembles_tool_calls_reasoning_and_think_tags():
    def handler(request):
        return sse(
            chunk(reasoning_content="plan "),
            chunk(tool_calls=[{"index": 0, "id": "call_1", "function": {"name": "get_", "arguments": '{"a"'}}]),
            chunk(tool_calls=[{"index": 0, "function": {"name": "weather", "arguments": ": 1}"}}]),
            chunk(finish="tool_calls"),
        )

    message = make(handler).chat.completions.create(model="m", messages=[])["choices"][0]["message"]
    assert message["reasoning_content"] == "plan "
    assert message["tool_calls"] == [
        {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"a": 1}'}}
    ]

    def thinker(request):
        return sse(chunk("<think>hmm</think>\nAnswer"), chunk(finish="stop"))

    message = make(thinker).chat.completions.create(model="m", messages=[])["choices"][0]["message"]
    assert message == {"role": "assistant", "content": "Answer", "reasoning_content": "hmm"}


def test_stream_text_skips_keepalives():
    def handler(request):
        return httpx.Response(200, content=b": keepalive\n\n" + reply("Hel").content.replace(b"Hel", b"Hello"))

    client = make(handler)
    assert "".join(client.chat.completions.stream_text(model="m", messages=[])) == "Hello"


# Known API answers -----------------------------------------------------------


def test_key_is_cleaned_and_partial_keys_fail_fast():
    assert FreeTheAI(api_key=f'  "Bearer {KEY}"\n').api_key == KEY
    with pytest.raises(IncompleteKeyError):
        FreeTheAI(api_key="ftai_23dc791...")
    with pytest.raises(IncompleteKeyError):
        FreeTheAI(api_key="ftai_23dc791…")


@pytest.mark.parametrize(
    "response,cls",
    [
        (
            err(
                403,
                "Daily check-in required for free models. Visit https://freetheai.org/checkin to solve the captcha.",
            ),
            CheckinRequiredError,
        ),
        (
            err(
                429,
                "Daily free request limit reached. It resets at 00:00 UTC; see https://freetheai.org/dashboard/plan.",
            ),
            DailyLimitError,
        ),
        (err(401, "unauthorized"), AuthenticationError),
    ],
)
def test_final_answers_are_not_retried(response, cls):
    calls = []

    def handler(request):
        calls.append(1)
        return response

    with pytest.raises(cls) as caught:
        make(handler).chat.completions.create(model="m", messages=[])
    assert len(calls) == 1
    assert caught.value.error_id == "freetheai-abc"
    if cls is DailyLimitError:
        assert caught.value.resets_at.hour == 0


def test_busy_model_moves_to_the_fallback_at_once():
    models = []

    def handler(request):
        models.append(body_of(request)["model"])
        if body_of(request)["model"] == "fta/kimi/k3":
            return err(
                503,
                "this model is busy right now; try again in a minute or pick another model.",
                headers={"retry-after": "30"},
            )
        return reply("from fallback")

    client = make(handler, fallback_models=["fta/zai/glm-5.3"])
    result = client.chat.completions.create(model="fta/kimi/k3", messages=[])
    assert models == ["fta/kimi/k3", "fta/zai/glm-5.3"]
    assert result["choices"][0]["message"]["content"] == "from fallback"


def test_busy_model_without_fallback_waits_retry_after(monkeypatch):
    waits = []
    monkeypatch.setattr(client_module.time, "sleep", waits.append)
    responses = iter([err(503, "this model is busy right now", headers={"retry-after": "30"}), reply()])
    make(lambda r: next(responses)).chat.completions.create(model="m", messages=[])
    assert waits == [30.0]


def test_busy_everywhere_raises_model_busy():
    def handler(request):
        return err(503, "this model is busy right now")

    with pytest.raises(ModelBusyError):
        make(handler, max_retries=1, fallback_models=["b"]).chat.completions.create(model="a", messages=[])


def test_content_filter_tries_the_next_model():
    def handler(request):
        if body_of(request)["model"] == "fta/dog/gpt-5":
            return err(400, "Content filtered: ...", code="content_filter")
        return reply()

    result = make(handler).chat.completions.create(
        model="fta/dog/gpt-5", messages=[], fallback_models=["fta/zai/glm-5.3"]
    )
    assert result["choices"][0]["message"]["content"] == "hi"
    with pytest.raises(ContentFilterError):
        make(handler).chat.completions.create(model="fta/dog/gpt-5", messages=[])


def test_concurrency_refusal_lowers_the_limit_and_retries():
    responses = iter(
        [err(429, "concurrency limit reached: your account already has as many requests running"), reply()]
    )
    client = make(lambda r: next(responses))
    assert client.chat.completions.create(model="m", messages=[])["choices"][0]["message"]["content"] == "hi"
    assert client._gate.learned == 1
    assert client._gate.in_flight == 0


def test_cut_off_stream_is_retried_when_nothing_was_shown():
    responses = iter([sse(chunk("half a sen"), done=False), reply("whole")])
    result = make(lambda r: next(responses)).chat.completions.create(model="m", messages=[])
    assert result["choices"][0]["message"]["content"] == "whole"


def test_cut_off_user_stream_raises_with_the_partial_text():
    def handler(request):
        return sse(chunk("half a "), chunk("sentence"))  # [DONE] but no finish reason

    client = make(handler)
    stream = client.chat.completions.create(model="m", messages=[], stream=True)
    with pytest.raises(StreamInterruptedError) as caught:
        list(stream)
    assert caught.value.partial == "half a sentence"
    assert client._gate.in_flight == 0


def test_error_event_mid_stream():
    def handler(request):
        return httpx.Response(
            200,
            content=b"data: "
            + json.dumps(chunk("so")).encode()
            + b'\n\ndata: {"error": {"message": "stream interrupted", "error_id": "freetheai-9"}}\n\n',
        )

    with pytest.raises(StreamInterruptedError) as caught:
        list(make(handler).chat.completions.create(model="m", messages=[], stream=True))
    assert caught.value.error_id == "freetheai-9"
    assert caught.value.partial == "so"


def test_model_id_missing_its_prefix_is_fixed():
    models = []

    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "fta/zai/glm-5.3"}, {"id": "fta/kimi/k3"}]})
        models.append(body_of(request)["model"])
        if body_of(request)["model"] == "zai/glm-5.3":
            return err(404, 'model "zai/glm-5.3" was not found.', code="model_not_found")
        return reply()

    make(handler).chat.completions.create(model="zai/glm-5.3", messages=[])
    assert models == ["zai/glm-5.3", "fta/zai/glm-5.3"]


def test_unknown_model_lists_suggestions():
    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "fta/zai/glm-5.3"}, {"id": "fta/zai/glm-5.3-flash"}]})
        return err(404, 'model "fta/zai/glm-5.4" was not found.', code="model_not_found")

    with pytest.raises(ModelNotFoundError) as caught:
        make(handler).chat.completions.create(model="fta/zai/glm-5.4", messages=[])
    assert "fta/zai/glm-5.3" in caught.value.suggestions
    assert "Did you mean" in str(caught.value)


def test_edge_html_errors_are_retried():
    responses = iter([httpx.Response(502, text="<html>Bad gateway</html>"), httpx.Response(200, json={"data": []})])
    assert make(lambda r: next(responses)).models.list() == []

    with pytest.raises(InternalServerError) as caught:
        make(lambda r: httpx.Response(530, text="<html>origin down</html>"), max_retries=0).models.list()
    assert "temporarily unreachable" in str(caught.value)


def test_rate_limit_retries_then_gives_up():
    calls = []

    def handler(request):
        calls.append(1)
        return err(429, "rate limit reached", headers={"retry-after": "0"})

    with pytest.raises(RateLimitError):
        make(handler, max_retries=2).search("cats")
    assert len(calls) == 3


def test_error_id_from_header():
    def handler(request):
        return httpx.Response(
            502,
            json={"error": {"message": "upstream provider temporarily unavailable"}},
            headers={"x-error-id": "freetheai-h"},
        )

    with pytest.raises(InternalServerError) as caught:
        make(handler, max_retries=0).search("x")
    assert caught.value.error_id == "freetheai-h"


# Search, tasks, config -------------------------------------------------------


def test_search_and_answer_bodies():
    bodies = []

    def handler(request):
        bodies.append((request.url.path, body_of(request)))
        return httpx.Response(200, json={"results": [], "answer": "x"})

    client = make(handler)
    client.search("go", num_results=3)
    client.answer("why")
    assert bodies == [("/v1/search", {"query": "go", "num_results": 3}), ("/v1/answer", {"query": "why"})]


def test_task_wait_polls_until_done():
    states = iter(["queued", "in_progress", "completed"])

    def handler(request):
        if request.url.path.endswith("/content"):
            return httpx.Response(200, content=b"MP4")
        return httpx.Response(200, json={"id": "task_1", "status": next(states)})

    client = make(handler)
    assert client.tasks.wait("task_1")["status"] == "completed"
    assert client.tasks.content("task_1") == b"MP4"


def test_task_failure_raises():
    def handler(request):
        return httpx.Response(
            200, json={"id": "t", "status": "failed", "error": {"message": "refused", "error_id": "e1"}}
        )

    with pytest.raises(TaskFailedError) as caught:
        make(handler).tasks.wait("t")
    assert caught.value.error_id == "e1"


def test_missing_key(monkeypatch):
    monkeypatch.delenv("FREETHEAI_API_KEY", raising=False)
    with pytest.raises(FreeTheAIError):
        FreeTheAI()


def test_env_key_and_base_url(monkeypatch):
    monkeypatch.setenv("FREETHEAI_API_KEY", KEY)
    monkeypatch.setenv("FREETHEAI_BASE_URL", "http://localhost:9/v1/")
    client = FreeTheAI()
    assert client.api_key == KEY
    assert client.base_url == "http://localhost:9/v1"


# Async -------------------------------------------------------------------------


async def test_async_stream_fallback_and_request(monkeypatch):
    async def no_wait(seconds):
        return None

    monkeypatch.setattr(client_module.asyncio, "sleep", no_wait)

    def handler(request):
        if request.url.path == "/v1/answer":
            return httpx.Response(200, json={"answer": "ok"})
        if body_of(request)["model"] == "busy":
            return err(503, "this model is busy right now")
        return reply("ab")

    client = make_async(handler, fallback_models=["ok"])
    pieces = [p async for p in client.chat.completions.stream_text(model="busy", messages=[])]
    assert pieces == ["ab"]
    result = await client.chat.completions.create(model="busy", messages=[])
    assert result["choices"][0]["message"]["content"] == "ab"
    assert (await client.answer("q"))["answer"] == "ok"
    assert client._gate.in_flight == 0
    await client.close()
