# Handoff: jackpotTV infra (Sparky's lane)

Tars owns the app in this repo. Infra/deploy plumbing is Sparky's — this file is
the contract at the boundary so neither side blocks the other.

## What the app needs from the VM

- Ubuntu host, Nebula-joined (cert `jackpottv`, `10.100.0.5`)
- Python 3.11+, `python3 -m venv` available
- systemd service `jackpottv.service`:
  - `WorkingDirectory=/opt/jackpottv`
  - `ExecStart=/opt/jackpottv/.venv/bin/uvicorn jackpottv:app --host 127.0.0.1 --port 8020`
  - Environment (from `/etc/jackpottv/jackpottv.env`, root-only, mode 600 — never in git):
    `JACKPOT_DB`, `JACKPOT_HLS_DIR`, `JACKPOT_FEED`, `JACKPOT_ATRIUM_FRAME`,
    `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`, `FACEBOOK_REDIRECT_URI`,
    `JACKPOT_FACEBOOK_ADMIN_IDS`
- Reverse proxy on 443 for `jackpot.cool` → `127.0.0.1:8020`, with TLS
  - Facebook requires `FACEBOOK_REDIRECT_URI=https://jackpot.cool/auth/facebook/callback`
- The live-floor inputs are files synced in from the home lab (not served by the app):
  - `JACKPOT_ATRIUM_FRAME` — a PNG of the Atrium, refreshed every few seconds
  - `JACKPOT_FEED` — the ticker's `feed.json`
  - `JACKPOT_HLS_DIR` — HLS segments for the members-only channel
  How they arrive (rsync over Nebula, object sync, shared mount) is an infra call.
- The deploy user needs passwordless `sudo` for exactly one thing:
  `systemctl restart jackpottv.service` (the deploy workflow calls it).

## GitHub Actions

`.github/workflows/deploy.yml` runs tests on GitHub-hosted runners for every
push/PR. Deployment runs **only** on `master` pushes and only on a self-hosted
runner labelled `jackpot-tv` (expected: `.159`).

Repo/environment variables to set (no secrets in the workflow):
- `DEPLOY_TARGET` — e.g. `deploy@10.100.0.5`
- `APP_DIR` — optional, defaults to `/opt/jackpottv`

The runner must reach the VM over the Nebula overlay (`10.100.0.5`) with SSH key
auth. Facebook's App Secret is **not** a GitHub secret; it lives only in the VM's
env file.

## What Tars does not touch

VM provisioning, Nebula certs, DNS for `jackpot.cool`, proxy/TLS, runner
installation, cloud firewall. If the shape above needs to change, say so in this
file and Tars will adapt the app side.
