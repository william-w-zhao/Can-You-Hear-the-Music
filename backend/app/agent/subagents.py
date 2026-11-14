"""Sub-agents, one per job, each wrapping real pipeline functions (see tools.py).

- room-surveyor:       rooms and geometry           -> pipeline.rooms
- material-annotator:  materials from panoramas     -> pipeline.materials (asks a person when unsure)
- acoustic-simulator:  echo times, what-ifs, audio  -> pipeline.acoustics
- context-scout:       year built, tenants, use     -> sources.costar_kit
- traffic-analyst:     street noise (later)         -> pipeline (not built yet)

TODO: define SUBAGENTS = [...] with name, description, system prompt and tools.
"""
SUBAGENTS: list = []
