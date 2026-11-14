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
| `app/sources/` | Keys and paths (`config.py`), Matterport, Vexcel, the CoStar kit |
| `app/pipeline/` | The computation: plain functions that read and write `data/<sid>/` |
| `app/agent/` | The deepagents agent, its sub-agents, and tools that wrap `pipeline/` |
| `prototypes/` | Local servers for the working explorer and acoustics demos |
| `tests/` | Tests for the pipeline |

The feature routes currently return 501. The existing pipeline scripts run as modules from `backend/`.
To run the working demos, use `python3 -m prototypes.explorer` and `python3 -m prototypes.acoustics` in
separate terminals with the backend environment active.
