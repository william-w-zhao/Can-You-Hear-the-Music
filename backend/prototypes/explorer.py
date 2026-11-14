#!/usr/bin/env python3
"""
Building explorer + SDK key check on http://localhost:8765 (localhost only; the SDK key is allowed there).

    /                     building explorer: pick any kit building, then any room
    /keys                 Showcase SDK key check (key-check/sdk_test.html)
    /api/catalog          every model in the kit CSVs, with a short CoStar summary and a "cached" flag
    /api/kit/<sid>        that model's full CoStar records from the kit (no network)
    POST /api/fetch/<sid> run the fetch_building and shadows pipeline modules in the background
    GET  /api/fetch/<sid> that job's status and log
    /api/names?ids=a,b    Matterport model names (e.g. "Suite 410 - 3,500 SF"), cached in data/names.json

    /data/...             the shared per-model cache in <project>/data/
    /acoustics            redirects to the acoustics app (http://localhost:8766)

Reads MATTERPORT_SDK_KEY from <project>/.env or key-check/.env. Never serves .env or .py files.
"""
import http.server
import json
import os
import subprocess
import sys
import threading

from app.sources import costar_kit as catalog
from app.sources.config import BACKEND, DATA, FRONTEND, ROOT, secret
from app.sources.matterport import mp

PAGE = FRONTEND / "prototypes" / "explorer"
ACOUSTICS_URL = os.environ.get("ACOUSTICS_URL", "http://localhost:8766")
KEYCHECK = ROOT / "key-check"
PORT = int(os.environ.get("PORT", 8765))

CATALOG, OFFSETS = catalog.load()
SIDS = {r["sid"] for r in CATALOG}
JOBS = {}            # sid -> {"state": running|done|failed, "log": [...]}
JOBS_LOCK = threading.Lock()
NAMES_FILE = DATA / "names.json"
NAMES = json.loads(NAMES_FILE.read_text()) if NAMES_FILE.exists() else {}
NAMES_LOCK = threading.Lock()


def model_names(sids):
    """Names for up to 60 models: cache first, then one aliased GraphQL query for the rest."""
    sids = [s for s in sids if s in SIDS][:60]
    with NAMES_LOCK:
        missing = [s for s in sids if s not in NAMES]
        if missing:
            q = "query {" + " ".join(f'm{i}: model(id: "{s}") {{ name }}' for i, s in enumerate(missing)) + "}"
            try:
                data = mp(q)
                for i, s in enumerate(missing):
                    NAMES[s] = (data.get(f"m{i}") or {}).get("name") or ""
                NAMES_FILE.write_text(json.dumps(NAMES, separators=(",", ":")))
            except (Exception, SystemExit) as e:   # no keys / offline: the page falls back to model ids
                print(f"  names lookup failed: {e}")
        return {s: NAMES.get(s, "") for s in sids}


def cached_ids():
    idx = DATA / "index.json"
    models = json.loads(idx.read_text()) if idx.exists() else {}
    return {sid for sid in models if (DATA / sid / "bundle.json").exists()}


def run_job(sid):
    job = JOBS[sid]
    steps = ("app.pipeline.fetch_building", "app.pipeline.shadows")
    for i, module in enumerate(steps):
        cmd = [sys.executable, "-u", "-m", module, "--model", sid]
        job["log"].append(f"$ python -m {module} --model {sid}")
        p = subprocess.Popen(cmd, cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            job["log"].append(line.rstrip())
        if p.wait() != 0:
            if i == 0:                      # no bundle: the page has nothing new to show
                job["state"] = "failed"
                return
            job["log"].append("(shadow heights could not be computed for this model; the rest is saved)")
    job["state"] = "done"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(PAGE), **kw)

    def translate_path(self, path):
        """/data/... is the shared cache at <project>/data/; serve other files from the prototype page directory."""
        clean = path.split("?")[0].split("#")[0]
        if clean == "/data" or clean.startswith("/data/"):
            target = (DATA / clean[len("/data/"):]).resolve()
            return str(target) if target.is_relative_to(DATA) else str(DATA / "__denied__")
        return super().translate_path(path)

    def log_message(self, fmt, *args):
        if "/api/fetch/" not in self.path:   # the page polls this; keep the console readable
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, obj, status=200):
        body = json.dumps(obj, separators=(",", ":"), default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api_sid(self, prefix):
        sid = self.path.split("?")[0][len(prefix):].strip("/")
        return sid if sid in SIDS else None

    def do_POST(self):
        path = self.path.split("?")[0]
        if not path.startswith("/api/fetch/"):
            return self.send_error(404)
        # Only the page itself may start a fetch (the job calls paid APIs with your keys).
        origin = self.headers.get("Origin", "")
        if origin and origin not in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"):
            return self.send_error(403)
        sid = self.api_sid("/api/fetch/")
        if not sid:
            return self.send_json({"error": "unknown model id"}, 404)
        with JOBS_LOCK:
            if JOBS.get(sid, {}).get("state") != "running":
                JOBS[sid] = {"state": "running", "log": []}
                threading.Thread(target=run_job, args=(sid,), daemon=True).start()
        self.send_json(JOBS[sid])

    def do_GET(self):
        path = self.path.split("?")[0]
        if any(part.startswith(".env") for part in path.split("/")) or path.endswith(".py"):
            return self.send_error(404)
        if path == "/api/catalog":
            have = cached_ids()
            return self.send_json([{**r, "cached": r["sid"] in have} for r in CATALOG])
        if path == "/api/names":
            from urllib.parse import parse_qs, urlsplit
            ids = parse_qs(urlsplit(self.path).query).get("ids", [""])[0].split(",")
            return self.send_json(model_names([i for i in ids if i]))
        if path == "/api/enums":
            return self.send_json(json.loads((catalog.KIT / "schemas" / "enums.json").read_text()))
        if path.startswith("/api/kit/"):
            sid = self.api_sid("/api/kit/")
            if not sid:
                return self.send_json({"error": "unknown model id"}, 404)
            row = next(r for r in CATALOG if r["sid"] == sid)
            return self.send_json({"row": row, **catalog.kit_records(sid, OFFSETS)})
        if path.startswith("/api/fetch/"):
            sid = self.api_sid("/api/fetch/")
            return self.send_json(JOBS.get(sid) or {"state": "idle", "log": []})
        if path == "/config.js":
            body = f"window.MP_SDK_KEY = {json.dumps(secret('MATTERPORT_SDK_KEY', False) or '')};".encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/keys", "/keys/"):
            body = (KEYCHECK / "sdk_test.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/acoustics", "/acoustics/", "/acoustics.html"):
            from urllib.parse import urlsplit
            q = urlsplit(self.path).query
            self.send_response(302)
            self.send_header("Location", ACOUSTICS_URL + "/" + (f"?{q}" if q else ""))
            self.end_headers()
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()


if __name__ == "__main__":
    print(f"Explorer:  http://localhost:{PORT}  ({len(CATALOG):,} buildings in the catalog)\n"
          f"SDK check: http://localhost:{PORT}/keys\n"
          f"Acoustics: {ACOUSTICS_URL}  (separate app: python3 -m prototypes.acoustics)\n(Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
