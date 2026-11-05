#!/usr/bin/env python3
"""Keep a current PNG of the real Atrium for the jackpotTV stage."""
import time
from playwright.sync_api import sync_playwright
URL = "http://192.168.1.157:8090/assets/erpnext/atrium/index.html"
OUT = "/var/lib/jackpottv/atrium-live.png"
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
    pg = b.new_page(viewport={"width":1280,"height":636}, device_scale_factor=1)
    pg.goto(URL, wait_until="load", timeout=30000)
    pg.wait_for_timeout(4000)
    print("frame capture rolling", flush=True)
    import os
    print("frame target", OUT, os.path.exists("/var/lib/jackpottv"), flush=True)
    while True:
        try:
            body = pg.evaluate("() => document.body && document.body.scrollHeight")
            pg.set_viewport_size({"width":1280,"height":636})
            pg.wait_for_timeout(900)
            pg.screenshot(path=OUT)
        except Exception as e:
            print("frame capture error", repr(e), flush=True)
            time.sleep(2)
        time.sleep(2)
