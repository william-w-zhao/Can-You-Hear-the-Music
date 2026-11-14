#!/usr/bin/env python3
"""
Catalog of every building in the hackathon kit, for the explorer's building picker.

    python3 -m app.sources.costar_kit          # (re)build data/catalog.json and data/kit_offsets.json

One row per Matterport model in residential-listings.csv / commercial-properties.csv, with a short
summary from the kit's JSONL records (price, beds, stories, ...) where a record exists. Byte offsets
into the JSONL files are saved too, so the server can return a model's full CoStar records instantly.
The explorer prototype builds this automatically on first start (about 10 s).
"""
import csv
import json
import time

from app.pipeline.geo import dist_m
from app.sources.config import DATA, KIT

CATALOG = DATA / "catalog.json"
OFFSETS = DATA / "kit_offsets.json"
JSONL = {
    "listing": "residential-listings.jsonl",
    "features": "residential-listing-features.jsonl",
    "property": "commercial-property.jsonl",
}


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
    property_types = json.loads((KIT / "schemas" / "enums.json").read_text()).get("PropertyType", {})
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
            row.update(name=p.get("buildingName"), type=property_types.get(str(p.get("propertyType"))),
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
    print("CoStar kit: records")
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


if __name__ == "__main__":
    build()
