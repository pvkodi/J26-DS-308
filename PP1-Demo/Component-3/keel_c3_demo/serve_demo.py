"""Replay-only server for the Keel C3 viewer (frontend/index.html). Python standard library only: no model, no pipeline.

    python serve_demo.py [--port 8765] [--no-browser]

It answers the same API as the real viewer (keel-mvp/mvp/viz/server.py), from the pre-exported files in data/:
GET  /api/conversations   data/conversations.json
GET  /api/bundle?conv=ID&run=KEY   data/bundles/<conv>/<run>.json (chat) or data/bundles/<conv>/swe.json (SWE)
GET  /api/models          [] (no local model here)
POST /api/live/*          503: live runs are shown on the presenter's own laptop
"""

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "frontend" / "index.html"
DATA = ROOT / "data"
LIVE_MSG = "Live runs need the local model and are not part of this replay copy. Use the Keel presenter's laptop for live runs."


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def do_POST(self):
        if urlparse(self.path).path.startswith("/api/live/"):
            return self._json(503, {"error": LIVE_MSG})
        return self._json(404, {"error": "not found"})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/models":
            return self._json(200, [])
        if url.path == "/api/conversations":
            return self._send(200, (DATA / "conversations.json").read_bytes(), "application/json; charset=utf-8")
        if url.path == "/api/bundle":
            q = parse_qs(url.query)
            conv, run = (q.get("conv") or [""])[0], (q.get("run") or [""])[0]
            known = {c["id"]: c for c in json.loads((DATA / "conversations.json").read_text(encoding="utf-8"))}
            c = known.get(conv)
            if c is None:
                return self._json(404, {"error": f"unknown conversation '{conv}'"})
            if c.get("blocked"):
                return self._json(403, {"error": f"'{conv}' is in the frozen eval split and is not part of this demo copy."})
            if c["kind"] == "chat":
                run = run or c["runs"][0]
                if run not in c["runs"]:
                    return self._json(404, {"error": f"no stored run '{run}' for '{conv}'"})
                f = DATA / "bundles" / conv / f"{run}.json"
            else:
                f = DATA / "bundles" / conv / "swe.json"
            if not f.is_file():
                return self._json(404, {"error": f"bundle missing: {f.relative_to(ROOT)}"})
            return self._send(200, f.read_bytes(), "application/json; charset=utf-8")
        return self._json(404, {"error": "not found"})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    httpd = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Keel C3 viewer (replay only) at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
