"""OpenStreetMap building outlines for the aerial clip."""
import json

import requests


def fetch_osm(box, outdir, bundle):
    print("OpenStreetMap: building outlines (LA County heights)")
    q = (f'[out:json][timeout:60];(way["building"]({box.s},{box.w},{box.n},{box.e}););out tags geom;')
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, timeout=120,
                      headers={"User-Agent": "hackathon-sunlight-prototype"})
    r.raise_for_status()
    els = r.json()["elements"]
    (outdir / "osm.json").write_text(json.dumps(els))
    bundle["osm"] = {"buildings": len(els), "with_height": sum(1 for e in els if "height" in e.get("tags", {}))}
