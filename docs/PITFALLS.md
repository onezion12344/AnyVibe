# Pitfalls — coding-vibe (earned facts)

Each entry: symptom → root cause → fix → how verified. These are the expensive-to-rediscover bugs from the build.

## 2026-07-24: call.css/js 404 — page renders as stacked plain text
- **Symptom:** `/call` shows every view state at once, no styling, plain serif text.
- **Root cause:** `call.html` linked assets relatively (`href="call.css"`). Page is served at `/call` (not `/static/`), so the browser resolved them to `/call.css` → 404. No CSS (nothing hidden) + no JS (no state machine).
- **Fix:** absolute paths — `/static/call.css`, `/static/call.js`.
- **Verify:** `curl /static/call.css` = 200; served HTML shows `/static/` hrefs. Hard-refresh (Cmd+Shift+R) to bypass cached broken page.

## 2026-07-24: websockets 16.x — `extra_headers` rejected
- **Symptom:** StepFun realtime connection fails in `call_bridge.py`.
- **Root cause:** `websockets` ≥14 renamed `extra_headers` → `additional_headers`.
- **Fix:** try `additional_headers`, fall back to `extra_headers`.
- **Verify:** probe connected, `session.created` received.

## 2026-07-24: OpenOPC `opc exec` false success + corrupted DBs
- **Symptom:** openopc adapter returned `ok=True` but did nothing (no file, no events).
- **Root cause 1 (adapter):** `_run` drained stderr into the void and never checked `proc.returncode`; `result()` returned ok when no error events → a fast crash read as success.
- **Root cause 2 (data):** `.opc/projects/demo/tasks.db` (227MB) and `.opc/projects/dse-agent/tasks.db` (54MB) are **malformed** (`PRAGMA integrity_check` fails). `opc exec` crashes at engine-init DB migration: `DatabaseError: database disk image is malformed`.
- **Fix:** (a) adapter now captures stderr tail + fails on non-zero exit; (b) sidestep corruption by using a **fresh project** (`cvlive`) with its own clean `tasks.db` — never touch the user's corrupted DBs.
- **Verify:** cvlive run created `/tmp/cv-ooc/ooc_hello.txt` = `HELLO_FROM_OPENOPC`.
- **OPEN:** `dse-agent/tasks.db` is the user's real project history, corrupted — awaiting owner decision on `sqlite3 .recover` (non-destructive).

## 2026-07-24: OpenOPC staffing preset crashes for a fresh project
- **Symptom:** `coding-vibe-preset.py --project <new>` → `sqlite3.OperationalError: no such table: sessions`.
- **Root cause:** preset raw-inserts into `sessions`/`tasks` before the project DB schema exists. Worked for `demo` only because a prior engine run had created the schema.
- **Fix (in OpenOPC repo):** call `OPCStore(db_path).initialize()` (creates schema via `_create_tables`/`_ensure_schema`) before the inserts.
- **Verify:** fresh `cvlive` preset succeeds, `sessions` table populated, integrity ok.

## 2026-07-24: mic blocked — getUserMedia needs a secure context
- **Symptom:** phone/LAN over plain HTTP → no microphone.
- **Root cause:** `getUserMedia` requires HTTPS **or** `localhost`.
- **Fix:** serve HTTPS (self-signed on Mac :5443 / nginx on Oracle :8443), or test on `http://localhost` (localhost is a secure context — no cert needed).

## 2026-07-24: Cloudflare tunnel edge blocked on this network
- **Symptom:** all `*.onezion.top` return 530; `cloudflared` can't dial edge (QUIC UDP 7844 AND TCP 7844 refused).
- **Root cause:** network blocks Cloudflare edge port 7844 (both protocols). `--protocol http2` doesn't help.
- **Fix:** reverse SSH tunnel through the Oracle VM (`ssh -R`) + nginx TLS there; or test on LAN/localhost.

## 2026-07-24: subagents die with API 400 in a step-explore session
- **Symptom:** dispatched subagents fail `API Error: 400 invalid`.
- **Root cause:** they inherit the parent session's `step-explore` model.
- **Fix:** always pass `model="sonnet"` (or explicit) when dispatching agents/workflow agents.

## Standing: token in a WebSocket URL leaks into logs
- Browsers can't set WS headers. Putting `?token=` in the WS URL leaks it into nginx/access logs. **Fix:** first-message auth — client sends `{type:"auth",token}` as the first WS frame; server validates before processing. Page-load token is read once from `?token=`, stashed in sessionStorage, and stripped from the URL.
