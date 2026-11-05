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

import os
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

DB = Path(os.environ.get("JACKPOT_DB", "jackpottv.db"))
ADMIN = os.environ.get("JACKPOT_ADMIN", "captain")
HLS_DIR = Path(os.environ.get("JACKPOT_HLS_DIR", "/var/lib/atrium-cast/hls"))
COOKIE = "jackpottv_session"

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
    who = (f'{m["handle"]} ({m["status"]}){admin_link} · <form class=inline method=post action=/logout>'
           '<button class=secondary type=submit>sign out</button></form>') if m else ""
    return page("jackpotTV", who, f"{banner}<div class=grid>{cards}</div>")

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> str:
    body = """<h2 style="font-size:16px;color:#9aa4b2">Sign in</h2>
    <p class=meta>Demo identity is a handle, not OAuth. Your first sign-in files an
    access request; an operator admits you. Choose the admin handle to operate the door.</p>
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
    token = secrets.token_urlsafe(32)
    c.execute("insert into sessions(token,member_id,created_at) values(?,?,?)", (token, member_id, now()))
    c.commit()
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax")
    return resp

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
        items += f'<div class=card><b>{r["handle"]}</b> <span class=meta>{r["status"]} · requested {r["requested_at"]}</span> {btn}</div>'
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
    return page(row["name"], m["handle"], body)

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

@app.get("/api/now/{cid}")
def now_playing(cid: int) -> dict:
    row = db().execute("select * from channels where id=?", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "no such channel")
    playlist = HLS_DIR / row["ref"] / "index.m3u8"
    return {"id": cid, "name": row["name"], "owner": row["owner"],
            "live": playlist.is_file(),
            "playlist": f"/stream/{cid}/index.m3u8"}
