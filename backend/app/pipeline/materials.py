"""Validate room materials and optionally propose them from panorama contact sheets."""
import base64
import io

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.pipeline.acoustics import CONTENTS, MATERIALS
from app.sources.config import secret


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


def suggest_materials(directory, rooms, report):
    from anthropic import Anthropic, APIError
    from PIL import Image

    model = secret("ANTHROPIC_MODEL", required=False) or "claude-haiku-5-5"
    prompt = (
        "Label this indoor room for an acoustic simulation. The image shows the ceiling, floor, "
        "and four wall views in that order. Return only a JSON object with keys type, floor, ceiling, "
        "walls, furnishing, glass_m2, confidence. Choose floor, ceiling and walls only from: "
        + ", ".join(f"{key} ({value['name']})" for key, value in MATERIALS.items())
        + ". Choose furnishing from: " + ", ".join(CONTENTS)
        + ". Estimate total visible glass area in square metres. Set confidence between 0 and 1, "
        "using low confidence if any surface or the amount of glass is uncertain."
    )
    suggestions = {}
    with Anthropic(api_key=secret("ANTHROPIC_API_KEY"), timeout=45, max_retries=1) as client:
        with Image.open(directory / "room_sheet.jpg") as sheet:
            for index, room in enumerate(rooms):
                if not room.get("panorama_available", True):
                    continue
                report(f"Suggesting materials for room {index + 1} of {len(rooms)}")
                height = sheet.height // len(rooms)
                row = sheet.crop((0, index * height, sheet.width, (index + 1) * height))
                image = io.BytesIO()
                row.save(image, format="JPEG")
                try:
                    response = client.messages.create(
                        model=model, max_tokens=500,
                        messages=[{"role": "user", "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                       "data": base64.b64encode(image.getvalue()).decode("ascii")}},
                            {"type": "text", "text": prompt + f" Floor area: {room['area_m2']} m². "
                             f"Wall area: {room['perimeter_m'] * room['height_m']:.1f} m²."},
                        ]}],
                    )
                except APIError:
                    report("Claude did not return suggestions for all rooms. Complete the labels in the review form.")
                    break
                reply = "".join(block.text for block in response.content if block.type == "text").strip()
                if reply.startswith("```") and reply.endswith("```"):
                    reply = reply.partition("\n")[2][:-3].strip()
                try:
                    suggestion = MaterialSuggestion.model_validate_json(reply)
                except ValueError:
                    continue
                suggestions[room["id"]] = suggestion.model_dump()
    return suggestions
