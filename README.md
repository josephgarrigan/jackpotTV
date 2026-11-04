# Channel Surfing

A thin social TV guide. One screen: the guide, a player, and a form that puts
your own stream on the dial.

## Run

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install fastapi uvicorn python-multipart
uvicorn app:app --host 0.0.0.0 --port 8020
```

The guide seeds one channel, `atrium`, pointing at `ATRIUM_HLS`.

```bash
./cast.sh /var/lib/atrium-cast/hls/atrium     # the channel source
python3 -m http.server 8021 -d /var/lib/atrium-cast/hls   # HLS origin
```

Open <http://localhost:8020>, press play, channel up.

## What is real, and what is stubbed

| Piece | State |
|---|---|
| HLS pipeline (ffmpeg → segments → player) | real |
| Guide, registration, ownership | real |
| Channel source | a slate today; the Atrium capture swaps in behind the same encoder |
| Identity | a demo handle; Facebook OAuth is the last step, not the first |
| Signed `channel.registered` event | not wired yet — the visible thread behind the demo |

## The demo path

1. Open the guide; the Captain's channel is already on the dial.
2. Register a channel with any HLS URL; it appears immediately.
3. Switch to `atrium` and play it.

No platform credentials exist in this app. It owns its SQLite file and nothing else.
