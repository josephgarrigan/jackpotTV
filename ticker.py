#!/usr/bin/env python3
"""ticker.py — the bottom-of-frame feed for jackpotTV.

One JSON document, /feed.json, that the stage page polls. Its sources:

  * the Atrium tape  (agents moving, stories closing)  — via /tape on :8095
  * the judge channel (the Captain's messages)          — local file, updated live
  * now playing                                         — a line in the same file

The Captain updates the judge channel from this host's Matrix room by writing the
file (see `tickerctl`), or anything else can write it — it is just JSON on disk.
Format: {"judge": ["msg 1", "msg 2"], "music": "artist — title"}

    ticker.py --out /var/lib/jackpottv/feed.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

TAPE = os.environ.get("ATRIUM_TAPE_URL", "http://192.168.1.157:8095/tape")
SNAPSHOT = os.environ.get("ATRIUM_SNAPSHOT_URL", "http://192.168.1.157:8095/snapshot")
SOURCE_FILE = Path(os.environ.get("TICKER_SOURCE", "/var/lib/jackpottv/ticker-source.json"))


def load_source() -> dict:
    try:
        return json.loads(SOURCE_FILE.read_text())
    except Exception:
        return {}


def kind_for(ev: dict) -> tuple[str, str] | None:
    """Tape event -> (css kind, sentence). Only things a judge can read at a glance."""
    k = ev.get("kind", "")
    if k == "story_moved":
        return "story", f"{ev.get('story')} moved {ev.get('from')} → {ev.get('to')}"
    if k == "story_entered":
        return "story", f"{ev.get('story')} entered the queue ({ev.get('state')})"
    if k == "story_left":
        return "story", f"{ev.get('story')} left the board"
    if k == "agent_joined":
        return "join", f"{ev.get('agent')} joined at {ev.get('station')}"
    if k == "agent_changed":
        to = ev.get("to") or {}
        return "agent", f"{ev.get('agent')} → {to.get('state')}" + (f" on {to.get('story')}" if to.get("story") else "")
    if k == "agent_left":
        return "agent", f"{ev.get('agent')} left the floor"
    if k == "health":
        return "sys", f"{ev.get('service')} {'recovered' if ev.get('ok') else 'is DOWN'}"
    return None


def working_line() -> str | None:
    """One summary sentence from the live snapshot: who is actually working."""
    try:
        with urllib.request.urlopen(SNAPSHOT, timeout=6) as r:
            snap = (json.load(r).get("snapshot") or {})
    except Exception:
        return None
    agents = snap.get("agents") or []
    busy = [a for a in agents if a.get("state") == "working"]
    bits = [f"{a.get('label') or a.get('id')} on {a.get('story')}" if a.get("story")
            else f"{a.get('label') or a.get('id')} working" for a in busy[:4]]
    if not bits:
        return "The floor is quiet — agents standing by"
    return "On the floor: " + " · ".join(bits)


def build(prev_seq: int) -> dict:
    src = load_source()
    items: list[dict] = []

    for msg in (src.get("judge") or [])[-3:]:
        if str(msg).strip():
            items.append({"kind": "judge", "text": str(msg).strip()})

    music = str(src.get("music") or "").strip()
    if music:
        items.append({"kind": "music", "text": f"♪ Now playing: {music}"})

    line = working_line()
    if line:
        items.append({"kind": "agent", "text": line})

    try:
        with urllib.request.urlopen(f"{TAPE}?since=0", timeout=6) as r:
            events = json.load(r).get("events") or []
    except Exception:
        events = []
    for ev in events[-14:]:
        made = kind_for(ev)
        if made:
            items.append({"kind": made[0], "text": made[1], "seq": ev.get("seq", 0)})

    if not items:
        items = [{"kind": "sys", "text": "jackpotTV — the floor is live"}]
    return {"seq": prev_seq + 1, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "items": items[:18]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/var/lib/jackpottv/feed.json")
    ap.add_argument("--period", type=float, default=5.0)
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    seq = 0
    print(f"ticker: writing {out} every {args.period}s (source: {SOURCE_FILE})", flush=True)
    while True:
        try:
            doc = build(seq)
            seq = doc["seq"]
            tmp = out.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc))
            tmp.replace(out)
        except Exception as exc:  # never stop the ticker for one bad poll
            print(f"ticker: {exc!r}", flush=True)
        time.sleep(args.period)


if __name__ == "__main__":
    main()
