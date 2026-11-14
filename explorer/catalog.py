#!/usr/bin/env python3
"""
Catalog of every building in the hackathon kit, for the explorer's building picker.

    python3 catalog.py          # (re)build data/catalog.json and data/kit_offsets.json

One row per Matterport model in residential-listings.csv / commercial-properties.csv, with a short
summary from the kit's JSONL records (price, beds, stories, ...) where a record exists. Byte offsets
into the JSONL files are saved too, so the server can return a model's full CoStar records instantly.
serve.py builds this automatically on first start (about 10 s).
"""
import csv
import json
import time

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))  # shared/common.py
from common import DATA, KIT

CATALOG = DATA / "catalog.json"
OFFSETS = DATA / "kit_offsets.json"
JSONL = {
    "listing": "residential-listings.jsonl",
    "features": "residential-listing-features.jsonl",
    "property": "commercial-property.jsonl",
}
PROPERTY_TYPE = json.loads((KIT / "schemas" / "enums.json").read_text()).get("PropertyType", {})


def scan(name, wanted):
    """{id: (offset, record)} for the records whose top-level id is in `wanted`."""
    out = {}
    with open(KIT / "data" / name, "rb") as fh:
        while True:
            off = fh.tell()
            line = fh.readline()
            if not line:
                break
            head = line[:40].decode("utf-8", "ignore")
            i = head.split('"id":', 1)[1].split(",", 1)[0].strip() if '"id":' in head else None
            if i in wanted:
                out[i] = (off, json.loads(line))
    return out


def build():
    t = time.time()
    with open(KIT / "residential-listings.csv", newline="") as fh:
        res = list(csv.DictReader(fh))
    with open(KIT / "commercial-properties.csv", newline="") as fh:
        com = list(csv.DictReader(fh))

    listings = scan(JSONL["listing"], {r["ListingId"] for r in res})
    features = scan(JSONL["features"], {r["ListingId"] for r in res})
    props = scan(JSONL["property"], {r["PropertyId"] for r in com})

    rows, offsets = {}, {}
    for r in res:
        sid, lid = r["MatterportModelId"], r["ListingId"]
        row = {"sid": sid, "kind": "residential", "costar_id": lid, "address": r["Address"],
               "city": r["City"].title(), "state": r["State"]}
        if lid in listings:
            off, L = listings[lid]
            P = L.get("property") or {}
            a = P.get("address") or {}
            row.update(price=L.get("currentPrice"), beds=P.get("bedsMax"), baths=P.get("bathsMax"),
                       sqft=P.get("sqftMax"), year=P.get("yearBuilt"), stories=P.get("stories"),
                       lat=a.get("latitude"), lon=a.get("longitude"))
            offsets.setdefault(sid, {})["listing"] = off
        if lid in features:
            offsets.setdefault(sid, {})["features"] = features[lid][0]
        rows[sid] = row
    for r in com:
        sid, pid = r["MatterportModelId"], r["PropertyId"]
        row = {"sid": sid, "kind": "commercial", "costar_id": pid, "address": r["Address"],
               "city": r["City"].title(), "state": r["State"]}
        if pid in props:
            off, p = props[pid]
            a = p.get("primaryAddress") or {}
            row.update(name=p.get("buildingName"), type=PROPERTY_TYPE.get(str(p.get("propertyType"))),
                       stories=p.get("numStoriesAboveGrade"), sqft=p.get("rentableBuildingAreaSquareFeet"),
                       year=next((e.get("year") for e in p.get("constructionEvents") or [] if e.get("year")), None),
                       lat=a.get("latitude"), lon=a.get("longitude"))
            offsets.setdefault(sid, {})["property"] = off
        if sid in rows:   # a model in both lists: keep the residential row, note the property
            rows[sid]["also_commercial"] = pid
        else:
            rows[sid] = row

    DATA.mkdir(exist_ok=True)
    out = [{k: v for k, v in row.items() if v is not None} for row in rows.values()]
    CATALOG.write_text(json.dumps(out, separators=(",", ":")))
    OFFSETS.write_text(json.dumps(offsets, separators=(",", ":")))
    print(f"Catalog: {len(out)} models, {len(offsets)} with CoStar records ({time.time() - t:.1f} s)")
    return out, offsets


def load():
    if not CATALOG.exists() or not OFFSETS.exists():
        return build()
    return json.loads(CATALOG.read_text()), json.loads(OFFSETS.read_text())


def kit_records(sid, offsets):
    """Full CoStar records for one model, read straight from the JSONL at the saved offsets."""
    out = {}
    for key, off in (offsets.get(sid) or {}).items():
        with open(KIT / "data" / JSONL[key], "rb") as fh:
            fh.seek(off)
            out[key] = json.loads(fh.readline())
    return out


if __name__ == "__main__":
    build()
