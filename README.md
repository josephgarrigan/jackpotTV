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

## The stage (what the camera sees)

`/stage` is the broadcast frame at 1280×720: the Atrium fills the top, and a
jackpotTV-branded ticker runs along the bottom — judge messages, now playing, who
is working on the floor, and stories moving, from the Atrium tape.

- `ticker.py` builds `/feed.json` every 5s from the tape (`:8095/tape`), the live
  snapshot, and a source file.
- You control the judge channel with one command, no restart:

```bash
tickerctl "Welcome to jackpotTV — everything you are about to see is live"
tickerctl --music "Miles Davis — So What"
tickerctl --clear
```

- The newest judge message also pins in the top-right corner so it does not
  scroll away mid-sentence.
- The stage frame is public to compose the broadcast; the *tuned channel* in the
  guide stays behind the member gate.

## Facebook Login (manual flow)

Implemented per Meta's manual-flow guide — no SDK:

1. `GET /auth/facebook/login` → Facebook Login dialog (`response_type=code`,
   scopes `public_profile,email`) with a single-use, cookie-bound `state`.
2. `GET /auth/facebook/callback` exchanges the code server-side, validates the
   token with `debug_token` against this app's ID, fetches `/me`, and maps the
   identity into jackpotTV's admission flow. The App Secret and the user's
   Facebook token never reach the browser and are not persisted.
3. `POST /auth/facebook/deauthorize` and `POST /auth/facebook/data-deletion`
   accept Meta's signed requests (HMAC-verified); deletion removes the member
   and returns a confirmation code checkable at `/privacy/data-deletion/{code}`.

Required environment (server-side only):

```
FACEBOOK_APP_ID=
FACEBOOK_APP_SECRET=
FACEBOOK_REDIRECT_URI=https://jackpot.cool/auth/facebook/callback
JACKPOT_FACEBOOK_ADMIN_IDS=<comma-separated Facebook IDs for operators>
```

Meta dashboard callbacks: deauthorize
`https://jackpot.cool/auth/facebook/deauthorize`, data deletion
`https://jackpot.cool/auth/facebook/data-deletion`, privacy
`https://jackpot.cool/privacy`.
