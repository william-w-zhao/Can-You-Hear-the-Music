# Key check

Tests the API keys for Can You Hear the Music, using the same endpoints and auth as the official
Matterport quickstart.

```bash
cp .env.example .env      # fill in the values from /costar-keys in Discord
python3 test_keys.py      # Matterport API, Vexcel, CoStar kit, splat site
python3 serve.py          # then open http://localhost:8765 for the Showcase SDK key
```

| Test | Key(s) | What a pass proves |
|---|---|---|
| Matterport Model API | `MATTERPORT_API_KEY` + `MATTERPORT_API_TOKEN` (basic auth) | Folder access, model basics + lat/lon, rooms and wall graph, a panorama download, MatterPak availability |
| Vexcel ortho | `VEXCEL_API_KEY` (`X-API-KEY` header) | A 140 m aerial clip around the model, saved to `out/vexcel_ortho.jpg` |
| CoStar kit | none (local files) | The model ID joins to a CoStar property or listing record |
| Splat site | none (optional site login) | The model's drone/splat listing is reachable |
| Showcase SDK | `MATTERPORT_SDK_KEY` | The 3D viewer accepts the key on this origin; Model, Camera, Sweep and Room data come back |

Options: `--model <sid>` (any id from the kit CSVs), `--only matterport|vexcel|costar|site`.

Keys are read from `.env` or the environment and are never printed. `serve.py` binds to localhost only
and refuses to serve `.env` and `.py` files.
