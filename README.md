# Can You Hear the Music

HackPrinceton 2026, CoStar track. Pick any scanned building, pick a room, and hear how it sounds: echo time,
a voice played in that room, and "what if" changes (carpet, acoustic panels, an exposed ceiling). An AI agent
answers questions like "find the best room for client calls in this building".

## Structure

The app is a **backend** (Python, FastAPI) and a **frontend** (React + Vite). The existing data sources and
acoustics pipeline live in the backend. The working demo pages live in `frontend/prototypes/` while the FastAPI
routes and React UI are being built.

```
Can You Hear the Music/
├── backend/                      Python, FastAPI                         → http://localhost:8000
│   ├── app/
│   │   ├── main.py               the FastAPI server
│   │   ├── api/                  buildings · rooms · acoustics · jobs · agent (live stream)
│   │   ├── sources/              configuration · Matterport · Vexcel · OpenStreetMap · CoStar kit
│   │   ├── pipeline/             fetch_building · pointcloud · rooms (point-cloud split) ·
│   │   │                         materials (Claude vision) · acoustics (Eyring engine)
│   │   └── agent/                deepagents: main agent, sub-agents, tools wrapping pipeline/
│   ├── prototypes/               local servers for the explorer and acoustics demos
│   ├── tests/
│   └── requirements.txt
├── frontend/                     React + Vite                            → http://localhost:5173
│   ├── src/
│   │   ├── pages/                BuildingPicker → BuildingView (rooms on plan) → RoomView (echo, listen, what-if)
│   │   ├── components/           FloorPlan · EchoChart · Listen (Web Audio) · WhatIf · AgentPanel
│   │   └── api.ts                the only React module that calls the backend
│   ├── public/audio/             dry voice clip for listening
│   └── prototypes/               working explorer and acoustics demo pages
├── data/                         shared cache, one folder per scanned model (git-ignored)
├── key-check/                    API/SDK key tests; holds .env with the keys (git-ignored)
└── costar-hackathon-kit/         CoStar's data kit (read-only, git-ignored)
```

### How a request will flow

1. **Pick a building.** `GET /api/buildings` lists scanned buildings from the kit and marks which scans have analysis ready.
   Exclude outdoor-only scans such as pools and courtyards.
2. **Pick a room.** `GET /api/buildings/{sid}/rooms` returns the room outlines. If the building hasn't been
   analysed yet, `POST /api/buildings/{sid}/analyse` runs download → point cloud → room split → materials →
   acoustics as a background job, with progress streamed to the page.
3. **Hear the room.** `GET /api/buildings/{sid}/rooms/{room_id}/acoustics` returns echo times, materials and impulse-response settings.
   The browser plays the voice with Web Audio, using the echo times returned by the backend. The what-if endpoint recomputes those times after a material change.

### Where deepagents fits

| deepagents feature | What it does here                                                                                                                                                                                              |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Main agent         | The acoustic investigator: "find the best room for client calls", "cheapest fix for the break room?"                                                                                                           |
| Sub-agents         | `room-surveyor` (pipeline/rooms), `material-annotator` (pipeline/materials), `acoustic-simulator` (pipeline/acoustics), `context-scout` (CoStar: year built, tenants), `traffic-analyst` (street-noise estimates) |
| Planning           | The agent's to-do list streams live to `AgentPanel`                                                                                                                                                            |
| Working files      | Written to `data/<sid>/agent/`, the same files the UI reads                                                                                                                                                    |
| Human approval     | A low-confidence material ("glass or glossy paint?") pauses the agent; the frontend shows the image and a person confirms                                                                                      |

Rule: **the agent decides, the code computes.** Every number the agent states comes from a pipeline function.

## Teammate setup

1. Clone the repository and open a terminal in its root, where this README lives. Get the CoStar hackathon
   kit and API credentials through the team's private channel or the event's `/costar-keys` Discord command.
   Extract the kit as `costar-hackathon-kit/` next to `backend/` and `frontend/`. Both CSVs should be directly
   inside that folder, with the kit's `data/` and `schemas/` directories alongside them.

   ```text
   Can You Hear the Music/
   ├── backend/
   ├── frontend/
   ├── key-check/
   │   ├── .env.example
   │   └── .env                  create locally
   └── costar-hackathon-kit/
       ├── commercial-properties.csv
       ├── residential-listings.csv
       ├── data/
       └── schemas/
   ```

2. Create the local credentials file from the template. If `key-check/.env` already exists, edit it directly.

   ```bash
   cp -n key-check/.env.example key-check/.env
   ```

   Fill in `MATTERPORT_API_KEY` and `MATTERPORT_API_TOKEN` for scan downloads, `VEXCEL_API_KEY` for aerial
   imagery, and `MATTERPORT_SDK_KEY` for the browser's Showcase viewer. Use `COSTAR_ZIP_PASSWORD` to unlock
   the archive if needed. The unpacked kit is read from disk. The hackathon site username and password are
   optional. The backend checks shell environment variables first, then a root `.env`, then `key-check/.env`.
   The key-check scripts read `key-check/.env` and shell variables. Keep credentials and the kit out of Git.

3. Set up Python from the repository root, then check access to Matterport, Vexcel and the CoStar kit.

   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   python ../key-check/test_keys.py
   ```

4. To try the existing office and house acoustics, copy `data/hLR2zAFV1tK/` and `data/zvKHR9DHNjJ/` into the
   clone's root `data/` directory through the team's private channel. For the acoustics prototype's building
   selector and voice playback, also copy `data/index.json` and `frontend/public/audio/voice.wav` to their
   matching paths. These files are Git-ignored. The kit supplies the building catalog, which the API can build
   on the first building-list request. The room analysis and audio come from the demo cache.

5. From `backend/` with the virtual environment active, start the server and leave the terminal running.

   ```bash
   python -m uvicorn app.main:app --reload --port 8000
   ```

   On your teammate's machine, open [the API health check](http://localhost:8000/api/health) and then
   [Swagger](http://localhost:8000/docs). For a copied demo cache, try
   [the office room list](http://localhost:8000/api/buildings/hLR2zAFV1tK/rooms). These cached reads use local
   files. The API keys are used by the download pipeline and key checks.

## Run

The target app serves cached scans. New-scan analysis and agent routes are still scaffolds.

```bash
cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Working prototypes (one terminal each, using the Python dependencies from the backend setup above):

```bash
cd backend && source .venv/bin/activate && python3 -m prototypes.explorer  # http://localhost:8765
```

```bash
cd backend && source .venv/bin/activate && python3 -m prototypes.acoustics  # http://localhost:8766
```

## Build plan

Start with the cached office suite (`hLR2zAFV1tK`, 11 rooms), then check the same flow on the 1920 house
(`zvKHR9DHNjJ`, 13 rooms). The prototypes already split rooms, estimate echo from hand-labeled materials and
play a voice with Web Audio. The cached-data API now serves both scans and computes material what-ifs. The
next milestone is a React dashboard that can compare two office rooms and play a material what-if using cached data.
The [Hear the Space build guide](https://claude.ai/artifact/Vie6TwPdwnQxj7zGCiYq1C) describes the full demo,
including the hourly street-noise slider and the agent.

### Component responsibilities

| Component | Code and inputs | Output or consumer |
|---|---|---|
| Building data | `backend/app/sources/` and `app/pipeline/fetch_building.py` read the CoStar kit, Matterport and aerial imagery | Catalog and `data/<sid>/bundle.json` with scan metadata, panoramas and floor-plan files |
| Room geometry | `app/pipeline/pointcloud.py` and `rooms.py` use Matterport outlines or split a point cloud | `rooms.json` with floor-plan pixels, room dimensions and panorama IDs |
| Material annotation | `app/pipeline/materials.py` will use YOLO to locate furniture and Claude vision to classify acoustic surfaces | `materials.json` keyed by room ID, with editable labels, confidence and image references |
| Acoustic engine | `app/pipeline/acoustics.py` combines geometry and materials | Three-band RT60, a mid-band range and treatment results for API and agent tools |
| Street noise | Add traffic data ingestion under `app/sources/` and indoor estimates under `app/pipeline/` | A sourced 24-hour estimate per room for the chart, audio mixer and agent |
| API and jobs | `backend/app/api/` reads cached outputs, validates changes and streams work in progress | Typed responses and server-sent events for `frontend/src/api.ts` |
| Dashboard | `frontend/src/pages/` and `components/` render the floor plan, room cards and controls | Building selection, A/B listening, what-ifs and an agent activity panel |
| Agent | `backend/app/agent/` wraps the pipeline in deepagents tools | Ranked room recommendations, a live task trace and material review requests |

### 1. Serve the cached buildings through FastAPI (complete)

1. Implement the building list and detail handlers in `backend/app/api/buildings.py`. Reuse the CoStar
   catalog loader and include analysis availability so the picker can distinguish cached scans from the rest.
2. Implement the room list from `rooms.json`. Return the floor-plan image URL and dimensions together with
   room IDs, polygons and room labels, so the frontend can overlay the polygons at any display size.
3. Define the room acoustics contract before wiring React. Both demo buildings have an `r1`, so use the
   scan ID and the room ID together. These are target routes for this milestone.

   | Route | Response |
   |---|---|
   | `GET /api/buildings` | Catalog summaries and analysis availability |
   | `GET /api/buildings/{sid}` | Scan metadata and analysis status |
   | `GET /api/buildings/{sid}/rooms` | Floor-plan metadata and room outlines |
   | `GET /api/buildings/{sid}/rooms/{room_id}/acoustics` | Materials, echo times at 125 Hz, 500 Hz and 2 kHz, the 500 Hz range and the verdict |
   | `POST /api/buildings/{sid}/rooms/{room_id}/acoustics/what-if` | Recomputed echo times and verdict after a validated material or furnishing override |

4. Reuse `rt60()` from `pipeline/acoustics.py` for what-ifs. Combine each override with the saved room
   labels in memory and return the result without modifying the cache. Return a clear error for unknown rooms,
   missing analysis or invalid material choices. Update `frontend/src/api.ts` to use the same paths and types.

**Done when** both scans return real responses in `/docs`, the two `r1` lookups resolve to the correct rooms,
and `backend/tests/test_acoustics.py` reproduces the saved echo results for all 24 rooms.

### 2. Build the React listening flow

1. **BuildingPicker** loads the catalog through `api.ts`, shows which scans can be played and links to
   `/b/:sid`. Start with the two cached scans and make them easy to find.
2. **BuildingView and FloorPlan** overlay each room polygon on the cached plan. Make rooms selectable from
   both the plan and a room list. Link the selection to `/b/:sid/r/:rid`.
3. **RoomView and EchoChart** display the current materials, room verdict and RT60 at the three bands.
   Handle loading, errors and scans awaiting analysis.
4. **Listen** ports the browser impulse-response and playback code from
   `frontend/prototypes/acoustics/index.html`. Load the dry voice clip from `frontend/public/audio/`.
   Start playback on user action and let the listener replay the same clip in two rooms at the same gain.
5. **WhatIf** sends a material change through `api.ts` and feeds the returned RT60 values to the chart and
   player. Keep the baseline available for A/B playback. Start with the existing exposed-ceiling and flooring
   changes, then add any treatments the engine supports.

**Done when** a user can pick either cached building, select a room, hear a comparison and reset a what-if.
Keep the prototypes available until the React dashboard covers the demo flow.

### 3. Add hourly street noise for one building

1. Pick a demo scan near a road with usable traffic counts. Cache the count, road segment, source and date.
   Prefer local or state agency counts. Record when a typical hourly profile is used to fill gaps in daily data.
2. Estimate the road-to-window distance and which rooms face the road. Record the assumed glazing and its
   attenuation. Use the road data and these assumptions to calculate a 24-hour indoor estimate with a confidence
   note. If exploring Vexcel car detections, use them as a lower-confidence fallback.
3. Serve the curve for that scan and add the time slider and traffic mix in `Listen`. Keep street noise and
   RT60 as separate inputs to playback, since the time slider changes the background sound.

**Done when** the dashboard shows the source and assumptions behind the estimate and a listener can hear the
difference between 2 a.m. and 8 a.m. The traffic-data work can begin alongside the dashboard.

### 4. Automate material labels and analyse a new scan

1. In `pipeline/materials.py`, use the room's panorama IDs to fetch the six skybox faces of a representative
   panorama. Run [YOLO detection](https://docs.ultralytics.com/modes/predict) on each face to locate common
   furniture such as chairs and couches. Keep each detection's label, confidence, bounding box, panorama ID
   and face index so the agent can retrieve the crop later. Use detections to inform the room's coarse
   furnishing category.
2. Send the faces and relevant detections in a structured Claude vision request using `ANTHROPIC_API_KEY`.
   Classify acoustically important surfaces such as carpet, ceiling tile, acoustic panels and glazing. Return
   floor, ceiling, walls and furnishing labels using the engine's existing keys, with confidence and evidence
   references. Estimate glass area from room geometry where possible and record any assumptions.
3. Compare predictions with the hand labels in both demo buildings. Flag low-confidence or missing labels
   that could change the acoustic result, and preserve confirmed corrections on retry.
4. Implement `POST /api/buildings/{sid}/analyse` and the job endpoints in `api/jobs.py`. Run download,
   geometry, material labels and acoustics in that order. Use Matterport outlines where suitable and point-cloud
   segmentation as the other path. Stream stage changes and failures to the dashboard and reuse completed
   outputs on retry.
5. Run the flow on a previously uncached scan. Check the room polygons against the floor plan, especially near
   windows. Verify floor selection before using a multi-floor scan in the demo.

**Done when** a user can start analysis from the picker, see progress, review doubtful labels and play a room
when the job finishes.

### 5. Add the deepagents workflow

1. In `app/agent/tools.py`, expose room lookup, acoustic comparison, what-if and CoStar context as tools.
   Start with cached results so the first agent question can complete without running a full analysis job.
2. In `app/agent/`, give the main agent the building context and delegate to specialists for geometry,
   materials, acoustics, CoStar context and traffic as those tools become available. Save tool evidence under
   `data/<sid>/agent/` so a recommendation can point to the room and calculated values it used.
3. Give the material annotator tools to fetch a detection crop, inspect a second panorama and ask Claude
   vision to classify the surface using the engine's material choices. Investigate when views disagree or when
   an uncertain label could change the room ranking. If both labels remain plausible, use the what-if tool to
   see how much the choice affects RT60.
4. Wire `api/agent.py` and `AgentPanel` for chat, streamed to-dos, tool activity and final answers. If a
   consequential label stays ambiguous, show both views and the proposed labels. Use a
   [Deep Agents review interrupt with a checkpointer](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop)
   to pause and resume after the user confirms or corrects the label. Save the reviewed label in
   `materials.json`, recompute RT60 and refresh the room ranking and playback.

**Done when** the agent can rank rooms for client calls, compare a treatment with the baseline, and show the
tool results behind its recommendation. If it recommends the cheapest treatment, give it explicit cost inputs.

### 6. Validate, rehearse and submit

1. Record repeated claps or balloon pops in 3–4 contrasting venue rooms. Measure room dimensions and label
   surfaces, estimate decay from the recordings and show predicted versus measured echo times. Ask the
   Matterport engineers whether a phone scan of a venue room can be accessed with the hackathon keys.
2. Expand the cached demo set toward five contrasting scans. Keep the office and house available and include
   a near-road example with defensible traffic data. Freeze features once the demo flow is stable and
   rehearse with cached analysis outputs and headphones.
3. Rehearse the two-minute flow from the build guide. Ask for the best call room and use a real ambiguity,
   such as glass versus a glossy partition, to show the agent checking a second view and comparing both RT60
   estimates. Compare two rooms by ear, show the time slider and play a treatment before and after. Record a
   backup video before submission.
4. Prepare the Devpost submission for the CoStar, main and LangChain deepagents tracks. Review `git status`
   before pushing. Keep `data/`, the CoStar kit and real `.env`
   files out of Git. Each teammate can populate `key-check/.env` from `key-check/.env.example` using keys
   shared privately.

## Rules for adding code

- Backend: routes in `api/` stay thin; computation goes in `pipeline/`; anything that talks to an outside
  service or reads the kit goes in `sources/`. The agent only calls `pipeline/` and `sources/` functions.
- Frontend: only `src/api.ts` calls the backend.
- Downloaded or computed data goes in `data/<sid>/`, never in a code folder.
- Keys stay in `.env`, never in code or HTML; `.env`, `data/` and the CoStar kit are git-ignored.
