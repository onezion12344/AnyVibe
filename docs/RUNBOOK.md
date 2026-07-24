# Runbook — coding-vibe

How to start/stop/reach the system. Secrets live in `.env` (gitignored) — locations only, never values here.

## Services (Mac, currently launched via nohup — NOT yet launchd)

```bash
cd ~/Projects/coding-vibe

# HTTP server (used by the Oracle reverse tunnel) — port 5091
nohup .venv/bin/python -m uvicorn web.server:app --host 0.0.0.0 --port 5091 \
  </dev/null >/tmp/cv-webui.log 2>&1 & disown

# HTTPS server (LAN + localhost, self-signed cert) — port 5443
nohup .venv/bin/python -m uvicorn web.server:app --host 0.0.0.0 --port 5443 \
  --ssl-keyfile .certs/mac.key --ssl-certfile .certs/mac.crt \
  </dev/null >/tmp/cv-webui-tls.log 2>&1 & disown
```
- `server.py` auto-loads `.env` from the project root, so no shell `source` needed.
- Stop precisely (never `killall`): `pkill -f "uvicorn web.server:app"`.
- The harness reaps `run_in_background` uvicorn; use `nohup … & disown`, not a tracked background task.

## Env vars (`.env`, gitignored)
| Var | Purpose |
|---|---|
| `STEPFUN_API_KEY` | StepFun (ASR/TTS/realtime) bearer |
| `CV_API_TOKEN` | API bearer for all endpoints (first-message on WS, `x-cv-token` header on REST) |
| `CV_CALL_BACKEND` | which backend the CS dispatches to (`mock`/`claude-code`/`openopc`) — real needs a token |
| `CV_DEMO_REPO` | working dir for the CEO backend (default `/tmp/cv-demo`) |
| `CV_ALLOWED_BACKENDS` | `/api/dispatch` allowlist (default `mock`) |
| `CV_ALLOWED_REPO_ROOTS` | allowed `repo_path` roots (default `/tmp/cv-demo:/tmp/cv-e2e:/tmp/cv-ooc`) |

## Reach it
| Where | URL |
|---|---|
| Mac local (easiest, mic works, no cert warning) | `http://localhost:5091/call?token=<CV_API_TOKEN>` |
| Same WiFi (phone) | `https://<mac-lan-ip>:5443/call?token=…` (accept self-signed) |
| Any network (phone) | `https://161.118.214.70:8443/call?token=…` (via Oracle) |

## Oracle reverse tunnel (for the public URL)
Cloudflare edge (7844) is blocked on this network — use the Oracle VM instead.
```bash
# Mac → Oracle: expose Mac:5091 as Oracle localhost:5091
ssh -fN -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -R 127.0.0.1:5091:localhost:5091 -i ~/.ssh/oci_sg_proxy ubuntu@161.118.214.70
```
- Oracle runs nginx: `0.0.0.0:8443` (TLS, self-signed `/etc/nginx/ssl/anyvibe.*`) → `127.0.0.1:5091`. Config: `/etc/nginx/sites-available/anyvibe`.
- Oracle SSH key: `~/.ssh/oci_sg_proxy`; VM `ubuntu@161.118.214.70` (SG, see `oracle-onezion` skill).

## Endpoints
- `GET /call` → call UI · `GET /` → index (tap-to-talk)
- `WS /api/call` → realtime voice bridge → StepFun · `WS /api/events` → signaling
- `POST /api/call/ring` → agent-calls-user · `POST /api/dispatch` · `GET /api/board` · `GET /api/task/{id}` · `POST /api/voice` · `GET /api/tts`
- `POST /api/devices/register|ring` (native push, scaffold)

## OpenOPC backend
- Root: `~/Projects/OpenOPC` (`OPC_ROOT`). Preset: `scripts/coding-vibe-preset.py`.
- Use a **fresh project** (e.g. `cvlive`) — `demo`/`dse-agent` tasks.db are corrupted.
- Adapter auto-runs the preset (staffs the `coding-vibe` org) then `uv run opc exec … --stream-json`.
