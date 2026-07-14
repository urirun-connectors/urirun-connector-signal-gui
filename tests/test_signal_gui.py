from urirun_connector_signal_gui import core

def test_bindings():
    b = core.urirun_bindings()["bindings"]
    assert any("host/command/reply-next-contextual" in k for k in b)

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
