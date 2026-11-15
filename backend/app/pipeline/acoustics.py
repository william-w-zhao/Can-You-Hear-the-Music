#!/usr/bin/env python3
"""
Echo time (RT60) per room from scanned geometry + materials labelled from the panoramas.

    python3 -m app.pipeline.acoustics --model <sid>     # needs rooms.json (app.pipeline.rooms) and materials.json
    -> data/<sid>/acoustics.json, plus audio/voice.wav (a dry voice clip for the page's listening demo)

Eyring's formula per band (125 Hz, 500 Hz, 2 kHz), with air absorption at 2 kHz:
    RT60 = 0.161 V / ( -S ln(1 - mean absorption) + 4 m V )
Coefficients are typical published values; each material has a low/high range, which becomes the
RT60 range shown on the page. Wall area = perimeter x height (walls shared with a neighbour count once
per room, as each room sees its own side).
"""
import argparse
import json
import math
import subprocess

from app.pipeline.cache_files import write_json
from app.sources.config import AUDIO, DATA

BANDS = ["125", "500", "2000"]
# Absorption coefficients [125 Hz, 500 Hz, 2 kHz], typical values, with a (low, high) range at 500 Hz.
MATERIALS = {
    "commercial_carpet": {"name": "Commercial carpet", "a": [0.05, 0.20, 0.45], "range": [0.12, 0.30]},
    "carpet_on_pad":     {"name": "Carpet on pad", "a": [0.08, 0.55, 0.70], "range": [0.45, 0.65]},
    "vinyl_tile":        {"name": "Vinyl", "a": [0.02, 0.03, 0.04], "range": [0.02, 0.05]},
    "ceramic_tile":      {"name": "Ceramic tile", "a": [0.01, 0.01, 0.02], "range": [0.01, 0.02]},
    "wood_floor":        {"name": "Wood floor", "a": [0.15, 0.10, 0.06], "range": [0.07, 0.12]},
    "concrete":          {"name": "Concrete", "a": [0.01, 0.02, 0.02], "range": [0.01, 0.03]},
    "acoustic_tile":     {"name": "Acoustic ceiling tile", "a": [0.35, 0.65, 0.80], "range": [0.50, 0.80]},
    "drywall_ceiling":   {"name": "Drywall ceiling", "a": [0.25, 0.05, 0.07], "range": [0.04, 0.08]},
    "exposed_concrete":  {"name": "Exposed concrete deck", "a": [0.01, 0.02, 0.02], "range": [0.01, 0.03]},
    "drywall":           {"name": "Drywall on studs", "a": [0.28, 0.05, 0.07], "range": [0.04, 0.10]},
    "plaster":           {"name": "Plaster", "a": [0.14, 0.06, 0.04], "range": [0.03, 0.08]},
    "brick":             {"name": "Brick", "a": [0.03, 0.03, 0.05], "range": [0.02, 0.05]},
    "glass":             {"name": "Glass", "a": [0.35, 0.18, 0.07], "range": [0.10, 0.25]},
    "acoustic_panel":    {"name": "Acoustic wall panel", "a": [0.30, 0.90, 0.95], "range": [0.80, 1.00]},
}
# Wall coverings measured from the room photos (share of wall area), not choices in the material menus.
COVERINGS = {
    "cabinetry": {"name": "Wood cabinetry", "a": [0.15, 0.10, 0.07], "range": [0.07, 0.14]},
    "shelving":  {"name": "Filled shelving", "a": [0.30, 0.40, 0.45], "range": [0.30, 0.50]},
    "rug":       {"name": "Area rug", "a": [0.05, 0.25, 0.45], "range": [0.15, 0.35]},
}
CARPETED = {"commercial_carpet", "carpet_on_pad"}
TYPICAL_RUG_SHARE = {"bath": 0.10}             # a rug seen only from the side: a bath mat, else a typical rug
DEFAULT_RUG_SHARE = 0.20


def rug_share(room_type, coverage):
    """Floor share under rugs: measured in the floor view, else typical for the room when a rug was seen."""
    if not coverage or not coverage.get("rug_seen", coverage.get("rug")):
        return 0.0
    typical = next((share for key, share in TYPICAL_RUG_SHARE.items() if key in (room_type or "").lower()),
                   DEFAULT_RUG_SHARE)
    return min(MAX_COVERAGE, max(float(coverage.get("rug") or 0), typical))
MAX_COVERAGE = 0.6
# Extra absorption from contents, m² sabins per m² of floor [125, 500, 2k].
CONTENTS = {"empty": [0.0, 0.0, 0.0], "built_in": [0.01, 0.02, 0.03], "cabinets": [0.01, 0.02, 0.03],
            "furnished": [0.08, 0.20, 0.25]}
AIR_M_2K = 0.0024          # air attenuation at 2 kHz, 1/m (energy), ~20 C, 50% RH
VERDICTS = [(0.5, "Excellent for calls"), (0.7, "Good for calls"), (1.0, "Noticeable echo"), (99, "Echoey")]


def surfaces(room, mat):
    A, H = room["area_m2"], room["height_m"]
    walls = room["perimeter_m"] * H
    glass = min(mat["glass_m2"], walls * 0.9)
    opaque = walls - glass
    panels = mat.get("wall_panel_m2", 0)
    if not math.isfinite(panels) or not 0 <= panels <= opaque + 1e-9:
        raise ValueError(f"Wall panel area must be between 0 and the available opaque wall area ({opaque:.2f} m²).")
    panels = min(panels, opaque)
    bare = opaque - panels
    # Cabinetry and shelving seen in the photos replace that share of the bare wall.
    coverage = {key: max(0.0, float(share)) for key, share in (mat.get("wall_coverage") or {}).items()
                if key in COVERINGS}
    scale = min(1.0, MAX_COVERAGE / sum(coverage.values())) if sum(coverage.values()) > 0 else 1.0
    covered = [(key, key, bare * share * scale) for key, share in coverage.items() if share > 0]
    # A rug seen in the photos covers that share of a hard floor (not of a carpeted one).
    rug = 0.0 if mat["floor"] in CARPETED else rug_share(mat.get("type") or room.get("type"), mat.get("floor_coverage"))
    floor = [("floor", mat["floor"], A * (1 - rug))] + ([("rug", "rug", A * rug)] if rug else [])
    return [
        *floor, ("ceiling", mat["ceiling"], A),
        ("walls", mat["walls"], bare - sum(area for _, _, area in covered)),
        ("glass", "glass", glass), ("wall_panels", "acoustic_panel", panels), *covered,
    ]


def rt60(room, mat, contents=None, which=None, *, absorption=None):
    """RT60 per band, with optional fixed coefficients keyed by surface and band in Hz.

    which='low'/'high' varies the material table coefficients. Explicit coefficients stay fixed.
    """
    V = room["volume_m3"]
    surf = surfaces(room, mat)
    S = sum(area for _, _, area in surf)
    absorption = absorption or {}
    surface_keys = {key for key, _, _ in surf}
    for surface, bands in absorption.items():
        if surface not in surface_keys or not isinstance(bands, dict) or bands.keys() - set(BANDS):
            raise ValueError(f"Unknown absorption surface or frequency: {surface}")
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in bands.values()):
            raise ValueError(f"Absorption coefficients for {surface} must be between 0 and 1.")
    out, absorb = [], []
    cont = CONTENTS[contents or mat.get("furnishing", "empty")]
    for b in range(3):
        tot = 0.0
        for surface, m, area in surf:
            fixed = absorption.get(surface, {}).get(BANDS[b])
            M = MATERIALS.get(m) or COVERINGS[m]
            a = M["a"][b]
            if fixed is not None:
                a = fixed
            elif which:
                lo, hi = M["range"]
                a *= (lo if which == "low" else hi) / M["a"][1]
            tot += area * min(a, 0.99)
        tot += cont[b] * room["area_m2"]
        mean = min(tot / S, 0.95)
        air = 4 * AIR_M_2K * V if b == 2 else 0.0
        loss = -S * math.log1p(-mean) + air
        out.append(0.161 * V / loss if loss else math.inf)
        absorb.append(tot)
    return out, absorb


def verdict(t):
    return next((v for lim, v in VERDICTS if t <= lim), VERDICTS[-1][1])


def room_acoustics(room, materials):
    """Calculate the metrics stored in the cache and displayed for what-ifs."""
    times, absorption = rt60(room, materials)
    low, _ = rt60(room, materials, which="high")
    high, _ = rt60(room, materials, which="low")
    furnished, _ = rt60(room, materials, contents="furnished")
    return {
        "rt60": [round(value, 2) for value in times],
        "rt60_range_500": [round(low[1], 2), round(high[1], 2)],
        "rt60_furnished": [round(value, 2) for value in furnished],
        "absorption_500": round(absorption[1], 1),
        "surface_m2": round(sum(area for _, _, area in surfaces(room, materials)), 1),
        "verdict": verdict(times[1]),
    }


def dry_voice():
    """A dry (echo-free) voice clip from macOS text-to-speech, for the listening demo."""
    out = AUDIO / "voice.wav"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    text = ("Hi, thanks for joining the call. Can everyone hear me clearly? "
            "Let's walk through the quarterly numbers, then open it up for questions.")
    try:
        subprocess.run(["say", "-o", str(out), "--data-format=LEI16@22050", text], check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(f"  (no macOS 'say': drop any short dry voice recording at {out})")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    a = ap.parse_args()
    analyse_acoustics(a.model, DATA / a.model)


def analyse_acoustics(sid, d):
    rooms = json.loads((d / "rooms.json").read_text())
    mats = json.loads((d / "materials.json").read_text())
    out = []
    vision = json.loads((d / "vision.json").read_text()) if (d / "vision.json").is_file() else {}
    evidence = vision.get("indoor", {}).get("rooms", {})
    for r in rooms["rooms"]:
        m = mats["rooms"][r["id"]]
        seen = evidence.get(r["id"], {}).get("wall_coverage") or {}
        coverage = {"cabinetry": seen.get("cabinet", 0), "shelving": seen.get("bookshelf", 0)}
        if any(coverage.values()):
            m = {**m, "wall_coverage": coverage}
        rug = evidence.get(r["id"], {}).get("floor_coverage") or {}
        if rug.get("rug_seen"):
            m = {**m, "floor_coverage": {"rug": rug.get("rug", 0), "rug_seen": True}}
        metrics = room_acoustics(r, m)
        out.append({**r, **m, **metrics})
        t = metrics["rt60"]
        lo, hi = metrics["rt60_range_500"]
        tf = metrics["rt60_furnished"]
        print(f"  {r['id']:4} {m['type']:24} {r['area_m2']:6.1f} m²  RT60 {t[0]:.2f}/{t[1]:.2f}/{t[2]:.2f} s "
              f"(mid range {lo:.2f}-{hi:.2f})  furnished {tf[1]:.2f} s  → {metrics['verdict']}")
    voice = dry_voice()
    res = {"model": sid, "bands_hz": BANDS, "materials": MATERIALS, "contents": CONTENTS,
           "air_m_2k": AIR_M_2K, "verdicts": VERDICTS, "rooms": out, "floorplan": rooms["floorplan"],
           "segmentation": rooms["method"], "materials_source": mats["labelled_by"],
           "voice": "audio/voice.wav" if voice.exists() else None}
    write_json(d / "acoustics.json", res)
    print(f"Saved {d / 'acoustics.json'}")


if __name__ == "__main__":
    main()
