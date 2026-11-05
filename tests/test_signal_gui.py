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

