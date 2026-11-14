# Building explorer

Everything the three data layers know about one building, on one local page, plus a prototype of
**building heights from shadows without a capture timestamp**.

Run from `backend/` with the backend Python environment active:

```bash
python3 -m app.pipeline.fetch_building                 # cache Matterport, Vexcel, CoStar, drone catalog, LA County outlines
python3 -m app.pipeline.shadows                        # sun angle + heights from the Vexcel shadows
python3 -m prototypes.explorer                         # http://localhost:8765  (SDK key check at /keys)
```

The room acoustics app is separate (http://localhost:8765/acoustics redirects to it). Both apps
read and write the same cache in `<project>/data/<sid>/`.

The page lists **every building in the kit** (5,099 buildings, 14,933 Matterport scans) in a searchable
sidebar: filter by residential/commercial and city, and sort by price, size, stories or year. Pick a building to
see its CoStar records at once. A building with several scans (suites or units) gets a scan picker. Scans
that are not downloaded yet have a **Download scan, rooms & aerial data** button, which runs the two scripts
above for that model. Once a scan is downloaded, the **Rooms** section lets you pick any room on the plan, in
the chips or in the table to see its area, dimensions, ceiling, perimeter, walls and scan positions.
`?m=<sid>&room=<id>` links straight to a building and room.

Use `--model <sid>` on the first two for another model (any id in the kit CSVs). Keys come from
`<project>/.env` or `key-check/.env`. Needs `requests numpy scipy pillow`.

## How the shadow trick works without a timestamp

1. **Shadow mask**: dark, bluish pixels (shadows are lit only by blue skylight).
2. **Direction**: the bearing where building outlines, shifted outward, land on shadow most often.
3. **Length**: rotate so shadows point right; per row of each outline, the dark run past its leeward edge.
4. **Calibrate**: a CoStar building with a known story count gives `tan(sun elevation) = height / shadow`.
5. **Heights**: every other building = `shadow x tan(sun elevation)`.
6. **Validate**: LA County's LiDAR heights (carried in OpenStreetMap outlines) never feed the estimate.

First result (5836 La Mirada Ave): shadows point 359.5°, sun 41.6° up (calibrated on Lex II, 5 stories),
consistent with about 12:30 on Oct 31 or Feb 9. Median error 2.7 m on 125 buildings; estimates run about
2.5 m low on pitched-roof houses, whose ridge height (what LA County records) casts no longer shadow
than the eaves.

## Files

| File | What it does |
|---|---|
| `backend/app/pipeline/fetch_building.py` | Downloads and caches one model's data into `<project>/data/<sid>/` (shared with acoustics) |
| `backend/app/sources/config.py` and `backend/app/sources/matterport.py` | Keys, Matterport GraphQL helper, paths (shared with acoustics) |
| `backend/app/pipeline/shadows.py` | Shadow direction, calibration, heights, validation → `data/<sid>/shadows.json` |
| `backend/app/pipeline/solar.py` | Sun position (NOAA equations) and "when could the sun have been here" search |
| `backend/app/sources/costar_kit.py` | Builds `data/catalog.json` (every kit building) + JSONL offsets; `backend/prototypes/explorer.py` runs it on first start |
| `index.html` | The page |
| `backend/prototypes/explorer.py` | Localhost server: catalog, kit-record and download APIs; serves the SDK key to the page without writing it into HTML |
