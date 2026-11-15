# Backend

FastAPI app: the API the frontend calls, the computation pipeline, and the deepagents agent.

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000        # http://localhost:8000/docs lists every route
```

| Folder | What goes there |
|---|---|
| `app/api/` | HTTP routes. Thin: check input, call `sources/` or `pipeline/`, return JSON |
| `app/sources/` | Keys and paths (`config.py`), Matterport, Vexcel, the CoStar kit, OpenStreetMap, traffic counts |
| `app/pipeline/` | The computation: plain functions that read and write `data/<sid>/` |
| `app/agent/` | The deepagents agent, its sub-agents, and tools that wrap `pipeline/` |
| `tests/` | Tests for the pipeline |

Every route is listed in `/docs`; the root README summarises them. Use `POST /api/buildings/{sid}/analyse`
to start a job, `GET /api/jobs/{job_id}` to check progress, and `POST /api/buildings/{sid}/materials` to save
reviewed labels (this works even if a restart forgot the job). Pipeline modules also run as scripts from
`backend/`, for example `python -m app.pipeline.vision --model <sid> --refresh` or
`python -m app.sources.traffic <sid>`.

## Compare predicted and measured reverberation

From `backend/`, with the backend environment active:

```bash
python -m pip install h5py
python -m tests.compare_dechorate
```

The benchmark downloads 12 [dEchorate SOFA recordings](https://sofacoustics.org/data/database/dechorate/)
(about 20 MB total) into `data/benchmarks/dechorate/` at the project root. Use `--data-dir` to point to an
existing download. It compares the app's 500 Hz RT60 with the mean measured 500 Hz T20 across 15 microphone
channels from three arrays per configuration, using the same speaker in both configurations. It reports the
measurement spread, absolute error, and predicted versus measured change.

The test uses the [paper's documented room and surface configurations](https://doi.org/10.1186/s13636-021-00229-0).
It tests four configurations, from absorbing walls and ceiling through mixed surfaces to reflective walls
and ceiling. The default inputs use carpet on pad, acoustic panels, and vinyl as proxies for the lab's
floor, absorptive panels, and reflective laminate. The report includes a sensitivity sweep for the fully
absorbing case. Use `--floor-500`, `--absorbing-500`, and `--reflective-500` to supply independently sourced
500 Hz coefficients. The comparison covers the acoustic engine and those material assumptions in one room.
Scan geometry and AI material identification require a separate test.
