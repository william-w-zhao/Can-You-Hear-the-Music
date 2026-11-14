#!/usr/bin/env python3
"""
Room acoustics app on http://localhost:8766 (localhost only).

    /            the acoustics page (index.html)
    /audio/...   the dry voice clip
    /data/...    the shared per-model cache in <project>/data/ (rooms.json, acoustics.json, floor plans)

The building explorer is a separate app on http://localhost:8765. Never serves .env or .py files.
"""
import http.server
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))  # shared/common.py
from common import DATA

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", 8766))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def translate_path(self, path):
        clean = path.split("?")[0].split("#")[0]
        if clean == "/data" or clean.startswith("/data/"):
            target = (DATA / clean[len("/data/"):]).resolve()
            return str(target) if target.is_relative_to(DATA) else str(DATA / "__denied__")
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def blocked(self):
        path = self.path.split("?")[0]
        return any(part.startswith(".env") for part in path.split("/")) or path.endswith(".py")

    def do_GET(self):
        return self.send_error(404) if self.blocked() else super().do_GET()

    def do_HEAD(self):
        return self.send_error(404) if self.blocked() else super().do_HEAD()


if __name__ == "__main__":
    print(f"Acoustics: http://localhost:{PORT}\nExplorer:  http://localhost:8765 (separate app: python3 explorer/serve.py)\n(Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
