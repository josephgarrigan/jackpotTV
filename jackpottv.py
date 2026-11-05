"""jackpotTV — agentic channel surfing.

One real channel (the Atrium, captured live into HLS on .212) behind a members-only
door. Admission is explicit and visible: request access, an operator admits you, and
only then can you watch. The HLS playlist and segments are served by THIS app and
checked on every request — the raw cast origin is never the door.

    uvicorn jackpottv:app --host 0.0.0.0 --port 8020

Env:
    JACKPOT_DB        app SQLite (default ./jackpottv.db)
    JACKPOT_ADMIN     operator handle; first login as this name becomes admin
    JACKPOT_HLS_DIR   directory holding atrium/index.m3u8 (deploy-local)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

DB = Path(os.environ.get("JACKPOT_DB", "jackpottv.db"))
ADMIN = os.environ.get("JACKPOT_ADMIN", "captain")
HLS_DIR = Path(os.environ.get("JACKPOT_HLS_DIR", "/var/lib/atrium-cast/hls"))
COOKIE = "jackpottv_session"
STATE_COOKIE = "jackpottv_fb_state"
FEED = Path(os.environ.get("JACKPOT_FEED", "/var/lib/jackpottv/feed.json"))
STAGE = Path(__file__).with_name("stage.html")
ATRIUM_FRAME = Path(os.environ.get("JACKPOT_ATRIUM_FRAME", "/var/lib/jackpottv/atrium-live.png"))
FRAMED = Path(__file__).with_name("atrium_framed.html")
GRAPH_VERSION = os.environ.get("FACEBOOK_GRAPH_VERSION", "v27.0")


def fb_config() -> dict:
    return {
        "app_id": os.environ.get("FACEBOOK_APP_ID", "").strip(),
        "app_secret": os.environ.get("FACEBOOK_APP_SECRET", "").strip(),
        "redirect_uri": os.environ.get("FACEBOOK_REDIRECT_URI", "").strip(),
        "admin_ids": {
            x.strip() for x in os.environ.get("JACKPOT_FACEBOOK_ADMIN_IDS", "").split(",") if x.strip()
        },
    }


def fb_configured() -> bool:
    cfg = fb_config()
    return bool(cfg["app_id"] and cfg["app_secret"] and cfg["redirect_uri"])


def graph_get(path: str, params: dict) -> dict:
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{path}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=12) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        raise HTTPException(502, "Facebook identity check failed") from exc

app = FastAPI(title="jackpotTV")

CSS = """
body{background:#0b0d10;color:#e8eaed;font:16px/1.5 system-ui;margin:0}
header{padding:16px 24px;border-bottom:1px solid #1e232a;display:flex;justify-content:space-between;align-items:center}
.brand{font-size:15px;letter-spacing:.18em;text-transform:uppercase;color:#f5c542}
.sub{color:#9aa4b2;font-size:13px}
main{max-width:1080px;margin:0 auto;padding:28px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}
.card{background:#12161b;border:1px solid #1e232a;border-radius:10px;padding:16px}
.card h2{font-size:17px;margin:0 0 4px}
.meta{color:#7d8796;font-size:13px}
.live{color:#ff5d5d;font-weight:700;font-size:12px;letter-spacing:.08em}
.lock{color:#f5c542;font-size:13px}
video{width:100%;background:#000;border-radius:10px}
input,button{background:#12161b;border:1px solid #2a3240;color:#e8eaed;padding:9px 11px;border-radius:8px}
button{background:#b8860b;border-color:#b8860b;cursor:pointer;font-weight:600}
button.secondary{background:transparent;border-color:#2a3240}
label{display:block;margin:10px 0 4px;color:#9aa4b2;font-size:13px}
form.inline{display:inline}
.notice{background:#171207;border:1px solid #4a3808;border-radius:10px;padding:14px 16px;margin:16px 0}
a{color:#f5c542}
"""

def page(title: str, who: str, body: str) -> str:
    right = who if who else '<a href="/login">sign in</a>'
    return (f"<!doctype html><meta charset=utf-8><title>{title}</title><style>{CSS}</style>"
            f"<header><div><span class=brand>jackpotTV</span> "
            f"<span class=sub>agentic channel surfing</span></div>"
            f"<span class=meta>{right}</span></header><main>{body}</main>")

def db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript("""
        create table if not exists members(
            id integer primary key,
            handle text not null unique,
            status text not null default 'pending',
            is_admin integer not null default 0,
            requested_at text not null,
            decided_at text
        );
        create table if not exists oauth_states(
            state_hash text primary key,
            created_at real not null,
            expires_at real not null
        );
        create table if not exists deletion_requests(
            confirmation_code text primary key,
            facebook_id_hash text not null,
            status text not null,
            created_at text not null,
            completed_at text
        );
        create table if not exists sessions(
            token text primary key,
            member_id integer not null,
            created_at text not null
        );
        create table if not exists channels(
            id integer primary key,
            name text not null,
            kind text not null default 'hls',
            ref text not null,
            owner text not null,
            created_at text not null
        );
    """)
    cols = {r[1] for r in c.execute("pragma table_info(members)")}
    for name, ddl in {
        "facebook_id": "text",
        "display_name": "text",
        "email": "text",
        "fb_token_expires_at": "text",
        "deauthorized_at": "text",
    }.items():
        if name not in cols:
            c.execute(f"alter table members add column {name} {ddl}")
    c.execute("create unique index if not exists idx_members_facebook_id on members(facebook_id) where facebook_id is not null")
    c.commit()
    return c

def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def seed() -> None:
    c = db()
    if not c.execute("select 1 from channels where id=1").fetchone():
        c.execute("insert into channels(id,name,kind,ref,owner,created_at) values(1,'atrium','local','atrium','captain',?)", (now(),))
        c.commit()

@app.on_event("startup")
def _startup() -> None:
    seed()

def current(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    row = db().execute(
        "select m.* from sessions s join members m on m.id=s.member_id where s.token=?",
        (token,)).fetchone()
    return dict(row) if row else None

def admitted(member) -> bool:
    return bool(member and member["status"] == "admitted")


def start_session(member_id: int) -> str:
    token = secrets.token_urlsafe(32)
    c = db()
    c.execute("insert into sessions(token,member_id,created_at) values(?,?,?)", (token, member_id, now()))
    c.commit()
    return token


def session_response(member_id: int) -> RedirectResponse:
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, start_session(member_id), httponly=True, samesite="lax")
    return resp


def upsert_facebook_member(profile: dict, token_expires_at: str | None) -> int:
    cfg = fb_config()
    facebook_id = str(profile["id"])
    email = str(profile.get("email") or "").strip().lower()
    display_name = str(profile.get("name") or "").strip()
    handle = f"fb:{facebook_id}"
    is_operator = facebook_id in cfg["admin_ids"]
    c = db()
    row = c.execute("select * from members where facebook_id=?", (facebook_id,)).fetchone()
    if row is None and email:
        row = c.execute("select * from members where lower(email)=?", (email,)).fetchone()
    if row is None:
        cur = c.execute(
            """insert into members(handle,status,is_admin,requested_at,decided_at,facebook_id,display_name,email,fb_token_expires_at)
               values(?,?,?,?,?,?,?,?,?)""",
            (handle, "admitted" if is_operator else "pending", 1 if is_operator else 0,
             now(), now() if is_operator else None, facebook_id, display_name, email, token_expires_at),
        )
        member_id = int(cur.lastrowid)
        c.commit()
        return member_id
    c.execute(
        """update members set facebook_id=?, display_name=?, email=?, fb_token_expires_at=?,
           deauthorized_at=null, is_admin=?, status=?, decided_at=?
           where id=?""",
        (facebook_id, display_name or row["display_name"], email or row["email"], token_expires_at,
         1 if is_operator else row["is_admin"],
         "admitted" if is_operator else row["status"],
         now() if is_operator else row["decided_at"], row["id"]),
    )
    c.commit()
    return int(row["id"])


def parse_signed_request(signed_request: str) -> dict:
    cfg = fb_config()
    if not fb_configured():
        raise HTTPException(503, "Facebook login is not configured")
    try:
        encoded_sig, payload = signed_request.split(".", 1)
        pad = "=" * (-len(payload) % 4)
        body = base64.urlsafe_b64decode(payload + pad)
        expected = hmac.new(cfg["app_secret"].encode(), payload.encode(), hashlib.sha256).digest()
        given = base64.urlsafe_b64decode(encoded_sig + "=" * (-len(encoded_sig) % 4))
    except Exception as exc:
        raise HTTPException(400, "invalid signed request") from exc
    if not hmac.compare_digest(expected, given):
        raise HTTPException(400, "invalid signed request signature")
    data = json.loads(body)
    if data.get("algorithm", "HMAC-SHA256").upper() != "HMAC-SHA256":
        raise HTTPException(400, "unexpected signed request algorithm")
    return data

@app.get("/", response_class=HTMLResponse)
def guide(request: Request) -> str:
    m = current(request)
    rows = db().execute("select * from channels order by id").fetchall()
    cards = ""
    for r in rows:
        if admitted(m):
            action = f'<a href="/watch/{r["id"]}">Watch channel {r["id"]:02d}</a> · <span class=live>● LIVE</span>'
        else:
            action = '<span class=lock>Members only — admission required</span>'
        cards += (f'<div class=card><h2>{r["name"]}</h2><div class=meta>'
                  f'channel {r["id"]:02d} · {r["owner"]} · the live floor</div>{action}</div>')
    if m and m["status"] == "pending":
        banner = '<div class=notice>Your access request is pending. An operator admits members; nothing to do but wait — or ask the Captain.</div>'
    elif not m:
        banner = '<div class=notice>One channel. One door. <a href="/login">Sign in and request access</a> to watch the Atrium live.</div>'
    else:
        banner = ""
    admin_link = ' · <a href="/admin">admissions</a>' if m and m.get("is_admin") else ""
    who = (f'{m.get("display_name") or m["handle"]} ({m["status"]}){admin_link} · <form class=inline method=post action=/logout>'
           '<button class=secondary type=submit>sign out</button></form>') if m else ""
    return page("jackpotTV", who, f"{banner}<div class=grid>{cards}</div>")

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> str:
    if fb_configured():
        body = """<h2 style="font-size:16px;color:#9aa4b2">Sign in</h2>
        <p class=meta>Facebook confirms who you are. jackpotTV then files an admission
        request; an operator admits you before the channel will play.</p>
        <p><a href="/auth/facebook/login"><button type=button>Continue with Facebook</button></a></p>
        <p class=meta>Only public profile and email are requested.</p>"""
    else:
        body = """<h2 style="font-size:16px;color:#9aa4b2">Sign in</h2>
        <p class=meta>Facebook login is not configured yet, so this local handle form is
        only a development fallback. Your first sign-in files an access request; an
        operator admits you. Choose the admin handle to operate the door.</p>
        <form method=post action=/login>
          <label>Handle<input name=handle required placeholder="your-name" autocomplete="username"></label>
          <button type=submit>Enter</button>
        </form>"""
    return page("Sign in — jackpotTV", "", body)

@app.post("/login")
def login(handle: str = Form(...)):
    handle = handle.strip().lower()[:40] or "guest"
    c = db()
    row = c.execute("select * from members where handle=?", (handle,)).fetchone()
    if row is None:
        is_admin = 1 if handle == ADMIN else 0
        status = "admitted" if is_admin else "pending"
        cur = c.execute(
            "insert into members(handle,status,is_admin,requested_at,decided_at) values(?,?,?,?,?)",
            (handle, status, is_admin, now(), now() if is_admin else None))
        member_id = cur.lastrowid
    else:
        member_id = row["id"]
    c.commit()
    return session_response(member_id)

@app.get("/auth/facebook/login")
def facebook_login():
    cfg = fb_config()
    if not fb_configured():
        raise HTTPException(503, "Facebook login is not configured")
    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    c = db()
    c.execute("delete from oauth_states where expires_at < ?", (time.time(),))
    c.execute(
        "insert into oauth_states(state_hash,created_at,expires_at) values(?,?,?)",
        (state_hash, time.time(), time.time() + 600),
    )
    c.commit()
    query = urllib.parse.urlencode({
        "client_id": cfg["app_id"],
        "redirect_uri": cfg["redirect_uri"],
        "state": state,
        "response_type": "code",
        "scope": "public_profile,email",
    })
    resp = RedirectResponse(f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?{query}", status_code=303)
    resp.set_cookie(STATE_COOKIE, state, httponly=True, samesite="lax", max_age=600)
    return resp


@app.get("/auth/facebook/callback")
def facebook_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    cfg = fb_config()
    if error:
        raise HTTPException(400, "Facebook login was cancelled or refused")
    if not fb_configured() or not code or not state:
        raise HTTPException(400, "incomplete Facebook login response")
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    cookie_state = request.cookies.get(STATE_COOKIE, "")
    c = db()
    row = c.execute(
        "select * from oauth_states where state_hash=? and expires_at>=?", (state_hash, time.time())
    ).fetchone()
    c.execute("delete from oauth_states where state_hash=?", (state_hash,))
    c.commit()
    if row is None or not hmac.compare_digest(cookie_state, state):
        raise HTTPException(400, "Facebook login state check failed")

    token_data = graph_get("oauth/access_token", {
        "client_id": cfg["app_id"],
        "redirect_uri": cfg["redirect_uri"],
        "client_secret": cfg["app_secret"],
        "code": code,
    })
    user_token = token_data.get("access_token")
    if not user_token:
        raise HTTPException(502, "Facebook did not return an access token")

    app_token = f"{cfg['app_id']}|{cfg['app_secret']}"
    inspected = graph_get("debug_token", {"input_token": user_token, "access_token": app_token}).get("data") or {}
    if not inspected.get("is_valid") or str(inspected.get("app_id")) != cfg["app_id"] or not inspected.get("user_id"):
        raise HTTPException(502, "Facebook access token did not validate for this app")
    profile = graph_get("me", {"fields": "id,name,email", "access_token": user_token})
    if str(profile.get("id")) != str(inspected["user_id"]):
        raise HTTPException(502, "Facebook profile did not match the inspected token")

    expires_at = None
    if token_data.get("expires_in"):
        expires_at = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + int(token_data["expires_in"]))
        )
    member_id = upsert_facebook_member(profile, expires_at)
    resp = session_response(member_id)
    resp.delete_cookie(STATE_COOKIE)
    return resp


@app.post("/auth/facebook/deauthorize")
def facebook_deauthorize(signed_request: str = Form(...)):
    data = parse_signed_request(signed_request)
    facebook_id = str(data.get("user_id") or "")
    if facebook_id:
        c = db()
        c.execute(
            """update members set status='revoked', deauthorized_at=?
               where facebook_id=?""", (now(), facebook_id))
        c.execute(
            """delete from sessions where member_id in
               (select id from members where facebook_id=?)""", (facebook_id,))
        c.commit()
    return {"ok": True}


@app.post("/auth/facebook/data-deletion")
def facebook_data_deletion(signed_request: str = Form(...)):
    data = parse_signed_request(signed_request)
    facebook_id = str(data.get("user_id") or "")
    if not facebook_id:
        raise HTTPException(400, "signed request has no user id")
    confirmation_code = secrets.token_urlsafe(18)
    id_hash = hashlib.sha256(facebook_id.encode()).hexdigest()
    c = db()
    c.execute(
        "delete from sessions where member_id in (select id from members where facebook_id=?)",
        (facebook_id,),
    )
    c.execute("delete from members where facebook_id=?", (facebook_id,))
    c.execute(
        """insert into deletion_requests(confirmation_code,facebook_id_hash,status,created_at,completed_at)
           values(?,?,?,?,?)""",
        (confirmation_code, id_hash, "complete", now(), now()),
    )
    c.commit()
    cfg = fb_config()
    base = cfg["redirect_uri"].split("/auth/facebook/callback")[0]
    return {
        "url": f"{base}/privacy/data-deletion/{confirmation_code}",
        "confirmation_code": confirmation_code,
    }


@app.get("/privacy", response_class=HTMLResponse)
def privacy() -> str:
    body = """<h2 style="font-size:16px;color:#9aa4b2">Privacy</h2>
    <p>jackpotTV uses Facebook Login only to confirm identity for admission to a
    members-only live channel. We receive a Facebook user ID, display name, and
    email address when Facebook provides it.</p>
    <p>We store that identity with your admission status and a local session cookie.
    We do not post to Facebook, read your timeline, or store your Facebook access
    token after login. You can request deletion through Facebook's app settings or
    by contacting the operator.</p>"""
    return page("Privacy — jackpotTV", "", body)


@app.get("/privacy/data-deletion/{confirmation_code}")
def deletion_status(confirmation_code: str) -> dict:
    row = db().execute(
        "select status,created_at,completed_at from deletion_requests where confirmation_code=?",
        (confirmation_code,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "unknown confirmation code")
    return {"confirmation_code": confirmation_code, **dict(row)}


@app.post("/logout")
def logout(request: Request):
    token = request.cookies.get(COOKIE)
    if token:
        c = db(); c.execute("delete from sessions where token=?", (token,)); c.commit()
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request) -> str:
    m = current(request)
    if not (m and m.get("is_admin")):
        raise HTTPException(403, "operators only")
    rows = db().execute("select * from members order by id").fetchall()
    items = ""
    for r in rows:
        btn = ""
        if r["status"] != "admitted":
            btn += f'<form class=inline method=post action=/admin/admit/{r["id"]}><button type=submit>admit</button></form> '
        if r["status"] != "revoked":
            btn += f'<form class=inline method=post action=/admin/revoke/{r["id"]}><button class=secondary type=submit>revoke</button></form>'
        label = r["display_name"] or r["handle"]
        items += f'<div class=card><b>{label}</b> <span class=meta>{r["handle"]} · {r["status"]} · requested {r["requested_at"]}</span> {btn}</div>'
    return page("Admissions — jackpotTV", m["handle"], f"<h2 style='font-size:16px;color:#9aa4b2'>Members</h2>{items}")

@app.post("/admin/admit/{member_id}")
def admit(request: Request, member_id: int):
    m = current(request)
    if not (m and m.get("is_admin")):
        raise HTTPException(403, "operators only")
    c = db(); c.execute("update members set status='admitted', decided_at=? where id=?", (now(), member_id)); c.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/revoke/{member_id}")
def revoke(request: Request, member_id: int):
    m = current(request)
    if not (m and m.get("is_admin")):
        raise HTTPException(403, "operators only")
    c = db(); c.execute("update members set status='revoked', decided_at=? where id=?", (now(), member_id)); c.commit()
    return RedirectResponse("/admin", status_code=303)

@app.get("/watch/{cid}", response_class=HTMLResponse)
def watch(request: Request, cid: int) -> str:
    m = current(request)
    if not admitted(m):
        raise HTTPException(403, "members only")
    row = db().execute("select * from channels where id=?", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "no such channel")
    body = (f'<h2 style="font-size:15px;color:#9aa4b2">{row["name"]} · <span class=live>● LIVE</span></h2>'
            '<script src="https://cdn.jsdelivr.net/npm/hls.js@1"></script>'
            '<video id=v controls autoplay muted playsinline></video>'
            '<script>'
            'const v=document.getElementById("v");'
            f'const src="/stream/{cid}/index.m3u8";'
            'if(v.canPlayType("application/vnd.apple.mpegurl")){v.src=src;}'
            'else if(window.Hls&&Hls.isSupported()){const h=new Hls();h.loadSource(src);h.attachMedia(v);}'
            'else{v.src=src;}'
            '</script>'
            '<p class=meta><a href="/">← back to the guide</a></p>')
    return page(row["name"], m.get("display_name") or m["handle"], body)

@app.get("/stream/{cid}/{name}")
def stream(request: Request, cid: int, name: str):
    """Serve the gated playlist/segments. Checked on every request."""
    m = current(request)
    if not admitted(m):
        raise HTTPException(403, "members only")
    row = db().execute("select * from channels where id=?", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "no such channel")
    if row["kind"] != "local":
        raise HTTPException(400, "channel is not a local cast")
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "bad segment name")
    path = HLS_DIR / row["ref"] / name
    if not path.is_file():
        raise HTTPException(404, "segment not ready")
    if name.endswith(".m3u8"):
        resp = FileResponse(path, media_type="application/vnd.apple.mpegurl")
    elif name.endswith(".ts"):
        resp = FileResponse(path, media_type="video/mp2t")
    else:
        raise HTTPException(404, "unknown media type")
    resp.headers["Cache-Control"] = "no-cache"
    return resp

@app.get("/stage", response_class=HTMLResponse)
def stage_page() -> str:
    """The broadcast frame: floor on top, scrolling feed along the bottom.
    Public to view locally; the tuned channel stays behind the member gate."""
    return STAGE.read_text()


@app.get("/atrium-framed.html", response_class=HTMLResponse)
def atrium_framed() -> str:
    return FRAMED.read_text()


@app.get("/atrium-live.png")
def atrium_live_png():
    if not ATRIUM_FRAME.is_file():
        raise HTTPException(503, "Atrium frame is warming up")
    resp = FileResponse(ATRIUM_FRAME, media_type="image/png")
    resp.headers["Cache-Control"] = "no-cache, no-store"
    return resp


@app.get("/feed.json")
def feed() -> dict:
    try:
        return json.loads(FEED.read_text())
    except Exception:
        return {"seq": 0, "items": [{"kind": "sys", "text": "jackpotTV — feed warming up"}]}


@app.get("/api/now/{cid}")
def now_playing(cid: int) -> dict:
    row = db().execute("select * from channels where id=?", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "no such channel")
    playlist = HLS_DIR / row["ref"] / "index.m3u8"
    return {"id": cid, "name": row["name"], "owner": row["owner"],
            "live": playlist.is_file(),
            "playlist": f"/stream/{cid}/index.m3u8"}
