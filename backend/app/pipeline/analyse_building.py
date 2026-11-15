"""Prepare a scan for the acoustics dashboard, reusing completed stages on retry."""
import json

from app.pipeline.acoustics import CONTENTS, MATERIALS, analyse_acoustics
from app.pipeline.cache_files import write_json
from app.pipeline.vision import analyse_vision
from app.sources.config import DATA
from app.sources.review_model import resolve_review_model


def analyse_building(sid, report):
    """Return room geometry if material review is needed, or None when ready."""
    directory = DATA / sid
    rooms_file = directory / "rooms.json"
    materials_file = directory / "materials.json"
    if not rooms_file.is_file():
        from app.pipeline.fetch_building import fetch_building
        from app.pipeline.pointcloud import download_pointcloud
        from app.pipeline.rooms import finish, rooms_from_cloud, rooms_from_matterport, select_floorplan

        bundle_file = directory / "bundle.json"
        if not bundle_file.is_file():
            report("Downloading the Matterport scan and surrounding property data")
            fetch_building(sid)
        bundle = json.loads(bundle_file.read_text())
        floorplan = select_floorplan(bundle["matterport"])
        if not (directory / floorplan["file"]).is_file():
            report("Downloading the missing floor plan")
            fetch_building(sid)
            bundle = json.loads(bundle_file.read_text())
        if len(bundle["matterport"]["floors"]) > 1:
            raise ValueError("Automatic analysis currently supports single-floor scans.")
        report("Preparing room outlines")
        rooms, floorplan, method = rooms_from_matterport(bundle)
        floor_z = ceiling_z = None
        if not rooms:
            if not (directory / "cloud.npy").is_file():
                report("Downloading the point cloud for room segmentation")
                download_pointcloud(sid)
            rooms, floorplan, method, floor_z, ceiling_z = rooms_from_cloud(directory, bundle)
        report("Preparing room panorama views")
        finish(sid, directory, rooms, floorplan, method, floor_z, ceiling_z)

    geometry = json.loads(rooms_file.read_text())
    if not geometry["rooms"]:
        raise ValueError("No usable rooms were found in this scan.")
    vision = analyse_vision(directory, geometry, report)
    if (directory / "acoustics.json").is_file():
        return None
    if not materials_file.is_file():
        from app.pipeline.materials import suggest_materials

        settings, _ = resolve_review_model()
        suggestions = {}
        # Saved so a backend restart reopens the review form without paying for the model calls again.
        saved_suggestions = directory / "material_suggestions.json"
        if saved_suggestions.is_file():
            suggestions = json.loads(saved_suggestions.read_text())
        elif settings and (directory / "room_sheet.jpg").is_file():
            suggestions = suggest_materials(directory, geometry["rooms"], report, settings, vision["indoor"]["rooms"]
                                            if vision["indoor"]["status"] == "complete" else {})
            if suggestions:
                write_json(saved_suggestions, suggestions)
        if len(suggestions) != len(geometry["rooms"]) or any(
            item["confidence"] < 0.8 for item in suggestions.values()
        ):
            object_hints = {room_id: {key: item[key] for key in ("objects", "candidates")}
                            for room_id, item in vision["indoor"].get("rooms", {}).items()}
            return {"rooms": geometry["rooms"], "suggestions": suggestions, "object_hints": object_hints,
                    "has_room_sheet": (directory / "room_sheet.jpg").is_file(),
                    "material_options": {key: value["name"] for key, value in MATERIALS.items()},
                    "furnishing_options": list(CONTENTS)}
        write_json(materials_file, {"labelled_by": f"{settings.identifier} panorama analysis", "rooms": suggestions})

    report("Calculating room echo times")
    analyse_acoustics(sid, directory)
    return None
