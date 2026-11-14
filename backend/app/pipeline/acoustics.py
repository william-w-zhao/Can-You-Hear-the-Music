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

from app.sources.config import AUDIO, DATA

BANDS = ["125", "500", "2000"]
# Absorption coefficients [125 Hz, 500 Hz, 2 kHz], typical values, with a (low, high) range at 500 Hz.
MATERIALS = {
    "commercial_carpet": {"name": "Commercial carpet", "a": [0.05, 0.20, 0.45], "range": [0.12, 0.30]},
    "carpet_on_pad":     {"name": "Carpet on pad", "a": [0.08, 0.55, 0.70], "range": [0.45, 0.65]},
    "vinyl_tile":        {"name": "Vinyl / tile", "a": [0.02, 0.03, 0.04], "range": [0.02, 0.05]},
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
# Extra absorption from contents, m² sabins per m² of floor [125, 500, 2k].
CONTENTS = {"empty": [0.0, 0.0, 0.0], "built_in": [0.01, 0.02, 0.03], "cabinets": [0.01, 0.02, 0.03],
            "furnished": [0.08, 0.20, 0.25]}
AIR_M_2K = 0.0024          # air attenuation at 2 kHz, 1/m (energy), ~20 C, 50% RH
VERDICTS = [(0.5, "Excellent for calls"), (0.7, "Good for calls"), (1.0, "Noticeable echo"), (99, "Echoey")]


def surfaces(room, mat):
    A, H = room["area_m2"], room["height_m"]
    walls = room["perimeter_m"] * H
    glass = min(mat["glass_m2"], walls * 0.9)
    return [(mat["floor"], A), (mat["ceiling"], A), (mat["walls"], walls - glass), ("glass", glass)]


def rt60(room, mat, contents=None, which=None):
    """RT60 per band. which='low'/'high' swaps the 500 Hz coefficients for the range ends (all bands scaled)."""
    V = room["volume_m3"]
    surf = surfaces(room, mat)
    S = sum(a for _, a in surf)
    out, absorb = [], []
    cont = CONTENTS[contents or mat.get("furnishing", "empty")]
    for b in range(3):
        tot = 0.0
        for m, area in surf:
            M = MATERIALS[m]
            a = M["a"][b]
            if which:
                lo, hi = M["range"]
                a *= (lo if which == "low" else hi) / M["a"][1]
            tot += area * min(a, 0.99)
        tot += cont[b] * room["area_m2"]
        mean = min(tot / S, 0.95)
        air = 4 * AIR_M_2K * V if b == 2 else 0.0
        out.append(0.161 * V / (-S * math.log(1 - mean) + air))
        absorb.append(tot)
    return out, absorb


def verdict(t):
    return next(v for lim, v in VERDICTS if t <= lim)


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
    d = DATA / a.model
    rooms = json.loads((d / "rooms.json").read_text())
    mats = json.loads((d / "materials.json").read_text())
    out = []
    for r in rooms["rooms"]:
        m = mats["rooms"][r["id"]]
        t, absorb = rt60(r, m)
        lo, _ = rt60(r, m, which="high")       # more absorption -> shorter echo
        hi, _ = rt60(r, m, which="low")
        tf, _ = rt60(r, m, contents="furnished")
        mid = t[1]
        out.append({**r, **m, "rt60": [round(v, 2) for v in t], "rt60_range_500": [round(lo[1], 2), round(hi[1], 2)],
                    "rt60_furnished": [round(v, 2) for v in tf], "absorption_500": round(absorb[1], 1),
                    "surface_m2": round(sum(x for _, x in surfaces(r, m)), 1), "verdict": verdict(mid)})
        print(f"  {r['id']:4} {m['type']:24} {r['area_m2']:6.1f} m²  RT60 {t[0]:.2f}/{t[1]:.2f}/{t[2]:.2f} s "
              f"(mid range {lo[1]:.2f}-{hi[1]:.2f})  furnished {tf[1]:.2f} s  → {verdict(mid)}")
    voice = dry_voice()
    res = {"model": a.model, "bands_hz": BANDS, "materials": MATERIALS, "contents": CONTENTS,
           "air_m_2k": AIR_M_2K, "verdicts": VERDICTS, "rooms": out, "floorplan": rooms["floorplan"],
           "segmentation": rooms["method"], "materials_source": mats["labelled_by"],
           "voice": "audio/voice.wav" if voice.exists() else None}
    (d / "acoustics.json").write_text(json.dumps(res, indent=1))
    print(f"Saved {d / 'acoustics.json'}")


if __name__ == "__main__":
    main()
