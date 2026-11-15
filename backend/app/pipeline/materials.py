"""Validate room materials and optionally propose them from panorama contact sheets."""
import base64
import io
import logging

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.pipeline.acoustics import CONTENTS, MATERIALS

logger = logging.getLogger(__name__)


class RoomMaterials(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    type: str = Field(min_length=1, max_length=100)
    floor: str
    ceiling: str
    walls: str
    furnishing: str
    glass_m2: float = Field(ge=0)

    @field_validator("floor", "ceiling", "walls")
    @classmethod
    def known_material(cls, value):
        if value not in MATERIALS:
            raise ValueError("Choose a supported material.")
        return value

    @field_validator("furnishing")
    @classmethod
    def known_furnishing(cls, value):
        if value not in CONTENTS:
            raise ValueError("Choose a supported furnishing category.")
        return value


class MaterialSuggestion(RoomMaterials):
    confidence: float = Field(ge=0, le=1)


def suggest_materials(directory, rooms, report, settings, object_evidence=None):
    from langchain_core.messages import HumanMessage
    from PIL import Image

    model = settings.structured(MaterialSuggestion, max_tokens=1400)
    prompt = (
        "Label this indoor room for an acoustic simulation. The image shows the ceiling, floor, "
        "and four wall views in that order. Choose floor, ceiling and wall materials from: "
        + ", ".join(f"{key} ({value['name']})" for key, value in MATERIALS.items())
        + ". Choose furnishing from: " + ", ".join(CONTENTS)
        + ". Glazed tile on a floor or wall (bathrooms, kitchens) is ceramic_tile, not vinyl_tile; if tile covers only "
        "part of the walls, choose the material covering most of the wall area."
        + " Estimate visible glass in square metres. Use low confidence when evidence is unclear."
    )
    suggestions = {}
    with Image.open(directory / "room_sheet.jpg") as sheet:
        height = sheet.height // len(rooms)
        for index, room in enumerate(rooms):
            if not room.get("panorama_available", True):
                continue
            report(f"Suggesting materials for room {index + 1} of {len(rooms)}")
            row = sheet.crop((0, index * height, sheet.width, (index + 1) * height))
            image = io.BytesIO()
            row.save(image, format="JPEG")
            evidence = (object_evidence or {}).get(room["id"], {})
            objects = ", ".join(evidence.get("objects", [])) or "none reported"
            candidates = ", ".join(evidence.get("candidates", [])) or "none reported"
            message = HumanMessage(content=[
                {"type": "image", "mime_type": "image/jpeg",
                 "base64": base64.b64encode(image.getvalue()).decode("ascii")},
                {"type": "text", "text": prompt + f" Floor area: {room['area_m2']} m². "
                 f"Wall area: {room['perimeter_m'] * room['height_m']:.1f} m². "
                 f"YOLO object hints: {objects}. Lower confidence candidates: {candidates}. "
                 "Check these hints against the images."},
            ])
            try:
                suggestion = model.invoke([message])
            except ValueError:
                logger.warning("Unusable material suggestion for room %s", room["id"], exc_info=True)
                continue
            except Exception:
                logger.exception("Material suggestion failed for room %s", room["id"])
                report("The vision model could not finish. Complete the missing labels in the review form.")
                break
            if suggestion is not None:
                suggestions[room["id"]] = suggestion.model_dump()
    return suggestions
