"""Sub-agents, one per job, each limited to the tools that job needs (see tools.py).

- material-annotator:  compares saved materials with the panorama photos
- acoustic-simulator:  compares treatments with what-if recalculations
- context-scout and traffic-analyst come later, once CoStar context and street-noise data are tools.
"""
from app.agent import prompts


def subagents(tools):
    return [
        {
            "name": "material-annotator",
            "description": "Checks one room's saved floor, ceiling, wall and furnishing labels against its "
                           "panorama photos. Give it the room ID.",
            "system_prompt": prompts.MATERIAL_ANNOTATOR,
            "tools": [tools["room_details"], tools["view_room"]],
        },
        {
            "name": "acoustic-simulator",
            "description": "Compares acoustic treatments for one or more rooms with what-if recalculations and "
                           "returns a table of options. Give it the room IDs and the goal.",
            "system_prompt": prompts.ACOUSTIC_SIMULATOR,
            "tools": [tools["list_rooms"], tools["room_details"], tools["what_if"]],
        },
    ]
