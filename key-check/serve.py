#!/usr/bin/env python3
"""
Serves sdk_test.html on http://localhost:8765 (use localhost, not 127.0.0.1: the SDK key is allowed on localhost only) and hands it MATTERPORT_SDK_KEY from .env,
so the key never sits in the HTML file. Localhost only. Ctrl+C to stop.
"""
import http.server
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", 8765))


def env(name):
    if os.environ.get(name):
        return os.environ[name].strip()
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    return ""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/sdk_test.html"
        if self.path == "/config.js":
            body = f"window.MP_SDK_KEY = {json.dumps(env('MATTERPORT_SDK_KEY'))};".encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/.env") or self.path.endswith(".py"):
            self.send_error(404)
            return
        super().do_GET()


if __name__ == "__main__":
    key = env("MATTERPORT_SDK_KEY")
    print(f"MATTERPORT_SDK_KEY: {'set (' + str(len(key)) + ' chars)' if key else 'NOT SET - add it to .env'}")
    print(f"Open http://localhost:{PORT}  (Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
