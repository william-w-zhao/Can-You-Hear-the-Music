#!/usr/bin/env python3
"""
Fetch and cache everything about one Matterport model and its block, for the explorer page.

    python3 fetch_building.py                 # default: zvKHR9DHNjJ, 5836 La Mirada Ave, LA
    python3 fetch_building.py --model <sid>   # any model id from the kit CSVs

Writes data/<sid>/: bundle.json (all records), ortho.png (analysis) + ortho.jpg (page),
osm.json (building outlines with LA County heights), preview.jpg, floorplan images,
pano_equirect.jpg / pano_defurnished.jpg. About 20 MB per model, a few seconds.
Signed Matterport links expire, so images are downloaded rather than linked.
"""
import argparse
import csv
import io
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from common import DATA, KIT, SITE, VEXCEL, Box, dist_m, mp, secret

HALF_M = 170          # clip half-width: 340 m square, enough for neighbours and a reference building
SIZE_PX = 2400        # ~0.14 m per pixel (Vexcel urban is 7.5 cm native)


def log(msg):
    print(msg, flush=True)


def get(url, **kw):
    r = requests.get(url, timeout=120, **kw)
    r.raise_for_status()
    return r.content


def save_jpg(data_or_img, path, max_w=None, quality=86):
    img = data_or_img if isinstance(data_or_img, Image.Image) else Image.open(io.BytesIO(data_or_img))
    img = img.convert("RGB")
    if max_w and img.width > max_w:
        img = img.resize((max_w, round(img.height * max_w / img.width)), Image.LANCZOS)
    img.save(path, quality=quality)
    return img.size


# --------------------------------------------------------------------------- Matterport
Q_BASICS = """query($id: ID!) { model(id: $id) {
  id name description created visibility
  address { address locality administrativeArea postalCode }
  geolocation { lat long }
  generatedDescription { summary }
  propertyClassifications { classification type }
  floors { id label } rooms { id } panoLocations { id }
  image { url }
} }"""

Q_VIEW = """query($id: ID!) { model(id: $id) { view(type: "matterport.model.defurnished") { id } } }"""

Q_ROOMS = """query($id: ID!) { model(id: $id) {
  floors { id label vertices { id position { x y } } edges { id type thickness vertices { id } } }
  rooms { id floor { id } classifications { label confidence } boundary { edges { id } }
          dimensions(units: metric) { areaFloor width depth height } }
  assets { floorplans(provider: "matterport") { format flags url width height resolution origin { x y } } }
  panoLocations { id label position { x y z } }
} }"""

Q_PANOS = """query($id: ID!) { model(id: $id) {
  panoLocations { id label position { x y z } skybox(resolution: "2k") { status children } }
} }"""

Q_MATTERPAK = """query($id: ID!) { model(id: $id) {
  bundle(id: "mp:matterpak") { availability assets { ... on Resource { format status filename } } }
} }"""


def equirect(faces, width=2048):
    """Six skybox faces (0 up, 1-4 around, 5 down) -> equirectangular. Face mapping from the official quickstart."""
    h = width // 2
    lon = (np.arange(width) + 0.5) / width * 2 * np.pi - np.pi
    lat = np.pi / 2 - (np.arange(h) + 0.5) / h * np.pi
    lon, lat = np.meshgrid(lon, lat)
    x, y, z = np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)
    ax, ay, az = np.abs(x), np.abs(y), np.abs(z)
    out = np.zeros((h, width, 3), np.uint8)
    n = faces[0].width
    arrays = [np.asarray(f.convert("RGB")) for f in faces]
    for k, mask, u, v in [
        (1, (az >= ax) & (az >= ay) & (z > 0), x / az, -y / az),
        (2, (ax >= ay) & (ax >= az) & (x > 0), -z / ax, -y / ax),
        (3, (az >= ax) & (az >= ay) & (z < 0), -x / az, -y / az),
        (4, (ax >= ay) & (ax >= az) & (x < 0), z / ax, -y / ax),
        (0, (ay >= ax) & (ay >= az) & (y > 0), x / ay, z / ay),
        (5, (ay >= ax) & (ay >= az) & (y < 0), x / ay, -z / ay),
    ]:
        col = np.clip(((u[mask] + 1) / 2 * n).astype(int), 0, n - 1)
        row = np.clip(((v[mask] + 1) / 2 * n).astype(int), 0, n - 1)
        out[mask] = arrays[k][row, col]
    return Image.fromarray(out)


def polygon_centroid(pts):
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    if abs(a) < 1e-9:
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return cx / (3 * a), cy / (3 * a)


def room_polygons(floors, rooms):
    """Each room's boundary as an ordered polygon of (x, y) metres, chained from its edge loop."""
    vpos, edges = {}, {}
    for fl in floors:
        for v in fl["vertices"]:
            vpos[v["id"]] = (v["position"]["x"], v["position"]["y"])
        for e in fl["edges"]:
            edges[e["id"]] = [v["id"] for v in e["vertices"]]
    out = {}
    for r in rooms:
        segs = [edges[e["id"]] for e in (r.get("boundary") or {}).get("edges", []) if e["id"] in edges]
        if not segs:
            continue
        chain = list(segs.pop(0))
        while segs:
            for i, (a, b) in enumerate(segs):
                if a == chain[-1]:
                    chain.append(b); segs.pop(i); break
                if b == chain[-1]:
                    chain.append(a); segs.pop(i); break
            else:
                break
        out[r["id"]] = [vpos[v] for v in chain if v in vpos]
    return out


def fetch_matterport(sid, outdir, bundle):
    log("Matterport: basics")
    m = mp(Q_BASICS, id=sid)["model"]
    try:
        m["view"] = mp(Q_VIEW, id=sid)["model"]["view"]
    except Exception:
        m["view"] = None              # not every model has a defurnished view
    bundle["matterport"] = {"basics": m}
    if m.get("image", {}).get("url"):
        bundle["matterport"]["preview_size"] = save_jpg(get(m["image"]["url"]), outdir / "preview.jpg", 1600)

    log("Matterport: rooms, walls, floor plans")
    r = mp(Q_ROOMS, id=sid)["model"]
    polys = room_polygons(r["floors"], r["rooms"])
    rooms = []
    for room in r["rooms"]:
        labels = [c["label"] for c in room.get("classifications") or []]
        rooms.append({"id": room["id"], "floor": room["floor"]["id"], "label": labels[0] if labels else None,
                      "dimensions": room.get("dimensions"), "polygon": polys.get(room["id"])})
    walls = []
    for fl in r["floors"]:
        vpos = {v["id"]: (v["position"]["x"], v["position"]["y"]) for v in fl["vertices"]}
        for e in fl["edges"]:
            a, b = (vpos.get(v["id"]) for v in e["vertices"])
            if a and b:
                walls.append({"floor": fl["id"], "type": e["type"], "thickness": e["thickness"], "a": a, "b": b})
    plans = []
    for i, fp in enumerate((r.get("assets") or {}).get("floorplans") or []):
        if fp["format"] != "jpg" or "photogramy" not in (fp.get("flags") or []):
            continue
        name = f"floorplan_{i}.jpg"
        save_jpg(get(fp["url"]), outdir / name)
        plans.append({"file": name, "flags": fp["flags"], "width": fp["width"], "height": fp["height"],
                      "resolution": fp["resolution"], "origin": fp["origin"]})
    bundle["matterport"].update(rooms=rooms, walls=walls, floorplans=plans, panos=r["panoLocations"],
                                floors=[{"id": f["id"], "label": f["label"]} for f in r["floors"]])

    log("Matterport: panorama (furnished + defurnished)")
    panos = mp(Q_PANOS, id=sid)["model"]["panoLocations"]
    living = [x for x in rooms if x["polygon"] and (x["label"] or "") in ("Living Room", "Dining Room", "Kitchen")]
    target = max(living, key=lambda x: (x["dimensions"] or {}).get("areaFloor") or 0) if living else None
    if target:
        cx, cy = polygon_centroid(target["polygon"])
        pano = min(panos, key=lambda p: (p["position"]["x"] - cx) ** 2 + (p["position"]["y"] - cy) ** 2)
    else:
        pano = panos[0]
    faces = [Image.open(io.BytesIO(get(u))) for u in pano["skybox"]["children"]]
    equirect(faces).save(outdir / "pano_equirect.jpg", quality=85)
    info = {"id": pano["id"], "label": pano["label"], "position": pano["position"],
            "room": target["label"] if target else None, "file": "pano_equirect.jpg"}
    view = (m.get("view") or {}).get("id")
    if view:
        try:
            dpanos = mp(Q_PANOS, id=view)["model"]["panoLocations"]
            dp = next((p for p in dpanos if p["id"] == pano["id"]), None)
            if dp and dp["skybox"]["status"] == "available":
                dfaces = [Image.open(io.BytesIO(get(u))) for u in dp["skybox"]["children"]]
                equirect(dfaces).save(outdir / "pano_defurnished.jpg", quality=85)
                info["defurnished_file"] = "pano_defurnished.jpg"
        except Exception as e:
            bundle["errors"].append(f"defurnished pano: {e}")
    bundle["matterport"]["pano"] = info

    log("Matterport: MatterPak")
    bundle["matterport"]["matterpak"] = mp(Q_MATTERPAK, id=sid)["model"]["bundle"]
    g = m["geolocation"]
    return float(g["lat"]), float(g["long"])


# --------------------------------------------------------------------------- Splat site
def fetch_site(sid, bundle):
    log("Hackathon site: splat + drone catalog")
    auth = (secret("HACKATHON_SITE_USER", False), secret("HACKATHON_SITE_PASSWORD", False))
    r = requests.get(f"{SITE}/api/models/{sid}", timeout=60, auth=auth if all(auth) else None)
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        bundle["site"] = {"available": False, "status": r.status_code}
        return
    cat = r.json()
    photos = cat.get("images") or []
    # DJI file names carry the flight time: DJI_YYYYMMDDhhmmss_....
    stamps = sorted(p[4:18] for p in photos if p.startswith("DJI_") and p[4:18].isdigit())
    bundle["site"] = {"available": True, **{k: v for k, v in cat.items() if k != "images"},
                      "drone_photo_count": len(photos), "drone_photo_sample": photos[:5],
                      "drone_flight_start": stamps[0] if stamps else None,
                      "drone_flight_end": stamps[-1] if stamps else None}


# --------------------------------------------------------------------------- Vexcel + OSM
def fetch_vexcel(box, outdir, bundle):
    log("Vexcel: ortho clip")
    t = time.time()
    r = requests.post(f"{VEXCEL}/ortho/extract", headers={"X-API-KEY": secret("VEXCEL_API_KEY")}, timeout=300, json={
        "wkt": box.wkt(), "srid": 4326, "layer": "urban,urban-r,wide-area,urban-g", "crop": "bounding_box",
        "image-format": "png", "destination-dimensions": f"{box.size},{box.size}", "attribution": "false"})
    if r.status_code in (401, 403):
        raise RuntimeError(f"Vexcel answered {r.status_code} (key, or location outside Houston/LA)")
    r.raise_for_status()
    (outdir / "ortho.png").write_bytes(r.content)
    save_jpg(r.content, outdir / "ortho.jpg", 1600, quality=88)
    bundle["vexcel"] = {"box": box.as_dict(), "bytes": len(r.content), "seconds": round(time.time() - t, 1),
                        "layer": "urban,urban-r,wide-area,urban-g", "capture_time": None,
                        "note": "The ortho extract returns no capture date or time."}


def fetch_osm(box, outdir, bundle):
    log("OpenStreetMap: building outlines (LA County heights)")
    q = (f'[out:json][timeout:60];(way["building"]({box.s},{box.w},{box.n},{box.e}););out tags geom;')
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, timeout=120,
                      headers={"User-Agent": "hackathon-sunlight-prototype"})
    r.raise_for_status()
    els = r.json()["elements"]
    (outdir / "osm.json").write_text(json.dumps(els))
    bundle["osm"] = {"buildings": len(els), "with_height": sum(1 for e in els if "height" in e.get("tags", {}))}


# --------------------------------------------------------------------------- CoStar
def find_jsonl(path, ids):
    ids = {str(i) for i in ids}
    found = {}
    with open(path) as fh:
        for line in fh:
            head = line[:40]
            for i in list(ids):
                if f'"id": {i},' in head or f'"id":{i},' in head:
                    found[i] = json.loads(line)
                    ids.discard(i)
            if not ids:
                break
    return found


def fetch_costar(sid, box, bundle):
    log("CoStar kit: records")
    cs = {"listing": None, "features": None, "property": None, "nearby": []}
    with open(KIT / "residential-listings.csv", newline="") as fh:
        res = next((r for r in csv.DictReader(fh) if r["MatterportModelId"] == sid), None)
    with open(KIT / "commercial-properties.csv", newline="") as fh:
        com = next((r for r in csv.DictReader(fh) if r["MatterportModelId"] == sid), None)
    if res:
        lid = res["ListingId"]
        cs["listing"] = find_jsonl(KIT / "data" / "residential-listings.jsonl", [lid]).get(lid)
        cs["features"] = find_jsonl(KIT / "data" / "residential-listing-features.jsonl", [lid]).get(lid)
        cs["match"] = {"kind": "residential", "id": lid, "address": res["Address"]}
    if com:
        pid = com["PropertyId"]
        cs["property"] = find_jsonl(KIT / "data" / "commercial-property.jsonl", [pid]).get(pid)
        cs["match"] = {"kind": "commercial", "id": pid, "address": com["Address"]}
    # Every CoStar commercial property inside the clip: stories/height make them reference buildings.
    with open(KIT / "data" / "commercial-property.jsonl") as fh:
        for line in fh:
            p = json.loads(line)
            a = p.get("primaryAddress") or {}
            la, lo = a.get("latitude"), a.get("longitude")
            if la is None or not (box.s <= la <= box.n and box.w <= lo <= box.e):
                continue
            x, y = box.px(lo, la)
            cs["nearby"].append({
                "id": p["id"], "name": p.get("buildingName"),
                "address": " ".join(str(a.get(k) or "") for k in ("streetNumber", "streetName", "streetType")).strip(),
                "lat": la, "lon": lo, "px": [round(x, 1), round(y, 1)],
                "distance_m": round(dist_m(box.lat, box.lon, la, lo)),
                "stories": p.get("numStoriesAboveGrade"), "height_ft": p.get("buildingHeightInFeet"),
                "year_built": next((e.get("year") for e in p.get("constructionEvents") or [] if e.get("year")), None),
                "property_type": p.get("propertyType"), "rba_sf": p.get("rentableBuildingAreaSquareFeet"),
            })
    cs["nearby"].sort(key=lambda r: r["distance_m"])
    bundle["costar"] = cs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="zvKHR9DHNjJ")
    args = ap.parse_args()
    sid = args.model
    outdir = DATA / sid
    outdir.mkdir(parents=True, exist_ok=True)
    bundle = {"sid": sid, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "errors": []}

    lat, lon = fetch_matterport(sid, outdir, bundle)
    box = Box(lat, lon, HALF_M, SIZE_PX)
    for step in (lambda: fetch_site(sid, bundle), lambda: fetch_vexcel(box, outdir, bundle),
                 lambda: fetch_osm(box, outdir, bundle), lambda: fetch_costar(sid, box, bundle)):
        try:
            step()
        except Exception as e:
            log(f"  ! {e}")
            bundle["errors"].append(str(e))
    (outdir / "bundle.json").write_text(json.dumps(bundle, indent=1, default=str))
    idx = DATA / "index.json"
    models = json.loads(idx.read_text()) if idx.exists() else {}
    models[sid] = bundle["matterport"]["basics"]["name"]
    idx.write_text(json.dumps(models, indent=1))
    log(f"Saved {outdir}  ({len(bundle['errors'])} errors)")


if __name__ == "__main__":
    sys.exit(main())
