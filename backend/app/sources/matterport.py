"""Fetch building interiors and scan metadata from the Matterport Model API.

The CoStar kit supplies the scan ID. This module fetches room geometry,
floor-plan images and a representative panorama. The building fetch writes
the metadata to data/<sid>/bundle.json alongside the downloaded images.
"""
import io
import os

import numpy as np
import requests
from PIL import Image

from app.sources.config import secret
from app.sources.imagery import get, save_jpg

MP_API = "https://api.matterport.com/api/models/graph"
SITE = os.environ.get("HACKATHON_SITE", "https://beta-app.matterport.com/2026-princeton-hackathon").rstrip("/")

_session = None


def mp(query, **variables):
    """Run a Matterport Model API query; return `data`."""
    global _session
    if _session is None:
        # Reuse the authenticated session across the metadata, room and panorama queries.
        _session = requests.Session()
        _session.auth = (secret("MATTERPORT_API_KEY"), secret("MATTERPORT_API_TOKEN"))
    r = _session.post(MP_API, json={"query": query, "variables": variables}, timeout=120)
    if r.status_code in (401, 403):
        raise SystemExit(f"Matterport rejected the key (HTTP {r.status_code}).")
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(f"GraphQL error: {body['errors'][0].get('message')}")
    return body["data"]


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
    """Cache scan geometry and images, then return latitude and longitude for the aerial fetch."""
    print("Matterport: basics")
    m = mp(Q_BASICS, id=sid)["model"]
    try:
        m["view"] = mp(Q_VIEW, id=sid)["model"]["view"]
    except Exception:
        m["view"] = None              # not every model has a defurnished view
    bundle["matterport"] = {"basics": m}
    if m.get("image", {}).get("url"):
        bundle["matterport"]["preview_size"] = save_jpg(get(m["image"]["url"]), outdir / "preview.jpg", 1600)

    print("Matterport: rooms, walls, floor plans")
    r = mp(Q_ROOMS, id=sid)["model"]
    # Matterport identifies room boundaries by edge ID. Expand those references
    # into ordered polygons in the scan's local metre coordinates.
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
    # Keep the floor-plan origin and resolution so the room pipeline can
    # convert scan coordinates to pixels on the downloaded images.
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

    print("Matterport: panorama (furnished + defurnished)")
    panos = mp(Q_PANOS, id=sid)["model"]["panoLocations"]
    # Prefer the sweep closest to the center of the largest labeled living room,
    # dining room or kitchen. Use the first sweep when those labels are unavailable.
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
    # A matching sweep ID lets the explorer compare the same viewpoint in both views.
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

    print("Matterport: MatterPak")
    # This query records availability and filenames. The separate pointcloud
    # command fetches the archive URL and extracts cloud.xyz when needed.
    bundle["matterport"]["matterpak"] = mp(Q_MATTERPAK, id=sid)["model"]["bundle"]
    g = m["geolocation"]
    return float(g["lat"]), float(g["long"])


def fetch_site(sid, bundle):
    """Fetch drone and splat catalog metadata from the separate hackathon site."""
    print("Hackathon site: splat + drone catalog")
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
