# Room acoustics

How each scanned room sounds: echo time per room, a voice you can play in it, and "what if" material changes.
Its own app on **http://localhost:8766**; the building explorer is separate (http://localhost:8765).

Run from `backend/` with the backend Python environment active:

```bash
python3 -m app.pipeline.fetch_building --model <sid>   # shared download (skip if the explorer already did it)
python3 -m app.pipeline.pointcloud --model <sid>       # stream cloud.xyz out of the MatterPak (~7 s)
python3 -m app.pipeline.rooms --model <sid>            # split rooms from the point cloud
#   or --source matterport for scans that have Matterport room outlines (e.g. zvKHR9DHNjJ)
# label materials per room into data/<sid>/materials.json, from data/<sid>/room_sheet.jpg
python3 -m app.pipeline.acoustics --model <sid>        # echo time per room -> data/<sid>/acoustics.json
python3 -m prototypes.acoustics                        # http://localhost:8766
```

Outputs go into the shared cache, `<project>/data/<sid>/`: `cloud.npy`, `rooms.json`, `room_sheet.jpg`,
`materials.json`, `acoustics.json`.

| Step | How |
|---|---|
| Rooms from the point cloud | A ceiling slice marks what is indoors. A wall slice (1 m up to just under the ceiling) marks walls, including the wall above each door. Gaps up to 1.3 m are bridged so doorways close rooms off. Only areas containing a scan position count, which drops glimpses through windows. |
| Materials | One panorama per room (ceiling, floor, four walls) on a contact sheet. In this prototype Claude labelled them by eye; in the build that is one Claude API call per room. |
| Echo time (RT60) | Eyring's formula at 125 Hz, 500 Hz and 2 kHz with typical published absorption values; each material's spread gives the "likely" range. |
| Listening | A dry voice clip (macOS `say`, in `frontend/public/audio/voice.wav`) convolved in the browser with an impulse response built from the three echo times, so what-if changes are heard instantly. |

## First results

| Building | Result |
|---|---|
| 1990 S Bundy Dr, Suite 410 (hLR2zAFV1tK), office | 11 rooms split from the point cloud. Carpet + acoustic ceiling tile: 0.32–0.44 s everywhere ("excellent for calls"). Same office with an exposed ceiling and concrete floor: about 1.2 s. |
| 5836 La Mirada Ave (zvKHR9DHNjJ), 1920 house | 13 rooms from Matterport outlines. Furnished plaster rooms about 0.75 s, tiled kitchen 1.3 s, bathroom 1.1 s. |

Not validated against measurements yet. Plan: clap-test 3–4 rooms at the venue with a phone and compare.

## Files

| File | What it does |
|---|---|
| `backend/app/pipeline/pointcloud.py` | Streams the point cloud out of a MatterPak with HTTP range requests |
| `backend/app/pipeline/rooms.py` | Rooms from the point cloud (or Matterport outlines) + panorama contact sheet |
| `backend/app/pipeline/acoustics.py` | Echo time per room per band, ranges, furnished scenario; dry voice clip |
| `index.html` | The acoustics page |
| `backend/prototypes/acoustics.py` | Localhost server on 8766; serves the demo page, audio and shared `data/` cache |
| `frontend/public/audio/voice.wav` | Dry voice clip used for listening |
