# Building explorer

Explore Matterport scans, CoStar property records and Vexcel aerial imagery on one local page.

Run from `backend/` with the backend Python environment active:

```bash
python3 -m app.pipeline.fetch_building                 # cache Matterport, Vexcel, CoStar, drone catalog, OpenStreetMap outlines
python3 -m prototypes.explorer                         # http://localhost:8765  (SDK key check at /keys)
```

The room acoustics app is separate (http://localhost:8765/acoustics redirects to it). Both apps
read and write the same cache in `<project>/data/<sid>/`.

The page lists **every building in the kit** (5,099 buildings, 14,933 Matterport scans) in a searchable
sidebar: filter by residential/commercial and city, and sort by price, size, stories or year. Pick a building to
see its CoStar records at once. A building with several scans (suites or units) gets a scan picker. Scans
that are not downloaded yet have a **Download scan, rooms & aerial data** button, which runs the building download
for that model. Once a scan is downloaded, the **Rooms** section lets you pick any room on the plan, in
the chips or in the table to see its area, dimensions, ceiling, perimeter, walls and scan positions.
`?m=<sid>&room=<id>` links straight to a building and room.

Use `--model <sid>` on the download command for another model (any id in the kit CSVs). Keys come from
`<project>/.env` or `key-check/.env`. Needs `requests numpy pillow`.

## Files

| File | What it does |
|---|---|
| `backend/app/pipeline/fetch_building.py` | Downloads and caches one model's data into `<project>/data/<sid>/` (shared with acoustics) |
| `backend/app/sources/config.py` and `backend/app/sources/matterport.py` | Keys, Matterport GraphQL helper, paths (shared with acoustics) |
| `backend/app/sources/costar_kit.py` | Builds `data/catalog.json` (every kit building) + JSONL offsets; `backend/prototypes/explorer.py` runs it on first start |
| `index.html` | The page |
| `backend/prototypes/explorer.py` | Localhost server: catalog, kit-record and download APIs; serves the SDK key to the page without writing it into HTML |
