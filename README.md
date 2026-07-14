# urirun-connector-signal-gui — `signal-gui://`

Reply to Signal messages through the **GUI** (screen capture + vision-LLM + KVM input),
for when `signal-cli` is not linked on a node but the Signal desktop app is open and logged
in. It sees the conversation by capturing the screen, reads it with a vision model, and types
the reply through `kvm://` — no credentials, no API.

## Routes

| URI | What it does |
|-----|--------------|
| `signal-gui://host/command/reply-next-contextual` | Capture the Signal window, read the last incoming message with a vision-LLM, compose a contextual reply, and type it via `kvm://` (gated: confirm before send). |

## How it works

1. `_capture(node)` — screenshot the Signal desktop window via `kvm://…/screen/query/capture`.
2. `_llm_vision(image, prompt)` — a vision model reads the last message + conversation context.
3. `kvm` types the reply and (only on confirm) sends it.

This is the GUI fallback path; the credential path is `signal://` (signal-cli). Prefer
`signal://` when linked — use `signal-gui://` only when the CLI is unavailable.

## Grounding

Runs against the routes `route_health` marks healthy on the node (e.g. `task/command/run`
warm-uinput batch, `abs/command/click`), and verifies the typed text on screen before sending
(`ok:true` ≠ effect).

## Tests

```bash
python -m pytest tests/ -q
```
