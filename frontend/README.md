# Frontend

React + Vite. Pick a building, pick a room, hear it, ask the agent.

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (needs the backend on :8000)
```

| Path | What goes there |
|---|---|
| `src/pages/` | `BuildingPicker` -> `BuildingView` -> `RoomView` |
| `src/components/` | `FloorPlan`, `EchoChart`, `Listen` (Web Audio), `WhatIf`, `AgentPanel` |
| `src/api.ts` | The only file that calls the backend |
| `public/audio/` | The generated dry voice clip used by the listening demo |

The React pages are placeholders. The working demo pages are in `prototypes/` and use the local servers documented in the backend README.
