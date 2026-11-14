#!/usr/bin/env python3
"""
Fetch and cache everything about one Matterport model and its block, for the explorer page.

    python3 -m app.pipeline.fetch_building                 # default: zvKHR9DHNjJ, 5836 La Mirada Ave, LA
    python3 -m app.pipeline.fetch_building --model <sid>   # any model id from the kit CSVs

Writes data/<sid>/: bundle.json (all records), ortho.png (analysis) + ortho.jpg (page),
osm.json (building outlines), preview.jpg, floorplan images,
pano_equirect.jpg / pano_defurnished.jpg. About 20 MB per model, a few seconds.
Signed Matterport links expire, so images are downloaded rather than linked.
"""
import argparse
import json
import sys
import time

from app.pipeline.geo import Box
from app.sources.config import DATA
from app.sources.costar_kit import fetch_costar
from app.sources.matterport import fetch_matterport, fetch_site
from app.sources.osm import fetch_osm
from app.sources.vexcel import fetch_vexcel

HALF_M = 170          # clip half-width: 340 m square, enough for neighbours and a reference building
SIZE_PX = 2400        # ~0.14 m per pixel (Vexcel urban is 7.5 cm native)


def log(msg):
    print(msg, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="zvKHR9DHNjJ")
    args = ap.parse_args()
    sid = args.model
    outdir = DATA / sid
    outdir.mkdir(parents=True, exist_ok=True)
    bundle = {"sid": sid, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "errors": []}

    # Matterport supplies the scan coordinates. Reuse one bounding box for the
    # aerial image, OpenStreetMap outlines and nearby CoStar properties so they align.
    lat, lon = fetch_matterport(sid, outdir, bundle)
    box = Box(lat, lon, HALF_M, SIZE_PX)
    for step in (lambda: fetch_site(sid, bundle), lambda: fetch_vexcel(box, outdir, bundle),
                 lambda: fetch_osm(box, outdir, bundle), lambda: fetch_costar(sid, box, bundle)):
        try:
            step()
        except Exception as e:
            log(f"  ! {e}")
            bundle["errors"].append(str(e))
    # Keep source metadata together while storing the actual images beside the JSON.
    (outdir / "bundle.json").write_text(json.dumps(bundle, indent=1, default=str))
    idx = DATA / "index.json"
    models = json.loads(idx.read_text()) if idx.exists() else {}
    models[sid] = bundle["matterport"]["basics"]["name"]
    idx.write_text(json.dumps(models, indent=1))
    log(f"Saved {outdir}  ({len(bundle['errors'])} errors)")


if __name__ == "__main__":
    sys.exit(main())
