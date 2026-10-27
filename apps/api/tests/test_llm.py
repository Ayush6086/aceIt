import json

import httpx

from aceit import explain, llm
from aceit.gate.runner import LlmSolver


def mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def gemini_reply(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_gemini_request_has_the_key_in_a_header_never_in_the_url_and_reads_the_reply(tmp_path):
    seen = {}
    def handler(req):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("x-goog-api-key"), json.loads(req.content)
        return httpx.Response(200, json=gemini_reply("hello"))
    png = tmp_path / "q.png"; png.write_bytes(b"\x89PNG")
    g = llm.Llm("SECRET-KEY", "gemini-test", min_interval_s=0, client=mock(handler))
    assert g("Explain", [png], max_tokens=99, temperature=0.2) == "hello"
    assert "SECRET-KEY" not in seen["url"] and seen["key"] == "SECRET-KEY" and seen["url"].endswith("/models/gemini-test:generateContent")
    parts = seen["body"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/png" and parts[-1] == {"text": "Explain"}                # image first, then the instruction
    assert seen["body"]["generationConfig"] == {"maxOutputTokens": 99, "temperature": 0.2}
    assert g.MODEL == "gemini:gemini-test"


def test_rate_limits_are_waited_out_and_calls_are_spaced():
    sleeps, calls = [], {"n": 0}
    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "7"}) if calls["n"] <= 2 else httpx.Response(200, json=gemini_reply("ok"))
    g = llm.Llm("k", "m", min_interval_s=0, client=mock(handler), sleep=sleeps.append)
    assert g("x") == "ok" and calls["n"] == 3 and sleeps.count(7.0) == 2                                           # waited the server's Retry-After twice
    always = llm.Llm("k", "m", min_interval_s=0, client=mock(lambda r: httpx.Response(429)), sleep=lambda s: None)
    try:
        always("x"); assert False
    except httpx.HTTPStatusError as e:
        assert e.response.status_code == 429                                                                       # gives up after a few tries, loudly
    spaced = []
    s = llm.Llm("k", "m", min_interval_s=5, client=mock(lambda r: httpx.Response(200, json=gemini_reply("a"))), sleep=spaced.append)
    s("1"); s("2")
    assert spaced and spaced[-1] > 0                                                                                # the second call was held back


def test_only_gemini_is_supported_and_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False); monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False); monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ignored")                                                              # an Anthropic key is never used
    assert llm.from_env() is None
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert llm.from_env().model == "gemini-3.8-flash"
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom"); assert llm.from_env().model == "gemini-custom"


def test_explainer_and_solver_work_end_to_end_through_the_model_interface(tmp_path):
    prompts = []
    def handler(req):
        text = json.loads(req.content)["contents"][0]["parts"][-1]["text"]
        prompts.append(text)
        if "Explain, for a student" in text:
            return httpx.Response(200, json=gemini_reply("Follow each process; a cycle in the wait-for graph means deadlock is possible, so pick the cycle option.\nFINAL ANSWER: {\"choice\": \"B\"}"))
        return httpx.Response(200, json=gemini_reply("Working...\n{\"choice\": \"B\"}"))
    g = llm.Llm("k", "m", min_interval_s=0, client=mock(handler))
    q = dict(q_type="MCQ", marks=1, key_type="mcq", key={"choice": "B"}, display="text", stem="Which option?", options=[{"label": c, "text": f"opt {c}"} for c in "ABCD"])
    body, why = explain.accept(q, explain.LlmExplainer(g)(q, [], "B"))
    assert why == "ok" and "official answer is B" in prompts[0] and "opt C" in prompts[0]
    assert "$2^{10} = 1024$" in prompts[0] and "\\frac{a}{b}" in prompts[0] and "FINAL ANSWER:" in prompts[0]          # the LaTeX example survived the f-string
    assert LlmSolver(g)(q, []) == {"choice": "B"}


def test_an_openai_style_provider_can_stand_in_and_anthropic_is_refused(tmp_path, monkeypatch):
    seen = {}
    def handler(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers.get("authorization"), json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "FINAL ANSWER: B"}}]})
    png = tmp_path / "q.png"; png.write_bytes(b"\x89PNG")
    m = llm.OpenAICompat("SECRET", "some-model", "https://api.example.com/v1/", min_interval_s=0, client=mock(handler))
    assert m("Solve", [png], max_tokens=50, temperature=0) == "FINAL ANSWER: B"
    assert seen["url"] == "https://api.example.com/v1/chat/completions" and seen["auth"] == "Bearer SECRET" and "SECRET" not in seen["url"]
    parts = seen["body"]["messages"][0]["content"]
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,") and parts[-1] == {"type": "text", "text": "Solve"}
    assert seen["body"]["max_tokens"] == 50 and m.MODEL == "openai-compatible:some-model"
    try:
        llm.OpenAICompat("k", "m", "https://api.anthropic.com/v1"); assert False
    except ValueError:
        pass
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"); monkeypatch.setenv("LLM_API_KEY", "k")
    assert isinstance(llm.from_env(), llm.OpenAICompat)
