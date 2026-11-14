# Can You Hear the Music

HackPrinceton 2026, CoStar track. Two local apps built on the same Matterport + Vexcel + CoStar data.

```
Can You Hear the Music/
├── acoustics/              Room acoustics app        → http://localhost:8766
├── explorer/               Building explorer app     → http://localhost:8765
├── shared/                 Code both apps use: keys, Matterport API, fetch_building.py
├── data/<sid>/             Shared cache, one folder per Matterport model (both apps read and write it)
├── key-check/              One-off API/SDK key tests; holds .env with the keys
└── costar-hackathon-kit/   CoStar's data kit (read-only, hackathon use only)
```

## Run

From this folder, one terminal per app:

```bash
python3 explorer/serve.py
```

```bash
python3 acoustics/serve.py
```

Or start either from the app's Browser pane, using the `explorer` and `acoustics` configurations in
`.claude/launch.json`.

## Add a building

```bash
python3 shared/fetch_building.py --model <sid>     # or the "Download" button in the explorer
```

Then see `explorer/README.md` (shadow heights, rooms) and `acoustics/README.md` (echo times).

## Next steps

Where things stand: the acoustics prototype works on two buildings (an office suite split into 11 rooms from
its point cloud, and a 1920 house from Matterport's room outlines). Each room has an echo time, a playable
voice clip and "what if" material changes. Materials were labelled by hand and nothing is checked against real
measurements yet. The sunlight / shadow-height work is parked in the explorer.

In priority order. Each step says what "done" looks like.

### 1. Prove the numbers: clap test at the venue (most important)
Judges will ask "how do you know?". Right now the answer is "we don't".
- Write `acoustics/measure_rt60.py`: takes a phone recording of a clap or balloon pop, returns the measured
  echo time at low, mid and high pitch.
- Pick 3–4 rooms at the venue that sound different (small office, classroom, stairwell, hallway). Tape-measure
  them, note the materials, record a clap in each.
- Put each room through `acoustics.py` and compare predicted vs measured.
- Ask the Matterport engineers whether the hackathon keys can see a space we scan ourselves with the phone app;
  if so, scan one venue room and test the whole pipeline end to end.
- **Done when:** a table of predicted vs measured echo time for 3+ real rooms, with the error, is on the page.
  If the error is large, adjust the furniture and material values in `acoustics.py` (furnished rooms are
  probably estimated too echoey today).

### 2. Automate material labelling
- Write `acoustics/label_materials.py`: one Claude API call per room with that room's panorama faces, returning
  floor, ceiling, walls, furnishing, glass area and a confidence, in the same shape as `materials.json`.
- Low-confidence answers get flagged for a person to confirm.
- Needs `ANTHROPIC_API_KEY` in `.env`.
- **Done when:** it reproduces the hand labels for both buildings, then runs on a new building with no hand work.

### 3. Run it on more buildings, and pick the demo set
- Run the pipeline on 10–20 scans. Look for contrast: an exposed-ceiling "creative office", a loft, a large
  apartment, a small studio, a restaurant or retail space.
- Fix what breaks. Known issues: room outlines can spill outdoors through windows (bottom right of the Bundy Dr
  plan), window glass is not detected from the point cloud, and multi-floor scans are untested.
- **Done when:** 5 demo buildings with clearly different results, all cached in `data/`.

### 4. One button from the explorer
- Add an "Analyse acoustics" button in the explorer next to the existing Download button. It runs
  `pointcloud.py`, `rooms_from_cloud.py`, `label_materials.py` and `acoustics.py`, then opens the acoustics app.
- **Done when:** any downloaded building can be analysed from the browser without a terminal.

### 5. Street noise (stretch)
- Outdoor level at the building from the US DOT national transportation noise map (road and aviation).
- Indoor estimate per room facing the street, as a range by window type (year built from CoStar suggests single
  or double pane), with an "open window" toggle.
- **Done when:** each room shows indoor street noise as a range, with the source named. Keep claims rough;
  this is the least certain part.

### 6. The agent (for the CoStar and LangChain prizes)
- A deepagents agent that answers questions like "find the best room for client calls in this building" or
  "what's the cheapest fix for the break room?", using steps 1–5 as tools.
- It asks a person when a material label is low confidence, and every number it states comes from a tool.
- **Done when:** the agent answers both example questions live, with its plan visible on screen.

### 7. Demo and submission
- Two-minute script: the problem, pick a building, hear two rooms, try the exposed-ceiling what-if, show the
  validation table, the agent answers a question.
- Speak in comparisons and categories ("this room is twice as echoey", "good for calls"), not exact decibels.
- Bring headphones for the judges and record a backup video.
- Devpost: CoStar track, main track, LangChain deepagents.

### Housekeeping
- `git init` and push only after checking `git status` shows no data or keys (the `.gitignore` covers them).
- Add a `requirements.txt` (`requests numpy scipy pillow scikit-image`).
- Share keys with teammates through a private channel, never in the repo; each person fills in
  `key-check/.env` from `key-check/.env.example`.

## Rules for adding code

- Code used by both apps goes in `shared/`; each app imports it with the two-line `sys.path` bootstrap at the top of its scripts.
- Downloaded or computed data goes in `data/<sid>/`, never inside an app folder.
- Keys stay in `.env` (here or in `key-check/`), never in code or HTML; `.env` and `data/` are git-ignored.
