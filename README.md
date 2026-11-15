# Can You Hear the Music?

HackPrinceton 2026 (Sustainability/Business/Science + Discovery, CoStar, main and LangChain Deep Agents tracks). Pick a scanned building, pick a room, and hear
it: how long a voice echoes, how much street noise gets in at any hour, and what a change such as a rug, carpet or
acoustic panels would do. An AI investigator answers questions like "which bedroom is quietest at night?" and asks
before it saves any change.

## What it does

| Step | How | Code |
|---|---|---|
| Building catalog | 14,933 scanned properties from the CoStar kit (Los Angeles and Houston) | `app/sources/costar_kit.py`, `api/buildings.py` |
| Scan download | Matterport rooms, panoramas, floor plans and wall graph; Vexcel aerial; CoStar listing; OpenStreetMap outlines | `app/pipeline/fetch_building.py`, `app/sources/` |
| Rooms | Matterport room outlines and dimensions (area from the outline when dimensions are missing; outdoor spaces skipped), or a point-cloud split | `app/pipeline/rooms.py` |
| Objects | YOLO-World on the full 2048 px panorama faces: furniture, fixtures, doors, windows, rugs, cabinet runs. Decoys and view rules remove look-alikes; the vision model confirms uncertain rugs, sofas, beds, curtains, shelves and windows | `app/pipeline/vision.py` |
| Materials | The vision model suggests room name, floor, ceiling, walls, furnishing and glass from the panoramas and YOLO hints; a person reviews | `app/pipeline/materials.py`, `components/BuildingAnalysis.tsx` |
| Echo | Eyring RT60 at 125 Hz, 500 Hz and 2 kHz with a range from material uncertainty. Cabinet runs, shelving and rugs measured from the photos replace their share of wall or floor | `app/pipeline/acoustics.py` |
| Street noise | Roads within 400 m (OpenStreetMap) with FHWA HPMS daily counts for every US state, city counts where available (LADOT), else a labelled typical value. FHWA vehicle noise per hour, per outside wall | `app/sources/traffic.py`, `app/pipeline/traffic_noise.py` |
| Outside walls | Outside walls from the floor plan, turned to north against the OpenStreetMap outline; wall and window construction read from outdoor panoramas and listing captions; glass placed on walls where windows were seen | `app/pipeline/facades.py`, `exterior.py`, `street_noise.py` |
| Review | Duplicate and label review on the room page; a Deep Agent can propose fixes from drawn views | `app/agent/room_review.py`, `api/acoustics.py` |
| Investigator | Deep Agent with planning, three sub-agents (`material-annotator`, `acoustic-simulator`, `traffic-analyst`) and a human-approval pause before saving a material change | `app/agent/`, `api/agent.py`, `components/AgentPanel.tsx` |

Rule: **the agent decides, the code computes.** Every number the agent states comes from a tool.

## How accurate is it?

- **Echo engine.** Against measured reverberation in the dEchorate lab room (`python -m tests.compare_dechorate`):
  0.56 s predicted versus 0.59 s measured with reflective walls and ceiling, but 2–3× too short when the room is
  heavily treated (0.07 s versus 0.20 s), a known limit of the Eyring formula with concentrated absorption.
  Rankings and the size of a change are right. Homes are mostly reflective, the better case.
- **Geometry.** Room areas are Matterport's measurements and add up to 86–96% of listing square footage (listings
  include walls). Ceiling heights are measured for most rooms. Wall area is perimeter × height with doors closed.
- **Materials matter most.** One wrong label (for example an acoustic-tile ceiling that is really drywall) changes
  a room's echo more than any area error. Labels come from the vision model and should be reviewed.
- **Street noise** is a screening estimate, typically within about ±5 dB: no terrain, sound walls or weekend
  traffic; counts can be years old; window insulation is read from photos. It has not been checked against a
  sound-level measurement at these buildings.
- **Detection.** On the four demo scans YOLO finds about 200 doors, 80 windows, 35 rugs and 100 cabinet runs.
  Some windows seen through doorways still count for the wrong room.

## Run it

1. Put the CoStar kit at `costar-hackathon-kit/` (CSV files directly inside) and create the root `.env` from
   `.env.example`: `MATTERPORT_API_KEY`, `MATTERPORT_API_TOKEN`, `MATTERPORT_SDK_KEY`, `VEXCEL_API_KEY`, and
   `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` (`REVIEW_MODEL` picks the model, for example `openai:gpt-5.6-terra` or
   `anthropic:claude-sonnet-4-6`). Keys, `data/` and the kit stay out of Git.
2. Backend (from `backend/`):

   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt -r requirements-vision.txt
   uvicorn app.main:app --reload --port 8000
   ```

   `http://localhost:8000/docs` lists every route. The first detection run downloads YOLO and CLIP weights into
   `.vision-cache/`.
3. Frontend (from `frontend/`): `npm install && npm run dev`, then open `http://localhost:5173`.

To analyse a new single-floor scan, open it from the home page and select **Analyse building**. The page shows
each stage, then a review form if any suggested label is uncertain. Completed stages are reused on retry. Analysis
jobs and agent conversations live in memory, so a backend restart forgets them (saved labels and results stay).
To redo detection for a cached scan: `python -m app.pipeline.vision --model <sid> --refresh`.

## Layout

```
backend/
  app/main.py          FastAPI app
  app/api/             buildings (catalog, analysis, traffic) · acoustics (room, reviews, what-if) · jobs · agent
  app/sources/         config · Matterport · Vexcel · OpenStreetMap · CoStar kit · traffic counts · model choice
  app/pipeline/        rooms · vision · materials · acoustics · facades · exterior · traffic_noise · street_noise · …
  app/agent/           investigator, sub-agents, tools, room review agent
  tests/               unit tests and the dEchorate benchmark
frontend/src/
  pages/               BuildingPicker → BuildingView (floor plan, investigator) → RoomView (echo, listen, street noise)
  components/          FloorPlan · EchoChart · Listen · WhatIf · StreetNoise · AgentPanel · RoomInterior · …
  api.ts               the only module that calls the backend
data/<sid>/            per-scan cache (git-ignored): bundle, rooms, vision, materials, acoustics, traffic, exterior
```

## API

| Route | Purpose |
|---|---|
| `GET /api/buildings`, `GET /api/buildings/{sid}` | Catalog and one building |
| `POST /api/buildings/{sid}/analyse`, `GET /api/jobs/{id}` | Start analysis and follow its stage |
| `POST /api/buildings/{sid}/materials` | Save reviewed labels and calculate echo times |
| `GET /api/buildings/{sid}/rooms`, `…/surroundings`, `…/traffic` | Floor plan and rooms, aerial evidence, street noise |
| `GET /api/buildings/{sid}/rooms/{rid}/acoustics` (+ `/what-if`, `/room-review`, `/object-review/…`) | Room echo, what-ifs, reviews |
| `POST /api/agent/threads`, `…/messages`, `GET …/events`, `POST …/approve` | Investigator chat |

## Tests

```bash
cd backend && .venv/bin/python -m unittest discover -s tests
cd frontend && npx vitest run && npx tsc --noEmit && npx vite build
```

## Data sources

CoStar hackathon kit and listing captions · Matterport scans and panoramas · Vexcel aerial imagery · OpenStreetMap
roads and building outlines (ODbL) · FHWA Highway Performance Monitoring System (public domain) · City of Los
Angeles LADOT traffic counts (CC0) · FHWA reference vehicle noise levels · HUD 24 CFR 51 indoor noise goal · WHO
night-time bedroom guideline · dEchorate measured room responses.

## Rules for adding code

- Routes in `api/` stay thin; computation goes in `pipeline/`; anything that calls an outside service or reads the
  kit goes in `sources/`. The agent only calls `pipeline/` and `sources/` functions.
- Only `frontend/src/api.ts` calls the backend.
- Downloaded or computed data goes in `data/<sid>/`, never in a code folder. Keys stay in `.env`.
