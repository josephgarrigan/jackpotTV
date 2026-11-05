#!/usr/bin/env python3
"""tickerctl — what the Captain types to change the bottom of the screen.

    tickerctl "Welcome to jackpotTV"          add a message to the judges
    tickerctl --music "Miles Davis — So What" set now playing
    tickerctl --clear                         clear judge messages
    tickerctl --show                          print the current source

Writes /var/lib/jackpottv/ticker-source.json, which ticker.py picks up within
seconds. This is the whole control surface: no restart, no redeploy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SOURCE = Path("/var/lib/jackpottv/ticker-source.json")


def load() -> dict:
    try:
        return json.loads(SOURCE.read_text())
    except Exception:
        return {}


def main() -> None:
    ap = argparse.ArgumentParser(prog="tickerctl")
    ap.add_argument("message", nargs="?", help="a message to the judges")
    ap.add_argument("--music", help="now playing (artist — title)")
    ap.add_argument("--clear", action="store_true", help="clear judge messages")
    ap.add_argument("--show", action="store_true", help="print the current source")
    a = ap.parse_args()

    src = load()
    if a.clear:
        src["judge"] = []
    if a.music is not None:
        src["music"] = a.music
    if a.message:
        judge = list(src.get("judge") or [])
        judge.append(a.message)
        src["judge"] = judge[-5:]
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE.write_text(json.dumps(src, indent=1))
    print(json.dumps(src, indent=1) if (a.show or not (a.message or a.music or a.clear)) else "ticker updated")


if __name__ == "__main__":
    main()
