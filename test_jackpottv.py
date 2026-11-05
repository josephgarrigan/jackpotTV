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
r = c.get("/auth/facebook/login")
assert r.status_code == 503, r.status_code

import importlib, json, ticker
from pathlib import Path as _P
ticker.SOURCE_FILE = _P("/tmp/jackpot-ticker-source.json")
ticker.SOURCE_FILE.write_text("{}")
doc = ticker.build(0)
assert doc["items"] and all("text" in i for i in doc["items"])
src = ticker.load_source()
src["judge"] = ["Welcome, judges — this is live"]
src["music"] = "Test Tone — 440Hz"
ticker.SOURCE_FILE.write_text(json.dumps(src))
doc = ticker.build(1)
kinds = [i["kind"] for i in doc["items"]]
assert "judge" in kinds and "music" in kinds, kinds

# --- Facebook manual OAuth flow (Meta calls mocked; no real secret/token) ---
import hashlib, hmac, base64
os.environ["FACEBOOK_APP_ID"] = "123456789"
os.environ["FACEBOOK_APP_SECRET"] = "test-app-secret"
os.environ["FACEBOOK_REDIRECT_URI"] = "https://jackpottv.example/auth/facebook/callback"
os.environ["JACKPOT_FACEBOOK_ADMIN_IDS"] = "999"
fb = TestClient(jackpottv.app); fb.__enter__()
r = fb.get("/auth/facebook/login", follow_redirects=False)
assert r.status_code == 303 and "facebook.com/v27.0/dialog/oauth" in r.headers["location"]
assert "response_type=code" in r.headers["location"] and "scope=public_profile%2Cemail" in r.headers["location"]
state = dict(x.split("=",1) for x in r.headers["location"].split("?",1)[1].split("&"))["state"]
state = __import__("urllib.parse", fromlist=["unquote"]).unquote(state)

real_graph = jackpottv.graph_get
def fake_graph(path, params):
    if path == "oauth/access_token":
        return {"access_token": "TEST-USER-TOKEN", "token_type": "bearer", "expires_in": 3600}
    if path == "debug_token":
        return {"data": {"is_valid": True, "app_id": "123456789", "user_id": "999"}}
    if path == "me":
        return {"id": "999", "name": "Captain Judge", "email": "captain@example.com"}
    raise AssertionError(path)
jackpottv.graph_get = fake_graph
r = fb.get(f"/auth/facebook/callback?code=TESTCODE&state={state}", follow_redirects=False)
assert r.status_code == 303, (r.status_code, r.text)
r = fb.get("/stream/1/index.m3u8")
assert r.status_code == 200  # configured Facebook ID is an operator for this test
r = fb.get(f"/auth/facebook/callback?code=TESTCODE&state={state}", follow_redirects=False)
assert r.status_code == 400  # states are single-use
jackpottv.graph_get = real_graph

def signed(user_id):
    payload = base64.urlsafe_b64encode(json.dumps({"algorithm":"HMAC-SHA256","user_id":user_id}).encode()).decode().rstrip("=")
    sig = hmac.new(b"test-app-secret", payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=") + "." + payload
r = fb.post("/auth/facebook/data-deletion", data={"signed_request": signed("999")})
assert r.status_code == 200 and r.json()["confirmation_code"]
code = r.json()["confirmation_code"]
assert fb.get(f"/privacy/data-deletion/{code}").json()["status"] == "complete"
assert fb.get("/stream/1/index.m3u8").status_code == 403  # member + sessions deleted
print("stage + ticker + facebook manual flow: PASS")
