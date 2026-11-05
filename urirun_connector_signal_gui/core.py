# Author: Tom Sapletta · Part of the ifURI solution.
"""urirun-connector-signal-gui — AUTONOMICZNY operator Signala nad KVM (mózg nad rękami).

KVM daje prymitywy (capture/click/type/key) — to RĘCE. Ten connector dokłada MÓZG jako jeden
route `signal-gui://host/command/reply-next-contextual`, realizując pełną pętlę „jak człowiek":

  observe (capture) → parse scene (LLM-vision) → identify next chat → read context →
  compose contextual reply (LLM) → execute (KVM batch: focus+click+type+send) →
  verify sent (capture+LLM) → log/comment (ticket + narracja + czas reakcji).

Wykonanie deleguje do KVM (task/command/run = ciepłe uinput; abs/command/click = atomowy klik).
Percepcja i treść: LLM-vision (litellm). Nic nie rzuca — koperta zwraca ok/fail + narrację.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from typing import Any

import urirun

CONNECTOR_ID = "signal-gui"
conn = urirun.connector(CONNECTOR_ID, scheme="signal-gui")

_NODE_URL = os.environ.get("SIGNAL_GUI_NODE_URL", "http://192.168.188.201:8765")
_VISION_MODEL = os.environ.get("SIGNAL_GUI_VISION_MODEL", "openrouter/google/gemini-3.1-flash")
_CAP_W = 1100  # szerokość capture; ekran=1920 → skala do współrzędnych klika


def _ok(**kw: Any) -> dict[str, Any]:
    return urirun.ok(connector=CONNECTOR_ID, **kw)


def _fail(msg: str, action: str, **extra: Any) -> dict[str, Any]:
    return urirun.fail(msg, connector=CONNECTOR_ID, action=action, **extra)


def _kvm(uri: str, payload: dict | None = None, timeout: float = 60.0) -> dict:
    """RĘCE: wywołaj prymityw KVM na węźle (/run)."""
    body = json.dumps({"uri": uri, "payload": payload or {}}).encode()
    req = urllib.request.Request(_NODE_URL + "/run", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode())
        res = d.get("result") or d
        return res.get("value") if isinstance(res, dict) and "value" in res else res


def _capture(node: str) -> str:
    r = _kvm(f"kvm://{node}/screen/query/capture", {"base64": True, "max_width": _CAP_W})
    return r.get("pngBase64") or r.get("base64") or ""


def _llm_vision(b64: str, prompt: str, context: dict | None = None) -> dict:
    """MÓZG: LLM-vision analizuje zrzut. Zwraca sparsowany JSON (albo {} przy błędzie)."""
    import litellm
    if context and context.get("ticket"):
        prompt = f"[ticket:{context.get('ticket')}] {prompt}"

    model = os.environ.get("SIGNAL_GUI_VISION_MODEL") or _VISION_MODEL
    api_base = os.environ.get("SIGNAL_GUI_LLM_API_BASE") or os.environ.get("URIRUN_LLM_API_BASE") or os.environ.get("OPENAI_API_BASE")
    if api_base and not (model.startswith("openai/") or model.startswith("openrouter/")):
        model = f"openai/{model}"

    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": 0.3,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ],
    }
    if api_base:
        kwargs["api_base"] = api_base
    api_key = os.environ.get("SIGNAL_GUI_LLM_API_KEY") or os.environ.get("OQLLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key

    resp = litellm.completion(**kwargs)
    txt = resp.choices[0].message.content or ""
    if "```" in txt:
        txt = txt.split("```")[1].removeprefix("json").strip()
    try:
        return json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
    except Exception:  # noqa: BLE001
        return {"_raw": txt[:400]}


_SCENE_PROMPT = (
    "To zrzut Signal Desktop (obraz {w}px szerokości, ~{h}px wysokości) z OTWARTYM czatem. "
    "Przeczytaj OSTATNICH (do {history_depth}) wiadomości widocznych w otwartym czacie — "
    "zarówno przychodzące (po lewej, od rozmówcy) jak i nasze wcześniejsze (po prawej) — "
    "żeby zrozumieć KONTEKST całej rozmowy, nie tylko pojedynczej ostatniej wiadomości. "
    "Zwróć CZYSTY JSON: {{\"next_contact\": nazwa osoby z nagłówka otwartego czatu, "
    "\"next_last_message\": treść ostatniej przychodzącej wiadomości, "
    "\"conversation_context\": krótkie streszczenie ostatnich {history_depth} wiadomości (o czym jest rozmowa), "
    "\"click_xy\": [x,y] środek POLA WPISYWANIA 'Message' na dole w PIKSELACH tego obrazu, "
    "\"reply\": naturalna, krótka, KONTEKSTOWA odpowiedź po polsku do next_last_message, "
    "uwzględniająca conversation_context (pasująca tonem i tematem do całej rozmowy, bez formalności)}}."
)


@conn.handler("command/reply-next-contextual", isolated=True,
              meta={"label": "Autonomiczny operator Signala: obserwuj→zrozum(z historią)→odpisz kontekstowo→zweryfikuj→zaloguj",
                    "gated": True})
def reply_next_contextual(node: str = "laptop", dry_run: bool = True, project: str = "",
                          history_depth: int = 5, ticket: str = "") -> dict[str, Any]:
    """Pełna pętla operatora. dry_run=True → NIE wysyła (podgląd draftu). dry_run=False → wysyła.

    history_depth: ile ostatnich wiadomości widocznych w czacie model ma uwzględnić przy
    komponowaniu odpowiedzi (kontekst rozmowy), nie tylko pojedynczą ostatnią wiadomość.
    ticket: opcjonalny identyfikator ticketu — tagowany w promptach LLM (audyt/debug).
    """
    t0 = time.time()
    log: list[dict] = []
    context = {"ticket": ticket} if ticket else None

    def step(name, **kw):
        log.append({"t": round(time.time() - t0, 2), "step": name, **kw})

    try:
        # 1. OBSERVE — fokus Signal (batch = ciepłe uinput) + capture
        _kvm(f"kvm://{node}/task/command/run", {"steps": [
            {"op": "key", "keys": "escape", "after": 0.7},
            {"op": "click", "x": 3, "y": 3, "after": 1.1},
            {"op": "type", "text": "signal", "after": 1.2},
            {"op": "key", "keys": "return", "after": 2.3}]})
        b64 = _capture(node)
        step("observe", captured=bool(b64))
        if not b64:
            return _fail("brak zrzutu", "reply-next", steps=log)

        # 2+3+4. PARSE SCENE + READ (z historią rozmowy) + COMPOSE (jedno wywołanie LLM-vision)
        scene = _llm_vision(b64, _SCENE_PROMPT.format(
            w=_CAP_W, h=int(_CAP_W * 9 / 16), history_depth=history_depth), context=context)
        step("parse+compose", scene={k: scene.get(k) for k in
                                      ("current_chat", "next_contact", "next_last_message",
                                       "conversation_context", "reply")})
        contact = scene.get("next_contact")
        reply = (scene.get("reply") or "").strip()
        xy = scene.get("click_xy") or []
        if not (contact and reply and len(xy) == 2):
            return _fail("LLM nie zwrócił kompletnej sceny", "reply-next", scene=scene, steps=log)
        # skala piksele-obrazu → ekran 1920x1080
        sx, sy = int(xy[0] * 1920 / _CAP_W), int(xy[1] * 1080 / int(_CAP_W * 9 / 16))

        # 5. EXECUTE — otwórz czat (abs-click stabilny) → wpisz → wyślij (albo dry-run)
        if dry_run:
            step("dry-run", would_open=contact, at=[sx, sy], would_send=reply)
            return _ok(action="reply-next", sent=False, dry_run=True, contact=contact,
                       reply=reply, reaction_s=round(time.time() - t0, 2), steps=log)
        # otwórz czat (abs-click stabilny) i WPISZ — ale JESZCZE NIE wysyłaj
        _kvm(f"kvm://{node}/abs/command/click", {"x": sx, "y": sy, "button": "left"})
        time.sleep(1.0)
        _kvm(f"kvm://{node}/task/command/run", {"steps": [{"op": "type", "text": reply, "after": 0.6}]})
        step("type", drafted=reply)

        # 6a. VERIFY DRAFT PRZED submitem (wzorzec type-verified: ok≠efekt; stop jeśli tekst nie w polu)
        db64 = _capture(node)
        vdraft = _llm_vision(db64, (
            f"Zrzut Signala. Czy w polu wpisywania (na dole, 'Message') widnieje DOKŁADNIE tekst "
            f"'{reply}' GOTOWY do wysłania (jeszcze niewysłany)? JSON {{\"draft_present\": true/false, "
            f"\"open_chat\": nazwa otwartego czatu}}."), context=context)
        draft_ok = bool(vdraft.get("draft_present")) and (vdraft.get("open_chat") or contact) == contact
        step("verify-draft", present=draft_ok, open_chat=vdraft.get("open_chat"))
        if not draft_ok:
            return _fail("draft niezweryfikowany — STOP przed Enterem (nie wysyłam na ślepo)",
                         "reply-next", contact=contact, reply=reply, steps=log)

        # 6b. SUBMIT dopiero po potwierdzeniu draftu
        _kvm(f"kvm://{node}/task/command/run", {"steps": [{"op": "key", "keys": "return", "after": 1.3}]})
        step("submit", sent=reply)

        # 6c. VERIFY SENT — dowód że wiadomość poszła do właściwej osoby
        vb64 = _capture(node)
        verify = _llm_vision(vb64, (
            f"Zrzut Signala. Czy w otwartym czacie z '{contact}' widać WYSŁANĄ przez nas (po prawej) "
            f"wiadomość '{reply}', a pole wpisywania jest PUSTE? JSON {{\"sent\": true/false, "
            f"\"open_chat\": nazwa otwartego czatu}}."))
        ok_sent = bool(verify.get("sent")) and (verify.get("open_chat") or contact) == contact
        step("verify-sent", sent=ok_sent, open_chat=verify.get("open_chat"))

        # 7. LOG — refleksja/ticket
        _log_ticket(project, contact, reply, ok_sent, round(time.time() - t0, 2))
        return _ok(action="reply-next", sent=ok_sent, contact=contact, reply=reply,
                   reaction_s=round(time.time() - t0, 2), steps=log)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"{type(exc).__name__}: {exc}", "reply-next", reaction_s=round(time.time() - t0, 2), steps=log)


def _log_ticket(project: str, contact: str, reply: str, ok: bool, secs: float) -> None:
    import shutil
    import subprocess
    pf = shutil.which("planfile") or os.path.expanduser("~/github/if-uri/venv/bin/planfile")
    proj = project or os.path.expanduser("~/github/if-uri")
    note = (f"signal-gui reply-next: {'WYSŁANO' if ok else 'NIEPOTWIERDZONE'} do {contact} "
            f"treść '{reply}' | czas reakcji {secs}s (observe→parse→compose→execute→verify)")
    try:
        subprocess.run([pf, "ticket", "create", f"[SIGNAL-GUI] Autonomiczna odpowiedź: {contact}",
                        "-p", "normal", "--source", "signal-gui", "-l", "signal", "-l", "autonomy",
                        "-d", note], capture_output=True, timeout=15, cwd=proj)
    except Exception:  # noqa: BLE001
        pass


def urirun_bindings() -> dict[str, Any]:
    return conn.bindings()
