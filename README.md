# jackpotTV — agentic channel surfing

One real channel — **the Atrium, captured live into HLS** — behind a members-only door.

## The demo in one breath

Open jackpotTV. There is one channel: *atrium*, the live floor. You cannot watch it.
Sign in, file an access request, and wait. An operator admits you — and only then does
the same guide hand you a player, and only then do the playlist and segments answer.
Revoke the admission and the stream stops on the next segment. The door is not a page;
it is checked on every request the player makes.

## Run

```bash
cd /path/to/jackpotTV && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
JACKPOT_HLS_DIR=/var/lib/atrium-cast/hls uvicorn jackpottv:app --host 0.0.0.0 --port 8020
```

- The cast runs separately (Playwright → ffmpeg → HLS). See `cast.sh` and the
  `atrium-cast` / `atrium-hls` services on the streaming host.
- `JACKPOT_ADMIN` (default `captain`) is the operator handle: first sign-in as that
  name is admitted and can admit/revoke others at `/admin`.
- Identity in the demo is a handle, not OAuth. That is stated, not hidden: admission
  is the product surface here, not the login mechanism.

## Routes

| Route | Gate |
|---|---|
| `GET /` | public guide; channel shown, locked |
| `GET /login`, `POST /login` | files an access request on first sign-in |
| `GET /watch/{id}` | admitted members only |
| `GET /stream/{id}/index.m3u8`, `GET /stream/{id}/seg…ts` | admitted members only, checked every request |
| `GET /admin`, `POST /admin/admit/{id}`, `POST /admin/revoke/{id}` | operator only |
| `GET /api/now/{id}` | channel liveness for agents/tools |

## Why the stream is proxied

The app serves the playlist and the segments itself rather than pointing the player
at the cast origin. That makes admission load-bearing: a leaked playlist URL without
a member session gets `403`, revocation takes effect immediately, and the internal
cast origin can stay on the LAN. Segment names are constrained (no path traversal).

## What is real

| Piece | State |
|---|---|
| Atrium → Chromium → ffmpeg → HLS | real, running, 3 fps |
| Guide, admission, revocation | real |
| Per-request stream gate | real, tested (`tests: guest 403 → admit 200 → revoke 403`) |
| Identity | a demo handle; Facebook OAuth is a later step |
| Agent channel tools | `GET /api/now/{id}` today; Muse connector is the next layer |

## Verify

```bash
uv run --no-project --with fastapi --with httpx --with python-multipart python test_jackpottv.py
# jackpotTV gate tests: ALL PASS
```
