#!/usr/bin/env python3
"""
Key check for Can You Hear the Music (HackPrinceton 2026, CoStar track).

Tests each key with the smallest real call, using the same endpoints and auth as
CoStar/Matterport's official quickstart:

  1. Matterport Model API   MATTERPORT_API_KEY + MATTERPORT_API_TOKEN (HTTP basic auth)
  2. Vexcel ortho imagery   VEXCEL_API_KEY (X-API-KEY header)
  3. CoStar data kit        local files in ../costar-hackathon-kit (no API key; joined by model id)
  4. Hackathon splat site   no key (optional HACKATHON_SITE_USER / _PASSWORD)

The Showcase SDK key (MATTERPORT_SDK_KEY) only works in a browser: run serve.py for that.

Usage:
    cp .env.example .env    # then fill in your values
    python3 test_keys.py                 # default model zvKHR9DHNjJ (5836 La Mirada Ave, LA)
    python3 test_keys.py --model <sid>   # any model id from the kit's CSVs

Needs only `requests` (pip install requests). Keys are never printed.
"""
import argparse
import csv
import json
import math
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

HERE = Path(__file__).resolve().parent
KIT = HERE.parent / "costar-hackathon-kit"
OUT = HERE / "out"
MP_API = "https://api.matterport.com/api/models/graph"  # production only
VEXCEL = "https://api.vexcelgroup.com/v2"
SITE = os.environ.get("HACKATHON_SITE", "https://beta-app.matterport.com/2026-princeton-hackathon").rstrip("/")
DEFAULT_MODEL = "zvKHR9DHNjJ"

GREEN, RED, YELLOW, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
results = []


def load_env():
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def secret(name):
    v = os.environ.get(name, "").strip()
    return v or None


def mask(v):
    return f"set ({len(v)} chars, ends …{v[-3:]})" if v else "NOT SET"


def report(name, ok, detail):
    tag = f"{GREEN}PASS{END}" if ok is True else f"{RED}FAIL{END}" if ok is False else f"{YELLOW}SKIP{END}"
    print(f"  [{tag}] {name}: {detail}")
    results.append((name, ok))


def section(title):
    print(f"\n{title}\n" + "-" * len(title))


# --------------------------------------------------------------------------- Matterport
def mp_graph(session, query, **variables):
    r = session.post(MP_API, json={"query": query, "variables": variables}, timeout=60)
    if r.status_code in (401, 403):
        raise RuntimeError(f"HTTP {r.status_code}: key rejected. Key = user name, token = password; production host only.")
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        e = body["errors"][0]
        raise RuntimeError(f"GraphQL error: {e.get('message')} ({(e.get('extensions') or {}).get('code', '')})")
    return body["data"]


def test_matterport(model):
    section("1. Matterport Model API")
    key, token = secret("MATTERPORT_API_KEY"), secret("MATTERPORT_API_TOKEN")
    print(f"  {DIM}MATTERPORT_API_KEY {mask(key)} · MATTERPORT_API_TOKEN {mask(token)}{END}")
    if not (key and token):
        report("Model API", False, "set MATTERPORT_API_KEY and MATTERPORT_API_TOKEN in .env")
        return None
    s = requests.Session()
    s.auth = (key, token)

    t = time.time()
    try:
        d = mp_graph(s, "{ rootFolder { name modelCountSummary(includeModelsInSubfolders: true) } }")
        f = d["rootFolder"]
        report("Auth + folder access", True, f"'{f['name']}' holds {f['modelCountSummary']:,} models ({time.time()-t:.1f}s)")
    except Exception as e:
        report("Auth + folder access", False, str(e))
        return None

    info = None
    try:
        d = mp_graph(s, """query($id: ID!) { model(id: $id) {
            id name visibility address { address } geolocation { lat long }
            floors { id } rooms { id } panoLocations { id } } }""", id=model)
        m = d["model"]
        geo = m.get("geolocation") or {}
        info = {"lat": float(geo["lat"]), "lon": float(geo["long"])} if geo.get("lat") else None
        report("Model basics", True,
               f"{m['name']} ({m['visibility']}) · {len(m['floors'])} floor(s), {len(m['rooms'])} rooms, "
               f"{len(m['panoLocations'])} panos · lat/lon {geo.get('lat')}, {geo.get('long')}")
    except Exception as e:
        report("Model basics", False, str(e))
        return None

    # Check that the scan exposes the room and wall geometry used by the explorer.
    try:
        d = mp_graph(s, """query($id: ID!) { model(id: $id) {
            floors { vertices { id } edges { id type } }
            rooms { classifications { label } dimensions(units: metric) { areaFloor height } } } }""", id=model)
        edges = [e for fl in d["model"]["floors"] for e in fl["edges"]]
        types = sorted({e["type"] for e in edges})
        labels = sorted({c["label"] for r in d["model"]["rooms"] for c in (r["classifications"] or [])})
        report("Rooms + wall graph", True, f"{len(edges)} edges (types: {', '.join(types)}); rooms: {', '.join(labels[:8])}")
    except Exception as e:
        report("Rooms + wall graph", False, str(e))

    try:
        d = mp_graph(s, """query($id: ID!) { model(id: $id) {
            panoLocations { skybox(resolution: "2k") { status children } } } }""", id=model)
        pano = d["model"]["panoLocations"][0]["skybox"]
        OUT.mkdir(exist_ok=True)
        img = requests.get(pano["children"][1], timeout=60)
        img.raise_for_status()
        (OUT / "matterport_skybox_face1.jpg").write_bytes(img.content)
        report("Panorama download", True, f"skybox {pano['status']}, saved out/matterport_skybox_face1.jpg ({len(img.content)//1024} KB)")
    except Exception as e:
        report("Panorama download", False, str(e))

    try:
        d = mp_graph(s, """query($id: ID!) { model(id: $id) {
            bundle(id: "mp:matterpak") { availability assets { ... on Resource { format status filename } } } } }""", id=model)
        b = d["model"]["bundle"]
        a = (b.get("assets") or [{}])[0]
        report("MatterPak (mesh/point cloud)", True, f"{b['availability']} · {a.get('filename')} ({a.get('status')}); not downloaded")
    except Exception as e:
        report("MatterPak (mesh/point cloud)", False, str(e))
    return info


# --------------------------------------------------------------------------- Vexcel
def square_wkt(lat, lon, half_m):
    m_per_deg = 111_320
    dlat, dlon = half_m / m_per_deg, half_m / (m_per_deg * math.cos(math.radians(lat)))
    w, e, s, n = lon - dlon, lon + dlon, lat - dlat, lat + dlat
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


def test_vexcel(latlon):
    section("2. Vexcel aerial imagery")
    key = secret("VEXCEL_API_KEY")
    print(f"  {DIM}VEXCEL_API_KEY {mask(key)}{END}")
    if not key:
        report("Ortho extract", False, "set VEXCEL_API_KEY in .env")
        return
    lat, lon = (latlon["lat"], latlon["lon"]) if latlon else (34.0934917, -118.3171)
    t = time.time()
    try:
        r = requests.post(f"{VEXCEL}/ortho/extract", headers={"X-API-KEY": key}, timeout=120, json={
            "wkt": square_wkt(lat, lon, 70), "srid": 4326, "layer": "urban,urban-r,wide-area,urban-g",
            "crop": "bounding_box", "image-format": "jpeg", "destination-dimensions": "1000,1000",
            "attribution": "false"})
    except Exception as e:
        report("Ortho extract", False, str(e))
        return
    if r.status_code == 401:
        report("Ortho extract", False, "401: key rejected (use the api_key from the Vexcel card)")
    elif r.status_code == 403:
        report("Ortho extract", False, f"403 at {lat},{lon}: keys only cover Houston and Los Angeles")
    elif not r.ok:
        report("Ortho extract", False, f"HTTP {r.status_code}: {r.text[:200]}")
    elif not r.headers.get("content-type", "").startswith("image"):
        report("Ortho extract", False, f"expected an image, got {r.headers.get('content-type')}: {r.text[:200]}")
    else:
        OUT.mkdir(exist_ok=True)
        (OUT / "vexcel_ortho.jpg").write_bytes(r.content)
        report("Ortho extract", True, f"140 m square around {lat:.5f},{lon:.5f} → out/vexcel_ortho.jpg "
                                      f"({len(r.content)//1024} KB, {time.time()-t:.1f}s)")


# --------------------------------------------------------------------------- CoStar kit
def test_costar(model):
    section("3. CoStar data kit (local files)")
    if not KIT.exists():
        report("Kit folder", False, f"not found at {KIT}")
        return
    hit = None
    for fname, key_col, kind in (("commercial-properties.csv", "PropertyId", "commercial"),
                                 ("residential-listings.csv", "ListingId", "residential")):
        with open(KIT / fname, newline="") as fh:
            rows = list(csv.DictReader(fh))
        match = next((r for r in rows if r["MatterportModelId"] == model), None)
        if match and not hit:
            hit = (kind, match[key_col], match.get("Address"))
        report(fname, True, f"{len(rows):,} rows")
    if not hit:
        report("Model → CoStar join", None, f"{model} not in either starter CSV (pick a sid from them to test the join)")
        return
    kind, rid, addr = hit
    jsonl = KIT / "data" / ("commercial-property.jsonl" if kind == "commercial" else "residential-listings.jsonl")
    rec = None
    with open(jsonl) as fh:
        for line in fh:
            if f'"id": {rid}' in line or f'"id":{rid}' in line:
                r = json.loads(line)
                if str(r.get("id")) == str(rid):
                    rec = r
                    break
    if not rec:
        report("Model → CoStar join", False, f"{kind} id {rid} not found in {jsonl.name}")
        return
    if kind == "commercial":
        extra = f"stories {rec.get('numStoriesAboveGrade')}, height {rec.get('buildingHeightInFeet')} ft"
    else:
        p = rec.get("property") or {}
        extra = f"keys: {', '.join(list(p)[:6])}…"
    report("Model → CoStar join", True, f"{kind} {rid} · {addr} · {extra}")


# --------------------------------------------------------------------------- Splat site
def test_site(model):
    section("4. Hackathon site (splats + drone photos)")
    auth = (secret("HACKATHON_SITE_USER"), secret("HACKATHON_SITE_PASSWORD"))
    auth = auth if all(auth) else None
    try:
        r = requests.get(f"{SITE}/api/models/{model}", timeout=30, auth=auth)
    except Exception as e:
        report("Model listing", False, str(e))
        return
    if r.status_code == 401:
        report("Model listing", False, "401: set HACKATHON_SITE_USER / HACKATHON_SITE_PASSWORD")
    elif r.status_code == 404:
        report("Model listing", None, f"{model} has no splat (only 232 models do)")
    elif r.ok:
        try:
            body = r.json()
            summary = ", ".join(f"{k}: {len(v) if isinstance(v, list) else v}" for k, v in list(body.items())[:5])
        except ValueError:
            summary = r.text[:120]
        report("Model listing", True, summary)
    else:
        report("Model listing", False, f"HTTP {r.status_code}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_MODEL, help="Matterport model id (sid)")
    ap.add_argument("--only", choices=["matterport", "vexcel", "costar", "site"], help="run one test")
    args = ap.parse_args()
    load_env()
    print(f"Key check · model {args.model}")
    latlon = None
    if args.only in (None, "matterport", "vexcel"):
        latlon = test_matterport(args.model) if args.only != "vexcel" else None
    if args.only in (None, "vexcel"):
        test_vexcel(latlon)
    if args.only in (None, "costar"):
        test_costar(args.model)
    if args.only in (None, "site"):
        test_site(args.model)
    print(f"\nShowcase SDK key: run `python3 serve.py` and open http://localhost:8765\n")
    failed = [n for n, ok in results if ok is False]
    print(f"{GREEN if not failed else RED}{len([1 for _, ok in results if ok])} passed, {len(failed)} failed{END}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
