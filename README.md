# Can You Hear the Music?

HackPrinceton 2026 (Science + Discovery, CoStar, Amazon and LangChain tracks). Pick a scanned building, pick a room, and hear
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

## Method

### 1. Echo: Eyring reverberation time

How long a sound takes to fade by 60 dB (RT60) is computed per octave band (125 Hz, 500 Hz, 2 kHz) with the Eyring
formula, which suits rooms with absorbent surfaces better than Sabine's:

$$
T_{60} = \frac{0.161\,V}{-S\,\ln(1-\bar\alpha) + 4mV}
\qquad
\bar\alpha = \frac{\sum_i S_i\,\alpha_i + A_{\text{contents}}}{S}
$$

- $V$ is the room volume (floor area × ceiling height) and $S = \sum_i S_i$ the total surface area.
- The surfaces $S_i$ are the floor and ceiling (each the floor area), the walls (perimeter × height, minus glass),
  the glass, any acoustic panels, and coverings measured from the photos: cabinetry and shelving replace their share
  of the bare wall, and a rug replaces its share of a hard floor (measured in the floor view, else 20% of the floor,
  10% in a bathroom).
- $\alpha_i$ is each material's absorption coefficient for the band (published typical values, `MATERIALS` and
  `COVERINGS` in `pipeline/acoustics.py`). $A_{\text{contents}}$ adds furniture absorption per square metre of floor.
- $4mV$ is air absorption, used at 2 kHz only ($m = 0.0024\ \text{m}^{-1}$).
- **Range:** each material also has a low and high coefficient at 500 Hz; recomputing with all lows and all highs
  gives the range shown beside the estimate.
- **Verdict at 500 Hz** (speech): up to 0.5 s excellent for calls, 0.7 s good, 1.0 s noticeable echo, longer echoey.

**Listening.** The browser builds an impulse response from three noise bands, each decaying at its RT60, scaled so
the reverberant energy relative to the direct sound matches $16\pi r^2/A$ for a listener $r = 1.5$ m away ($A$ is
the room's absorption at 500 Hz). A dry voice recording is convolved with it (Web Audio).

### 2. Objects and coverings from the panoramas

YOLO-World runs on the six 2048 px faces of each room's Matterport panorama, with several text descriptions per
object (for example "white panel door", "row of kitchen cabinets") and decoy descriptions (picture frame, vent,
light panel, tile floor) that absorb look-alikes. Detections are kept only where plausible: no furniture or windows
on the ceiling, rugs low in the picture, large items near the camera (not seen through a doorway), and bathroom
fixtures only in bathrooms. Soft items and windows are accepted at a lower score, and the vision model confirms the
remaining uncertain ones from a crop with the box drawn. Side-by-side cabinet boxes join into one run. Coverage is the
share of each view covered by the union of boxes, sampled on a 40 × 40 grid.

### 3. Street noise

**Traffic.** Roads within 400 m come from OpenStreetMap. Each road's daily volume (AADT) comes from the FHWA Highway
Performance Monitoring System, matched by location (the section must run alongside the road for 50 m and be a
compatible road class), else a city count (LADOT in Los Angeles), else a typical value for the road class and lanes.
Truck shares and speeds come from the same sources. The daily volume is spread over 24 hours with a typical urban
weekday profile.

**Outdoor level.** Each road is a line of vehicles. With the FHWA reference energy mean emission levels at
$D_0 = 15$ m ($S$ in km/h)

$$
L_0^{\text{auto}} = 38.1\log_{10}S - 2.4,\quad
L_0^{\text{medium}} = 33.9\log_{10}S + 16.4,\quad
L_0^{\text{heavy}} = 24.6\log_{10}S + 38.5,
$$

$N$ vehicles per hour of a type at speed $v$ (m/s) give, at distance $D$ over hard ground,

$$
L_{eq}(1\,\text{h}) = L_0 + 10\log_{10}\frac{\pi D_0 N}{3600\,v} + 10\log_{10}\frac{D_0}{D}.
$$

Vehicle types and roads add on an energy basis, $L = 10\log_{10}\sum 10^{L_k/10}$, with a 38 dB background.
The day–night level counts night hours (22:00–07:00) 10 dB louder:
$L_{dn} = 10\log_{10}\big(\tfrac{1}{24}\sum_h 10^{(L_h + 10\,[h\in\text{night}])/10}\big)$.

**Outside walls.** A room edge is an outside wall when no other room lies just beyond it. The floor plan is turned
to north by matching it to the OpenStreetMap building outline (dominant wall angle, then the quarter turn with the
best two-way overlap); if it fits two ways the louder case is used, and if no outline fits, every outside wall is
assumed to face the traffic. Each wall gets its own distance to every road; a wall side-on to a road hears 4 dB
less and a wall facing away 12 dB less (shielded by the building). Windows seen in the panoramas are given compass
directions from each panorama's heading, and the room's glass is weighted toward the walls where they were seen.

**Indoor level** (EN 12354-3 style), summed over the room's outside walls:

$$
L_{in} = L_{out} - R' + 10\log_{10}\frac{S_w}{A},
\qquad
R' = -10\log_{10}\frac{(S_w - S_g)\,\tau_{\text{wall}} + (S_g - S_o)\,\tau_{\text{glass}} + S_o}{S_w},
\quad \tau = 10^{-R/10}
$$

- $S_w$ is the wall area, $S_g$ its glass, $A$ the room's absorption at 500 Hz.
- Wall and window insulation $R$ (traffic-weighted $R_w + C_{tr}$) come from the construction read from outdoor
  photos: for example stucco on wood frame 40 dB, brick veneer 48 dB, single glazing 24 dB, double 30 dB.
- **Open window:** one window on the noisiest glazed wall is opened by a quarter of that wall's glass, up to
  0.5 m². The opening $S_o$ lets sound straight through ($\tau = 1$), so a larger window open lets in more. This
  typically leaves 15–22 dB of facade insulation, against about 33 dB closed.
- Rooms with no outside wall are treated as behind one more wall (+10 dB), and no room drops below 18 dB.
- Benchmarks: HUD's 45 dB $L_{dn}$ indoor goal for homes and the WHO's 30 dB night-time bedroom guideline.

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
