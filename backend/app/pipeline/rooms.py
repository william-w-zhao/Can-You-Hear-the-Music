#!/usr/bin/env python3
"""
Split a scan into rooms from its point cloud, when Matterport's own room data is coarse or missing.

1. Ceiling slice (points near the ceiling height) marks what is indoors: outdoors has no ceiling.
2. Wall slice (1.0 m up to just under the ceiling) marks walls, including the wall above each door.
3. Gaps up to door width (~1.3 m) along a wall are bridged, so doorways close rooms off.
4. Rooms = connected indoor areas between walls. Only areas containing a scan position are kept:
   the scanner always stands inside a real room, so glimpses through windows drop out.
5. Windows: room edges where the scanner saw *through* the wall to points outside.

    python3 -m app.pipeline.rooms --model <sid>      # needs data/<sid>/cloud.npy and bundle.json
    -> data/<sid>/rooms.json and data/<sid>/room_sheet.jpg (panorama faces per room, for material labelling)
"""
import argparse
import io
import json

import numpy as np
import requests
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage import measure

from app.pipeline.cache_files import write_json
from app.sources.config import DATA
from app.sources.matterport import mp

RES = 0.05            # grid cell, metres
DOOR_M = 1.3          # widest gap treated as a doorway

Q_SKY = """query($id: ID!) { model(id: $id) { panoLocations { id skybox(resolution: "2k") { children } } } }"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--source", choices=["cloud", "matterport"], default="cloud",
                    help="matterport: use Matterport's own room outlines (when the scan has them) instead of the point cloud")
    a = ap.parse_args()
    d = DATA / a.model
    bundle = json.loads((d / "bundle.json").read_text())
    if a.source == "matterport":
        rooms, fp, method = rooms_from_matterport(bundle)
        return finish(a.model, d, rooms, fp, method, None, None)
    rooms, fp, method, floor_z, ceil_z = rooms_from_cloud(d, bundle)
    return finish(a.model, d, rooms, fp, method, floor_z, ceil_z)


def rooms_from_cloud(d, bundle):
    P = np.load(d / "cloud.npy")
    x, y, z = P[:, 0], P[:, 1], P[:, 2]

    # Floor and ceiling heights: the two big peaks of the height histogram.
    h, e = np.histogram(z, bins=200)
    c = (e[:-1] + e[1:]) / 2
    floor_z = float(c[np.argmax(np.where(c < np.median(z), h, 0))])
    ceil_z = float(c[np.argmax(np.where(c > np.median(z), h, 0))])
    print(f"floor {floor_z:.2f} m, ceiling {ceil_z:.2f} m")

    x0, y0 = x.min(), y.min()
    W, H = int((x.max() - x0) / RES) + 1, int((y.max() - y0) / RES) + 1
    ci, ri = ((x - x0) / RES).astype(int), ((y - y0) / RES).astype(int)

    def grid(m):
        g = np.zeros((H, W), np.int32)
        np.add.at(g, (ri[m], ci[m]), 1)
        return g

    ceil = grid((z > ceil_z - 0.15) & (z < ceil_z + 0.15)) >= 2
    wall = grid((z > floor_z + 1.0) & (z < ceil_z - 0.15)) >= 6
    see = grid((z > floor_z + 0.6) & (z < floor_z + 2.2)) >= 1
    interior = ndimage.binary_fill_holes(ndimage.binary_closing(ceil, iterations=4))
    L = int(DOOR_M / RES)
    walls = wall | ndimage.binary_closing(wall, structure=np.ones((1, L))) | ndimage.binary_closing(wall, structure=np.ones((L, 1)))
    walls = ndimage.binary_dilation(walls, iterations=1)
    lab, n = ndimage.label(interior & ~walls)

    panos = bundle["matterport"]["panos"]
    pano_room = {}
    for p in panos:
        r, cc = int((p["position"]["y"] - y0) / RES), int((p["position"]["x"] - x0) / RES)
        if 0 <= r < H and 0 <= cc < W and lab[r, cc]:
            pano_room.setdefault(int(lab[r, cc]), []).append(p)
    fp = select_floorplan(bundle["matterport"])
    to_px = lambda X, Y: [round((X - fp["origin"]["x"]) * fp["resolution"], 1), round(fp["height"] - (Y - fp["origin"]["y"]) * fp["resolution"], 1)]

    outside = ~interior
    rooms = []
    for k, ps in sorted(pano_room.items(), key=lambda kv: -int((lab == kv[0]).sum())):
        m = lab == k
        area = m.sum() * RES * RES
        if area < 2:
            continue
        zs = z[(lab[ri.clip(0, H - 1), ci.clip(0, W - 1)] == k) & (z > ceil_z - 0.4)]
        height = float(np.median(zs) - floor_z) if zs.size > 50 else ceil_z - floor_z
        # Perimeter from the room outline; walls are shared with neighbours, which is fine for absorption.
        cont = max(measure.find_contours(np.pad(m, 1).astype(float), 0.5), key=len) - 1
        poly = measure.approximate_polygon(cont, tolerance=1.5)
        perim = float(np.sum(np.hypot(*np.diff(poly, axis=0).T))) * RES
        # Window length: edge cells within 0.6 m of space the scanner saw through (outdoors, beyond the wall).
        edge = m & ~ndimage.binary_erosion(m, iterations=1)
        ring = ndimage.binary_dilation(m, iterations=int(1.2 / RES)) & outside & see
        near = ndimage.binary_dilation(ring, iterations=int(0.6 / RES))
        window_len = float((edge & near).sum()) * RES * 0.7      # 0.7: edge cells step diagonally
        pts = [to_px(x0 + (cc + 0.5) * RES, y0 + (rr + 0.5) * RES) for rr, cc in poly]
        cy, cx = ndimage.center_of_mass(m)
        rooms.append({
            "id": f"r{len(rooms) + 1}", "area_m2": round(area, 1), "height_m": round(height, 2),
            "volume_m3": round(area * height, 1), "perimeter_m": round(perim, 1),
            "window_len_m": round(min(window_len, perim), 1), "panos": [p["id"] for p in ps],
            "pano_labels": [p["label"] for p in ps], "polygon_px": pts,
            "center_px": to_px(x0 + (cx + 0.5) * RES, y0 + (cy + 0.5) * RES),
        })
    method = "point-cloud wall slice; doorways bridged up to %.1f m; rooms must contain a scan position" % DOOR_M
    return rooms, fp, method, floor_z, ceil_z


def select_floorplan(scan):
    plans = scan["floorplans"]
    if not plans:
        raise ValueError("Matterport did not provide a floor plan for this scan.")
    return next((plan for plan in plans if plan["flags"] == ["photogramy"]), plans[0])


def rooms_from_matterport(bundle):
    """Rooms straight from Matterport's room outlines and dimensions (scans that have a wall graph)."""
    M = bundle["matterport"]
    fp = select_floorplan(M)
    to_px = lambda X, Y: [round((X - fp["origin"]["x"]) * fp["resolution"], 1), round(fp["height"] - (Y - fp["origin"]["y"]) * fp["resolution"], 1)]
    heights = [r["dimensions"]["height"] for r in M["rooms"] if (r.get("dimensions") or {}).get("height")]
    default_h = float(np.median(heights)) if heights else 2.6
    rooms = []
    for r in M["rooms"]:
        poly, dims = r.get("polygon"), r.get("dimensions") or {}
        if not poly or r.get("label") == "Void" or (dims.get("areaFloor") or 0) < 2:
            continue
        path = measure.points_in_poly
        ps = [p for p in M["panos"] if path([[p["position"]["x"], p["position"]["y"]]], poly)[0]]
        if not ps:
            continue
        hgt = dims.get("height") or default_h
        perim = sum(float(np.hypot(x1 - x0, y1 - y0)) for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]))
        cx, cy = np.mean(poly, axis=0)
        rooms.append({"id": f"r{len(rooms) + 1}", "matterport_label": r["label"], "area_m2": round(dims["areaFloor"], 1),
                      "height_m": round(hgt, 2), "height_measured": bool(dims.get("height")),
                      "volume_m3": round(dims["areaFloor"] * hgt, 1), "perimeter_m": round(perim, 1), "window_len_m": None,
                      "panos": [p["id"] for p in ps], "pano_labels": [p["label"] for p in ps],
                      "polygon_px": [to_px(x, y) for x, y in poly], "center_px": to_px(cx, cy)})
    rooms.sort(key=lambda r: -r["area_m2"])
    for i, r in enumerate(rooms, 1):
        r["id"] = f"r{i}"
    return rooms, fp, "Matterport room outlines and dimensions (wall graph)"


def finish(sid, d, rooms, fp, method, floor_z, ceil_z):
    if not rooms:
        raise ValueError("No usable rooms were found in this scan.")
    print(f"{len(rooms)} rooms: " + ", ".join(f"{r['id']} {r.get('matterport_label', '')} {r['area_m2']} m² ({len(r['panos'])} panos)" for r in rooms))

    # Contact sheet: for each room, its first panorama's ceiling, floor and four walls, for material labelling.
    sky = {p["id"]: (p.get("skybox") or {}).get("children") for p in mp(Q_SKY, id=sid)["model"]["panoLocations"]}
    t = 200
    sheet = Image.new("RGB", (t * 6 + 70, t * len(rooms)), "white")
    dr = ImageDraw.Draw(sheet)
    for i, r in enumerate(rooms):
        faces = next((sky.get(pano) for pano in r["panos"] if len(sky.get(pano) or []) == 6), None)
        r["panorama_available"] = bool(faces)
        if not faces:
            dr.text((75, i * t + t // 2), "Panorama unavailable", fill="black")
            continue
        for j, fi in enumerate([0, 5, 1, 2, 3, 4]):
            im = Image.open(io.BytesIO(requests.get(faces[fi], timeout=60).content)).convert("RGB").resize((t, t))
            sheet.paste(im, (70 + j * t, i * t))
        dr.text((6, i * t + t // 2 - 6), r["id"], fill="black")
    sheet.save(d / "room_sheet.jpg", quality=80)
    out = {"model": sid, "floor_z": floor_z, "ceiling_z": ceil_z, "floorplan": fp, "rooms": rooms, "method": method}
    write_json(d / "rooms.json", out)
    print(f"Saved {d / 'rooms.json'} and room_sheet.jpg (columns: ceiling, floor, 4 walls)")


if __name__ == "__main__":
    main()
