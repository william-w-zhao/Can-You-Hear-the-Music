#!/usr/bin/env python3
"""
Building heights from shadows in a Vexcel ortho, without knowing when the photo was taken.

1. Shadow mask: pixels that are dark and bluish (shadows are lit only by blue skylight).
2. Shadow direction: the compass bearing along which building outlines, shifted outward,
   land on shadow most often. One direction for the whole image, since one sun cast every shadow.
3. Shadow length per building: rotate the image so shadows point right, then for each row of a
   building's outline measure the dark run beyond its leeward edge.
4. Calibration: a CoStar building with a known story count gives tan(sun elevation) = height / shadow.
5. Heights: every other building's height = its shadow length x tan(sun elevation).
6. Validation: compare against LA County's measured heights (in the OpenStreetMap outlines), which
   the estimate never sees. Also report when the sun could have stood there (date/time candidates).

    python3 shadows.py [--model <sid>]      # needs data/<sid>/ from fetch_building.py
"""
import argparse
import json
import math

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

import solar
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))  # shared/common.py
from common import DATA, Box, dist_m

STORY_M = 3.3                 # typical floor-to-floor for mid-rise apartments
STORY_RANGE = (3.0, 3.6)
MAX_SHADOW_M = 60
GAP_PX = 3                    # tolerated lit pixels inside a shadow run
EDGE_GAP_M = 2.5              # lit roof allowed past the outline before the shadow starts (stale/offset outlines, eaves)


def shadow_mask(rgb):
    a = rgb.astype(np.float32)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    bfrac = a[..., 2] / (a.sum(-1) + 1e-6)
    m = ((lum < 62) & (bfrac > 0.37)) | (lum < 38)
    m = ndimage.binary_opening(m, iterations=1)
    return m, lum


def outlines(osm, box):
    out = []
    for el in osm:
        geom = el.get("geometry") or []
        if len(geom) < 4:
            continue
        pts = [box.px(g["lon"], g["lat"]) for g in geom]
        xs, ys = zip(*pts)
        area_px = 0.5 * abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])))
        tags = el.get("tags", {})
        try:
            h = float(tags.get("height")) if tags.get("height") else None
        except ValueError:
            h = None
        out.append({"osm_id": el["id"], "pts": pts, "area_m2": area_px * box.m_per_px ** 2,
                    "cx": sum(xs) / len(xs), "cy": sum(ys) / len(ys), "lacounty_h": h,
                    "start_date": tags.get("start_date"), "levels": tags.get("building:levels")})
    return out


def rasterize(blds, size):
    lab = Image.new("I", (size, size), 0)
    d = ImageDraw.Draw(lab)
    for i, b in enumerate(blds, start=1):
        d.polygon(b["pts"], fill=i)
    return np.asarray(lab, dtype=np.int32)


def shift(mask, dx, dy):
    """Move a boolean mask by (dx, dy) pixels (x right, y down), filling with False."""
    out = np.zeros_like(mask)
    h, w = mask.shape
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    out[yd, xd] = mask[ys, xs]
    return out


def unit(bearing):
    """Compass bearing (0 = north, 90 = east) -> image vector (x right, y down)."""
    r = math.radians(bearing)
    return math.sin(r), -math.cos(r)


def find_direction(S, F, m_per_px):
    """Bearing where outlines shifted outward by 1.5-6 m land on shadow most often."""
    dists_px = [d / m_per_px for d in (1.5, 3.0, 4.5, 6.0)]

    def score(bearing):
        ux, uy = unit(bearing)
        tot = 0.0
        for d in dists_px:
            strip = shift(F, round(d * ux), round(d * uy)) & ~F
            tot += S[strip].mean()
        return tot / len(dists_px)

    coarse = {b: score(b) for b in range(0, 360, 4)}
    best = max(coarse, key=coarse.get)
    fine = {b: score(b) for b in np.arange(best - 4, best + 4.01, 0.5)}
    best = float(max(fine, key=fine.get))
    profile = sorted({**coarse, **{float(k): v for k, v in fine.items()}}.items())
    return best % 360, [[round(b, 1), round(float(s), 4)] for b, s in profile]


def rotate_to(bearing, arrays, size):
    """Resample arrays so the shadow direction points along +x (nearest neighbour)."""
    ux, uy = unit(bearing)
    e1, e2 = np.array([ux, uy]), np.array([-uy, ux])
    n = int(math.ceil(size * math.sqrt(2))) + 2
    c_in, c_out = (size - 1) / 2, (n - 1) / 2
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    ox = c_in + (xx - c_out) * e1[0] + (yy - c_out) * e2[0]
    oy = c_in + (xx - c_out) * e1[1] + (yy - c_out) * e2[1]
    rot = [ndimage.map_coordinates(a, [oy, ox], order=0, cval=0) for a in arrays]
    return rot


def measure_lengths(Sr, Lr, nbld, m_per_px):
    """Per building: shadow run length beyond the leeward edge, row by row (rotated frame)."""
    max_px = int(MAX_SHADOW_M / m_per_px)
    edge_px = int(EDGE_GAP_M / m_per_px)
    slices = ndimage.find_objects(Lr, max_label=nbld)
    res = {}
    for i, sl in enumerate(slices, start=1):
        if sl is None:
            continue
        ys, xs = sl
        runs, blocked = [], 0
        for y in range(ys.start, ys.stop):
            row_lab = Lr[y]
            cols = np.nonzero(row_lab[xs] == i)[0]
            if cols.size == 0:
                continue
            x0 = xs.start + cols.max() + 1        # first pixel past the leeward edge
            seg_s = Sr[y, x0:x0 + max_px]
            seg_l = row_lab[x0:x0 + max_px]
            run, gap, started, hit = 0, 0, False, False
            for k in range(seg_s.size):
                if seg_l[k] != 0 and seg_l[k] != i:
                    hit = True            # shadow lands on another building: length unknown past here
                    break
                if seg_s[k]:
                    run, gap, started = k + 1, 0, True
                else:
                    gap += 1
                    if gap > (GAP_PX if started else edge_px):
                        break
            if hit:
                blocked += 1
            elif started:
                runs.append(run)
            else:
                runs.append(0)
        rows = len(runs) + blocked
        if rows < 6:
            continue
        r = np.array(runs) if runs else np.array([0])
        res[i] = {"rows": rows, "blocked_frac": round(blocked / rows, 2),
                  "shadow_m": round(float(np.percentile(r, 80)) * m_per_px, 2),
                  "shadow_m_median": round(float(np.median(r)) * m_per_px, 2),
                  "lit_frac": round(float((r == 0).mean()), 2)}
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="zvKHR9DHNjJ")
    args = ap.parse_args()
    d = DATA / args.model
    bundle = json.loads((d / "bundle.json").read_text())
    bx = bundle["vexcel"]["box"]
    box = Box(bx["lat"], bx["lon"], bx["half_m"], bx["size_px"])
    mpp = box.m_per_px

    rgb = np.asarray(Image.open(d / "ortho.png").convert("RGB"))
    S, lum = shadow_mask(rgb)
    blds = outlines(json.loads((d / "osm.json").read_text()), box)
    lab = rasterize(blds, box.size)
    F = lab > 0
    for i, b in enumerate(blds, start=1):
        inside = lab == i
        b["roof_shadow_frac"] = round(float(S[inside].mean()), 2) if inside.any() else None

    print("Finding shadow direction …")
    bearing, profile = find_direction(S, F, mpp)
    sun_az = (bearing + 180) % 360
    print(f"  shadows point {bearing:.1f}°  → sun azimuth {sun_az:.1f}°")

    print("Measuring shadow lengths …")
    Sr, Lr = rotate_to(bearing, [S.astype(np.uint8), lab], box.size)
    meas = measure_lengths(Sr.astype(bool), Lr, len(blds), mpp)

    for i, b in enumerate(blds, start=1):
        m = meas.get(i)
        b.update(m or {})
        if not m:
            b["status"] = "too small"
        elif b["roof_shadow_frac"] is not None and b["roof_shadow_frac"] > 0.45:
            b["status"] = "outline mismatch"      # roof mostly dark: stale outline or shaded roof
        elif m["blocked_frac"] > 0.5:
            b["status"] = "shadow on another roof"
        elif m["shadow_m"] < 0.5:
            b["status"] = "no shadow found"
        else:
            b["status"] = "ok"

    # Calibration on CoStar buildings with a story count.
    refs = []
    for c in bundle["costar"]["nearby"]:
        if not c.get("stories") and not c.get("height_ft"):
            continue
        cx, cy = c["px"]
        # lit_frac: share of the outline's leeward edge with no shadow behind it. A high value means the
        # outline doesn't match the roof (e.g. an old house outline on a redeveloped lot).
        parts = [b for b in blds if b["status"] == "ok" and b["area_m2"] > 120 and b["lit_frac"] < 0.5
                 and b["blocked_frac"] < 0.2 and math.hypot(b["cx"] - cx, b["cy"] - cy) * mpp < 35]
        if c.get("height_ft"):
            h, lo, hi = c["height_ft"] * 0.3048, c["height_ft"] * 0.3048 * 0.97, c["height_ft"] * 0.3048 * 1.03
            src = f"{c['height_ft']} ft (CoStar)"
        else:
            h, lo, hi = c["stories"] * STORY_M, c["stories"] * STORY_RANGE[0], c["stories"] * STORY_RANGE[1]
            src = f"{c['stories']} stories × {STORY_M} m (CoStar)"
        entry = {"costar_id": c["id"], "name": c["name"], "height_m": round(h, 1), "height_range": [round(lo, 1), round(hi, 1)],
                 "height_source": src, "px": c["px"], "parts": [b["osm_id"] for b in parts]}
        if parts:
            tallest = max(parts, key=lambda b: b["shadow_m"])
            entry.update(osm_id=tallest["osm_id"], shadow_m=tallest["shadow_m"], tan=h / tallest["shadow_m"],
                         rows=tallest["rows"], usable=True)
        else:
            entry["usable"] = False
            entry["why_not"] = "no matching outline with a clean shadow"
        refs.append(entry)
    usable = [r for r in refs if r["usable"]]
    if not usable:
        raise SystemExit("No usable CoStar reference building in this clip.")
    # Measurement errors mostly shorten shadows (cut off by neighbours, outlines inset from the roof), which
    # inflates tan(elevation). So the reference with the smallest tan is the least truncated one.
    ref = min(usable, key=lambda r: r["tan"])
    next(b for b in blds if b["osm_id"] == ref["osm_id"])["reference"] = ref["name"]
    for r in usable:
        r["elevation"] = round(math.degrees(math.atan(r["tan"])), 1)
    tan = ref["tan"]
    elev = math.degrees(math.atan(tan))
    tan_lo, tan_hi = ref["height_range"][0] / ref["shadow_m"], ref["height_range"][1] / ref["shadow_m"]
    print(f"  reference: {ref['name']}  {ref['height_m']} m / {ref['shadow_m']} m shadow → sun elevation {elev:.1f}°")

    for b in blds:
        if "shadow_m" in b:
            b["est_h"] = round(b["shadow_m"] * tan, 1)
            b["est_range"] = [round(b["shadow_m"] * tan_lo, 1), round(b["shadow_m"] * tan_hi, 1)]

    # Validation against LA County heights (never used above).
    val = [b for b in blds if b["status"] == "ok" and b.get("lacounty_h") and not b.get("reference")]
    est = np.array([b["est_h"] for b in val])
    gt = np.array([b["lacounty_h"] for b in val])
    err = est - gt
    Ls = np.array([b["shadow_m"] for b in val])
    tan_fit = float((Ls * gt).sum() / (Ls ** 2).sum())
    validation = {
        "n": int(len(val)), "mae_m": round(float(np.abs(err).mean()), 2),
        "median_abs_err_m": round(float(np.median(np.abs(err))), 2), "bias_m": round(float(err.mean()), 2),
        "within_1_5m": round(float((np.abs(err) <= 1.5).mean()), 2),
        "pearson_r": round(float(np.corrcoef(est, gt)[0, 1]), 3),
        "best_fit_elevation_deg": round(math.degrees(math.atan(tan_fit)), 1),
        "note": "LA County heights are LiDAR-derived maximum heights, from an older survey than the photo; "
                "pitched roofs cast shorter shadows than their ridge height.",
        "points": [[b["lacounty_h"], b["est_h"], b["osm_id"]] for b in val],
    }
    statuses = {}
    for b in blds:
        statuses[b["status"]] = statuses.get(b["status"], 0) + 1
    print(f"  validation on {validation['n']} buildings: MAE {validation['mae_m']} m, "
          f"median {validation['median_abs_err_m']} m, r = {validation['pearson_r']}, "
          f"best-fit elevation {validation['best_fit_elevation_deg']}° vs calibrated {elev:.1f}°")

    # The target building (the Matterport model's own outline).
    tx, ty = box.px(box.lon, box.lat)
    target = min(blds, key=lambda b: math.hypot(b["cx"] - tx, b["cy"] - ty))

    # Shadow mask overlay for the page (transparent PNG at display size).
    disp = 1600
    over = np.zeros((box.size, box.size, 4), np.uint8)
    over[S] = (40, 110, 255, 120)
    Image.fromarray(over, "RGBA").resize((disp, disp), Image.NEAREST).save(d / "shadow_mask.png", optimize=True)

    k = disp / box.size
    out = {
        "model": args.model, "display_px": disp, "m_per_px": mpp, "display_m_per_px": mpp / k,
        "shadow_bearing": round(bearing, 1), "sun_azimuth": round(sun_az, 1),
        "sun_elevation": round(elev, 1),
        "sun_elevation_range": [round(math.degrees(math.atan(tan_lo)), 1), round(math.degrees(math.atan(tan_hi)), 1)],
        "plausible_noon_elevation": solar.elevation_range(box.lat, box.lon),
        "capture_candidates": solar.matching_times(box.lat, box.lon, sun_az, elev),
        "direction_profile": profile, "reference": ref, "references": refs,
        "validation": validation, "status_counts": statuses, "target_osm_id": target["osm_id"],
        "shadow_pixel_frac": round(float(S.mean()), 3),
        "buildings": [{
            "osm_id": b["osm_id"], "pts": [[round(x * k, 1), round(y * k, 1)] for x, y in b["pts"]],
            "area_m2": round(b["area_m2"], 1), "status": b["status"], "lacounty_h": b["lacounty_h"],
            "start_date": b["start_date"], "roof_shadow_frac": b["roof_shadow_frac"],
            **{key: b.get(key) for key in ("shadow_m", "shadow_m_median", "rows", "blocked_frac", "lit_frac",
                                           "est_h", "est_range", "reference")},
            "lat": round(box.lonlat(b["cx"], b["cy"])[1], 7), "lon": round(box.lonlat(b["cx"], b["cy"])[0], 7),
            "distance_m": round(dist_m(box.lat, box.lon, *reversed(box.lonlat(b["cx"], b["cy"])))),
        } for b in blds],
    }
    (d / "shadows.json").write_text(json.dumps(out))
    print(f"Saved {d / 'shadows.json'}  statuses: {statuses}")
    print(f"  capture candidates: {[c['local'] for c in out['capture_candidates']]}")


if __name__ == "__main__":
    main()
