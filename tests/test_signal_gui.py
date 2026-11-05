from urirun_connector_signal_gui import core

def test_bindings():
    b = core.urirun_bindings()["bindings"]
    uri = "signal-gui://host/command/reply-next-contextual"
    assert uri in b
    assert b[uri]["meta"]["gated"] is True
    assert "signal-gui://host/host/command/reply-next-contextual" not in b

def test_envelope_never_raises(monkeypatch):
    monkeypatch.setattr(core, "_kvm", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(core, "_capture", lambda n: "")
    r = core.reply_next_contextual(node="laptop", dry_run=True)
    assert r["ok"] is False and "steps" in r  # brak zrzutu → koperta fail, nie wyjątek

def test_scale_and_dry_run(monkeypatch):
    monkeypatch.setattr(core, "_kvm", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(core, "_capture", lambda n: "ZZZ")
    monkeypatch.setattr(core, "_llm_vision", lambda b, p, context=None: {
        "current_chat": "Maciej", "next_contact": "Dariusz",
        "next_last_message": "aktualnie robię proste rzeczy", "click_xy": [110, 138],
        "reply": "spoko, trzymam kciuki"})
    r = core.reply_next_contextual(node="laptop", dry_run=True)
    assert r["ok"] and r["dry_run"] and r["contact"] == "Dariusz" and r["reply"]

def test_history_depth_reaches_scene_prompt(monkeypatch):
    monkeypatch.setattr(core, "_kvm", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(core, "_capture", lambda n: "ZZZ")
    seen_prompts = []
    def fake_llm_vision(b, p, context=None):
        seen_prompts.append(p)
        return {"next_contact": "Dariusz", "next_last_message": "hej", "click_xy": [1, 1], "reply": "hej!"}
    monkeypatch.setattr(core, "_llm_vision", fake_llm_vision)
    r = core.reply_next_contextual(node="laptop", dry_run=True, history_depth=8, ticket="IFURI-229")
    assert r["ok"]
    assert "8" in seen_prompts[0]  # history_depth wpisany do promptu, nie tylko domyślne 5


def test_llm_vision_with_oqllm_docker(monkeypatch):
    """Verify Signal GUI vision extraction through local OQLLM Docker instance."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11437/health", timeout=1.0) as resp:
            if resp.status != 200:
                return
    except Exception:
        return

    monkeypatch.setenv("SIGNAL_GUI_LLM_API_BASE", "http://127.0.0.1:11437/v1")
    monkeypatch.setenv("SIGNAL_GUI_VISION_MODEL", "oqlos/system-one-router")
    monkeypatch.setenv("SIGNAL_GUI_LLM_API_KEY", "oqllm_live_loopback_root")

    b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    prompt = "proc://dockuri/ops/container/list"
    res = core._llm_vision(b64, prompt)
    assert isinstance(res, dict)
    assert res.get("selected_uri") == "proc://dockuri/ops/container/list"


class _Resp:
    def __init__(self, content):
        msg = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": msg})()]

    def __getitem__(self, key):  # dict-style access used by some connectors
        return {"choices": [{"message": {"content": self.choices[0].message.content}}]}[key]


def _capture(monkeypatch):
    import litellm
    seen = {}
    def fake(**kw):
        seen.update(kw)
        return _Resp('{"ok": true}')
    monkeypatch.setattr(litellm, "completion", fake)
    for var in ("URIRUN_LLM_API_BASE", "URIRUN_LLM_API_KEY", "OQLLM_API_KEY", "OPENAI_API_BASE", "SIGNAL_GUI_LLM_API_BASE", "SIGNAL_GUI_LLM_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-must-not-leak")
    return seen


def test_default_call_does_not_forward_foreign_credentials(monkeypatch):
    seen = _capture(monkeypatch)
    core._llm_vision("ZZZ", "prompt")
    assert "api_key" not in seen and "api_base" not in seen
    assert seen["model"].startswith("openrouter/")


def test_explicit_gateway_gets_only_gateway_key(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setenv("SIGNAL_GUI_LLM_API_BASE", "http://127.0.0.1:11437/v1")
    monkeypatch.setenv("OQLLM_API_KEY", "oqllm-key")
    core._llm_vision("ZZZ", "prompt")
    assert seen["api_base"] == "http://127.0.0.1:11437/v1"
    assert seen["api_key"] == "oqllm-key"
