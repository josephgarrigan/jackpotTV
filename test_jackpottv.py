import os
import sys

os.environ["JACKPOT_DB"] = "/tmp/jackpot-test.db"
os.environ["JACKPOT_ADMIN"] = "captain"
os.environ["JACKPOT_HLS_DIR"] = "/tmp/jackpot-hls"
sys.path.insert(0, "/tmp/demo")

from pathlib import Path
Path("/tmp/jackpot-hls/atrium").mkdir(parents=True, exist_ok=True)
Path("/tmp/jackpot-hls/atrium/index.m3u8").write_text("#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2.0,\nseg00001.ts\n")
Path("/tmp/jackpot-hls/atrium/seg00001.ts").write_bytes(b"TS")

from fastapi.testclient import TestClient
import jackpottv

c = TestClient(jackpottv.app)
c.__enter__()

r = c.get("/")
assert r.status_code == 200 and "admission required" in r.text, r.text[:200]

r = c.get("/watch/1")
assert r.status_code == 403, r.status_code

r = c.get("/stream/1/index.m3u8")
assert r.status_code == 403, r.status_code

r = c.post("/login", data={"handle": "captain"}, follow_redirects=False)
assert r.status_code == 303
r = c.get("/watch/1")
assert r.status_code == 200 and "hls.js" in r.text
r = c.get("/stream/1/index.m3u8")
assert r.status_code == 200 and "#EXTM3U" in r.text
r = c.get("/stream/1/seg00001.ts")
assert r.status_code == 200 and r.content == b"TS"
r = c.get("/stream/1/../../jackpottv.py")
assert r.status_code in (400, 404), r.status_code

guest = TestClient(jackpottv.app)
guest.post("/login", data={"handle": "viewer-one"})
r = guest.get("/stream/1/index.m3u8")
assert r.status_code == 403
r = guest.get("/")
assert "pending" in r.text.lower()

# captain admits from a fresh client carrying the captain cookie
cap = TestClient(jackpottv.app)
cap.post("/login", data={"handle": "captain"})
r = cap.get("/admin")
assert r.status_code == 200 and "viewer-one" in r.text
import sqlite3
mid = sqlite3.connect("/tmp/jackpot-test.db").execute(
    "select id from members where handle='viewer-one'").fetchone()[0]
r = cap.post(f"/admin/admit/{mid}", follow_redirects=False)
assert r.status_code == 303
r = guest.get("/stream/1/index.m3u8")
assert r.status_code == 200, r.status_code

r = cap.post(f"/admin/revoke/{mid}", follow_redirects=False)
assert r.status_code == 303
r = guest.get("/stream/1/index.m3u8")
assert r.status_code == 403, r.status_code

r = c.get("/api/now/1")
assert r.status_code == 200 and r.json()["live"] is True
print("jackpotTV gate tests: ALL PASS")

# --- stage + ticker feed ---
r = c.get("/stage")
assert r.status_code == 200 and "ticker" in r.text and "Atrium" in r.text
r = c.get("/feed.json")
assert r.status_code == 200 and "items" in r.json()

import importlib, ticker
from pathlib import Path as _P
ticker.SOURCE_FILE = _P("/tmp/jackpot-ticker-source.json")
ticker.SOURCE_FILE.write_text("{}")
doc = ticker.build(0)
assert doc["items"], "ticker produced no items"
assert all("text" in i for i in doc["items"])
src = ticker.load_source()
src["judge"] = ["Welcome, judges — this is live"]
src["music"] = "Test Tone — 440Hz"
ticker.SOURCE_FILE.write_text(__import__("json").dumps(src))
doc = ticker.build(1)
kinds = [i["kind"] for i in doc["items"]]
assert "judge" in kinds and "music" in kinds, kinds
print("stage + ticker feed: PASS")
