"""Channel Surfing — a thin social TV guide.

The demo: a stranger signs in, registers a channel, and switches to the Captain's,
which is HLS playing from this host. No platform internals are exposed; the app
holds one read-only view of its own channel table.

Run:  uvicorn app:app --host 0.0.0.0 --port 8020
Env:  CHANNEL_DB=/var/lib/channel-app/channels.db
      ATRIUM_HLS=http://192.168.1.212:8021/atrium/index.m3u8
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

DB = Path(os.environ.get("CHANNEL_DB", "/var/lib/channel-app/channels.db"))
ATRIUM_HLS = os.environ.get("ATRIUM_HLS", "http://192.168.1.212:8021/atrium/index.m3u8")

app = FastAPI(title="Channel Surfing")

PAGE = """<!doctype html><meta charset=utf-8><title>{title}</title>
<style>
 body{{background:#0b0d10;color:#e8eaed;font:16px/1.5 system-ui;margin:0}}
 header{{padding:18px 28px;border-bottom:1px solid #1e232a;display:flex;justify-content:space-between}}
 h1{{font-size:18px;margin:0;letter-spacing:.12em;text-transform:uppercase;color:#9aa4b2}}
 main{{max-width:1080px;margin:0 auto;padding:28px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}}
 .card{{background:#12161b;border:1px solid #1e232a;border-radius:10px;padding:14px}}
 .card a{{color:#e8eaed;text-decoration:none;font-weight:600}}
 .meta{{color:#7d8796;font-size:13px}}
 video{{width:100%;background:#000;border-radius:10px}}
 input,button{{background:#12161b;border:1px solid #2a3240;color:#e8eaed;padding:9px 11px;border-radius:8px}}
 button{{background:#1f6feb;border-color:#1f6feb;cursor:pointer}}
 label{{display:block;margin:10px 0 4px;color:#9aa4b2;font-size:13px}}
</style>
<header><h1>Channel Surfing</h1><span class=meta>{who}</span></header>
<main>{body}</main>"""


def db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute(
        "create table if not exists channels("
        "id integer primary key, name text not null, stream_url text not null,"
        " owner text not null, created_at text not null)"
    )
    c.commit()
    return c


def seed() -> None:
    c = db()
    if not c.execute("select 1 from channels where id=1").fetchone():
        c.execute(
            "insert into channels(id,name,stream_url,owner,created_at) values(1,?,?,?,?)",
            ("atrium", ATRIUM_HLS, "captain", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        )
        c.commit()


@app.on_event("startup")
def _startup() -> None:
    seed()


def who(request: Request) -> str:
    return request.cookies.get("surfer", "guest")


@app.get("/", response_class=HTMLResponse)
def guide(request: Request) -> str:
    rows = db().execute("select id,name,stream_url,owner from channels order by id").fetchall()
    cards = "".join(
        f'<div class=card><a href="/watch/{i}">{n}</a>'
        f'<div class=meta>channel {i:02d} · {o}</div></div>'
        for i, n, _s, o in rows
    )
    form = """<h2 style="font-size:15px;color:#9aa4b2;margin-top:26px">Register a channel</h2>
<form method=post action=/channels>
 <label>Name<input name=name required placeholder="my channel" style="width:100%"></label>
 <label>Stream URL<input name=stream_url required placeholder="https://…/index.m3u8" style="width:100%"></label>
 <button type=submit>Go live</button></form>"""
    return PAGE.format(title="Channel Surfing", who=who(request),
                       body=f"<div class=grid>{cards}</div>{form}")


@app.post("/channels")
def register(request: Request, name: str = Form(...), stream_url: str = Form(...)):
    c = db()
    c.execute(
        "insert into channels(name,stream_url,owner,created_at) values(?,?,?,?)",
        (name.strip()[:40], stream_url.strip(), who(request),
         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
    )
    c.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/watch/{cid}", response_class=HTMLResponse)
def watch(request: Request, cid: int) -> str:
    row = db().execute("select name,stream_url from channels where id=?", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "no such channel")
    name, url = row
    body = (f'<h2 style="font-size:15px;color:#9aa4b2">{name}</h2>'
            f'<video controls autoplay muted src="{url}"></video>'
            f'<p class=meta><a href="/" style="color:#1f6feb">← back to the guide</a></p>')
    return PAGE.format(title=name, who=who(request), body=body)


@app.post("/login")
def login(request: Request, handle: str = Form(...)):
    """Demo identity: a handle, not an OAuth flow. Swap for Facebook before submit."""
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("surfer", handle.strip()[:40] or "guest")
    return resp


@app.get("/api/now/{cid}")
def now(cid: int) -> dict:
    row = db().execute("select name,stream_url,owner from channels where id=?", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "no such channel")
    return {"id": cid, "name": row[0], "stream_url": row[1], "owner": row[2]}
