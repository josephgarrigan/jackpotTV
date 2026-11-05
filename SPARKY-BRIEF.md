# jackpotTV — comprehensive handoff for Sparky

**Audience:** Sparky. You cannot write the GitHub repo, so this file carries the
context that lives only there and in Tars's session. Read it top to bottom once;
after that, the "If you do one thing" section is the whole job.

**Repo of record for the app:** https://github.com/josephgarrigan/jackpotTV (`master`)
**Your working copy:** Forgejo `josephgarrigan/jackpotTV` (`master`, currently `2f90dd6`)
**Production target:** GCP VM, Nebula name `jackpottv`, overlay `10.100.0.5`, public `34.86.114.173`
**Domain:** `jackpot.cool` (+ `www`) — we own it
**One-line product:** the live Atrium floor as a members-only TV channel: *"the floor
is on TV, behind a door an agent helped build."*

---

## If you do one thing (the critical path, in order)

1. **Frame, then Facebook.** Without the Atrium frame, `/stage` is a ticker over a
   pending image — the video shows nothing. Without Facebook creds, login is the
   disclosed local-handle fallback. Both are below; the frame is first because it is
   the visual.
2. Everything else — runner, DNS polish, EPG niceties — is after those two.

---

## 1. What exists and where it was proven

| Piece | State | Evidence |
|---|---|---|
| Atrium cast on `.212` (Playwright → ffmpeg → HLS, 3 fps) | **running, systemd** | `atrium-cast.service`, `atrium-hls.service`; playlist at `.212:8021/atrium/index.m3u8` (LAN-firewalled) |
| Atrium data (tape + snapshot) on `.157` | **running** | `atrium-stream.service`, `:8095/health` `ok`, `/tape`, `/snapshot` |
| jackpotTV app, members-only gate, IPTV | **merged in Forgejo**, proven on `.212` LAN | gate tests + live LAN acceptance (guest 403 → admit 200 → revoke 403) |
| Stage (`/stage`) with judge ticker | **built, screenshot-verified on LAN** | full frame: Atrium top, ticker bottom, pinned judge card |
| Facebook manual-flow login | **code merged, tests pass (mocked Meta)** | never run against real Meta — needs the app setup in §6 |
| GitHub Actions CI | **live** | test job green on GitHub; deploy job queued (no runner yet) |
| GCP VM + Caddy + units | **your work, merged** (§3) | running per your merge note; Tars has not touched the VM |

**Boundary (Captain's ruling):** Tars stays in the GitHub/app lane. VM, Nebula
certs, DNS, proxy/TLS, runner install, cloud firewall are yours. This doc is the
contract at that boundary; if the shape must change, say so in `INFRA-HANDOFF.md`.

---

## 2. The architecture in one picture

```
HOME LAB                                                     GCP VM (10.100.0.5)
────────                                                     ──────────────────
.157 ERPNext/Atrium page ─┐
     └─ atrium-stream :8095 (tape/snapshot JSON) ──Nebula──► ticker.py ─► feed.json
.212 Playwright capture ─► ffmpeg ─► HLS :8021 ──Nebula──► hls_mirror.py ─► local HLS dir
.212 capture_atrium_frame.py ─► atrium-live.png ──(frame-sync)──► VM /var/lib/jackpottv/

jackpotTV (FastAPI, :8020, behind Caddy on jackpot.cool)
  guides, admission, per-request HLS gate, /stage, /iptv, Facebook login
```

The app never points a player at the cast origin. It serves the playlist and
segments itself and checks admission **on every request** — that is what makes
revocation stop a stream mid-play, and it is the sentence the demo rests on.

---

## 3. What you already shipped (so Tars doesn't re-explain it to you)

Your commits on Forgejo `master`, newest first:

- **`2f90dd6` caddy: pin Let's Encrypt** — Caddyfile pins the LE ACME directory
  (the image's ZeroSSL EAB account is a removed legacy user). `jackpot.cool` +
  `www` reverse-proxy to `127.0.0.1:8020`, HSTS, JSON access log.
- **`e524574` frame-sync + env seam** — `deploy/frame-sync.service` +
  `.timer` written for `.212` (it has the Playwright venv), `EnvironmentFile=-/etc/jackpottv/jackpottv.env`
  in the app unit, and your handoff note naming the frame gap (§5, item 1).
- **`173db4e` merge** — Tars's Facebook/stage-frame/deploy work merged with your
  GCP units, IPTV, and guide rail. You verified the merged tests pass.
- **`81d8885` IPTV + channel rail** — `/iptv/playlist.m3u` and `/iptv/epg.xml`
  behind the *same* member gate (a playlist without an admitted session is a 403,
  and the stream URLs inside it are gated per request too); the watch page gained
  a channel rail with ↑/↓ and number-key surfing; tests gained IPTV gate checks.
- **`aad4ead` guide rail + overlay addresses** — CHANNELS side rail on the guide
  (locked channels show 🔒), IPTV pointer shown to admitted members, and the
  ticker/stage default sources moved to overlay addresses (`10.100.0.8:8095`,
  `10.100.0.8:8090`) because LAN addresses are unreachable from GCP.
- **`e4f6dd6` GCP host units** — `deploy/{jackpottv,jackpottv-ticker,hls-mirror}.service`,
  `deploy/hls_mirror.py` (mirrors the 6-segment window over Nebula every 1s,
  prunes what the playlist stops naming), `deploy/install.sh` (2 GB swap, python,
  caddy, ufw: 22/80/443/4242-udp, system user `jackpottv`).

Thank you — in particular, HLS mirroring and the IPTV gate preserved the app's
one load-bearing property (per-request admission) instead of routing around it.

---

## 4. The app surface (current, Forgejo `master`)

| Route | Who | Notes |
|---|---|---|
| `GET /` | public | guide + CHANNELS rail; locked channels visible, never playable |
| `GET /login`, `POST /login` | public | local-handle fallback; files an admission request |
| `GET /auth/facebook/login` | public | Meta manual flow; 503 until configured (§6) |
| `GET /auth/facebook/callback` | public | code → token (server-side), `debug_token` checked vs our app ID, `/me`, single-use cookie-bound `state` |
| `POST /auth/facebook/deauthorize` | Meta | signed request, HMAC-verified; revokes member + sessions |
| `POST /auth/facebook/data-deletion` | Meta | signed; deletes member, returns `{url, confirmation_code}` |
| `GET /privacy/data-deletion/{code}` | public | deletion status |
| `POST /logout` | member | destroys the local session |
| `GET /admin`, `POST /admin/admit/{id}`, `POST /admin/revoke/{id}` | operator (`JACKPOT_ADMIN`, or Facebook IDs in `JACKPOT_FACEBOOK_ADMIN_IDS`) | the admission door |
| `GET /watch/{id}` | admitted | player + CHANNELS rail; ↑/↓/number keys surf |
| `GET /stream/{id}/index.m3u8`, `…/seg*.ts` | admitted | **the gate; checked every request**; traversal-safe names |
| `GET /iptv/playlist.m3u`, `GET /iptv/epg.xml` | admitted | same session gate; XMLTV is minimal (rolling 30-min programme) |
| `GET /stage`, `GET /atrium-framed.html`, `GET /atrium-live.png`, `GET /feed.json` | public (compose the broadcast) | see §5 |
| `GET /api/now/{id}` | public | `{live, playlist}` — the agent/tool surface |

State is one SQLite file (`JACKPOT_DB`): `members` (handle, status, is_admin,
facebook_id, display_name, email), `sessions`, `oauth_states`, `deletion_requests`,
`channels` (seeded with exactly one: `atrium`, kind `local`, ref `atrium`).

Identity stance, stated plainly: Facebook confirms *who*; jackpotTV decides
*admission*. A Facebook login creates a **pending** member unless the Facebook ID
is an operator. The App Secret and the user's Facebook token never reach the
browser and are not persisted (only `fb_token_expires_at`).

---

## 5. Open seams — the actual to-do list

### 1. The frame gap (yours, named in your own handoff note)
`/stage` on the VM composes `/atrium-framed.html`, which polls `/atrium-live.png`
(`JACKPOT_ATRIUM_FRAME`, default `/var/lib/jackpottv/atrium-live.png`). On the VM
nothing writes that PNG, so the stage is a ticker over a pending frame.
`deploy/frame-sync.service` is written for `.212` (Playwright venv at
`/opt/atrium-cast/venv`) but **not enabled anywhere**, and two things about it need
your call as written:
- It both has a `.timer` (5 s) *and* is a long-running `Restart=always` service.
  One of those shapes is right; not both. The script loops forever, so the service
  alone is the coherent shape — drop the timer or make the script one-shot.
- Its `STAGE_URL` default (`http://10.100.0.8:8090/jackpottv-stage-embed`) names a
  page Tars doesn't have. Tars's version captures the real Atrium page directly:
  `http://192.168.1.157:8090/assets/erpnext/atrium/index.html` (from `.212`; overlay
  `10.100.0.8:8090` also answers). Capture **that**, write to
  `/var/lib/jackpottv/atrium-live.png` **on the VM** (or sync the PNG over Nebula —
  your call, but the PNG must land where the VM's app reads it; today the unit
  writes it on `.212`, where nothing serves it to the VM).
Acceptance: `curl https://jackpot.cool/atrium-live.png` returns a PNG that changes
every few seconds, and `/stage` shows the floor.

### 2. Facebook go-live (Captain + you)
Captain creates the Meta app and does the dashboard (§6). You place on the VM,
root-only (`/etc/jackpottv/jackpottv.env`, mode 600 — the unit already reads it):
```
FACEBOOK_APP_ID=
FACEBOOK_APP_SECRET=
FACEBOOK_REDIRECT_URI=https://jackpot.cool/auth/facebook/callback
JACKPOT_FACEBOOK_ADMIN_IDS=<Captain's Facebook ID, comma-separated>
```
Then restart `jackpottv` and run one real login end to end. Until then
`/auth/facebook/login` correctly returns 503 and the handle login is the fallback —
say so in the submission text; do not hide it.

### 3. GitHub Actions deploy (your `.159` runner)
The workflow expects a self-hosted runner labelled **`jackpot-tv`** and repo vars
`DEPLOY_TARGET` (e.g. `deploy@10.100.0.5`) and optional `APP_DIR` (default
`/opt/jackpottv`). It rsyncs over the overlay and restarts via the one sudo
permission (`systemctl restart jackpottv.service`). The GitHub Actions run for
`64bfeb3` is sitting queued for that runner. Note: GitHub only has `master` up to
`64bfeb3`; your five newer commits live only on Forgejo — see §7.

### 4. HLS on the VM
`hls-mirror.service` mirrors `10.100.0.3:8021` into `/var/lib/atrium-cast/hls/atrium`
on the VM and `JACKPOT_HLS_DIR` points there. Confirm it's active and that
`/api/now/1` reports `"live": true` through Caddy.

### 5. Small app-side notes (Tars, on request — do not block on these)
- XMLTV is deliberately minimal; channels beyond `atrium` need a `channels` row
  (kind `local`, `ref` = directory name) to appear in guide/IPTV.
- The watch page loads `hls.js` from a CDN; if you want zero third-party calls at
  demo time, Tars can vendor it.

---

## 6. Meta dashboard checklist (for the Captain; you can't do this part)

Per Meta's manual-flow guide, app at https://developers.facebook.com/apps/:
- Add **Facebook Login**; scopes `public_profile` + `email` only
- **Valid OAuth Redirect URI:** `https://jackpot.cool/auth/facebook/callback`
- **App Domains:** `jackpot.cool`
- **Privacy Policy URL:** `https://jackpot.cool/privacy`
- **Data Deletion Callback:** `https://jackpot.cool/auth/facebook/data-deletion`
- **Deauthorize Callback:** `https://jackpot.cool/auth/facebook/deauthorize`
- Dev-mode testers under App Roles; switch to **Live** before strangers log in
- Secret goes to the VM env file (§5.2) — never in git, Matrix, or GitHub secrets

---

## 7. Repo divergence — read this before pushing anything

- GitHub `master` = `64bfeb3` (Tars). Forgejo `master` = `2f90dd6` (you, 5 commits
  ahead, including the merge commit that already contains `64bfeb3`).
- So Forgejo is strictly ahead. When the runner exists, the deploy source of truth
  must be decided once: either push Forgejo `master` up to GitHub (Tars can do
  this on request), or point your deploy at Forgejo. Do not let both deploy.
- Tars will not push to Forgejo or pull app changes back to GitHub without the
  Captain asking — that's the lane discipline, not territorialism.

## 8. How to verify anything on the VM (copy-paste)

```bash
systemctl is-active jackpottv jackpottv-ticker hls-mirror caddy nebula
curl -s https://jackpot.cool/api/now/1            # expect "live": true
curl -sI https://jackpot.cool/atrium-live.png     # 200, image/png, changes over time
curl -s https://jackpot.cool/iptv/playlist.m3u    # 403 without a member session
curl -s https://jackpot.cool/auth/facebook/login  # 303 to facebook.com once configured; 503 before
```

## 9. What the demo video needs (so infra choices serve it)

1. The floor visibly alive on `/stage`, ticker running, Captain's judge message
   scrolling (control it from `.212` with `tickerctl "…"` / `tickerctl --music "…"`)
2. A judge/stranger: Facebook login → pending → admitted at `/admin` → channel plays
3. Revoke during playback; the stream stops on the next segment
4. Optional flex: load `/iptv/playlist.m3u` in VLC/TiviMate with the member session

If only two of these survive the clock, keep 1 and 2.
