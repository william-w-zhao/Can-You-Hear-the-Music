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

The specific-room page at `/b/:sid/r/:rid` supports room-to-room acoustic analysis alongside the building picker and overview from the shared application. Open a room from the building's floor plan or directory after populating the private demo cache described in the root README.

The room page loads room geometry and acoustic details through `src/api.ts`, shows baseline materials and three-band RT60, compares another room in the same scan, and supports material what-ifs without replacing the baseline. Voice and clap comparisons use the same gain and the prototype's synthetic impulse-response model. A missing voice clip disables voice playback while leaving clap playback available. All styles are scoped to `.room-page`.

When the API supplies `object_evidence.views`, the room page uses its image viewports and full-resolution photo URLs, retaining object detection boxes, object matching and material review. Approved reviews refresh the baseline and reset material what-ifs. `RoomEvidence.tsx` contains the room-photo and dimension displays from the shared application.

For older responses without image evidence, the fallback room gallery reads `/data/{sid}/room_sheet.jpg` through `api.ts`. The legacy sheet uses one 200 px row per room in directory order, with six 200 px tiles after a 70 px ID gutter: ceiling, floor, then four walls. The fallback checks dimensions before showing the selected row. Missing or mismatched images show a labeled illustration and retry control; the illustration is not a reconstruction or scan photograph.

Cached reads require no browser API credentials. Matterport, Vexcel and other service keys stay on the backend. Requests use relative `/api/buildings/{sid}/rooms/...` URLs; Vite proxies `/api` and `/data` to port 8000. The frontend serves `/audio/voice.wav` from `public/audio/` when the API reports a voice clip. Never add service keys to frontend environment variables or requests.

Loading/error/retry states, cancellation during navigation, malformed acoustic-response checks and non-negative glass-area validation are included. Building analysis, room review and object matching use the shared application's existing endpoints.

## Checks

Use Node 22.12+, Node 24, or Node 26+ for the test runner.

```bash
npm ci
npm test
npm run build
```

Tests mock `fetch` using explicitly synthetic fixtures; they do not require credentials, the licensed kit or private scans. They cover scan-scoped room IDs, encoded paths, GET responses, what-if POST bodies, errors, invalid results, cancellation/timeouts, room comparison, retries, input validation and baseline reset. Actual cached-room metrics and voice playback still need the team's private demo cache and audio file for a live smoke check.
