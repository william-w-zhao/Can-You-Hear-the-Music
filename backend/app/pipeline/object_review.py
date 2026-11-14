"""Optional LangChain second opinion on two YOLO detections."""
from base64 import b64encode
from io import BytesIO
from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field

from app.pipeline.vision import SHEET_MARGIN, VIEWS


class MatchSuggestion(BaseModel):
    decision: Literal["same", "separate", "unsure"]
    reason: str = Field(description="Briefly explain the visual evidence and any uncertainty.")


def suggest_match(directory, hits, settings):
    from langchain_core.messages import HumanMessage

    content = [{"type": "text", "text": (
        "Compare the two image crops of YOLO detections in a single Matterport panorama. "
        "Decide whether they depict the same physical object, separate objects, or whether "
        "the evidence is insufficient. Similar class labels alone are insufficient. "
        "The crops include a little surrounding context."
    )}]
    with Image.open(directory / "room_sheet.jpg") as sheet:
        for hit in hits:
            left, top, right, bottom = hit["sheet_box_px"]
            padding = 10
            # Pad inside the same face only, so the neighboring photo can't leak into the crop.
            x = round(left - hit["box_px"][0])
            y = round(top - hit["box_px"][1])
            face_size = (sheet.width - SHEET_MARGIN) // len(VIEWS)
            crop = sheet.crop((max(x, int(left) - padding), max(y, int(top) - padding),
                               min(x + face_size, int(right) + padding), min(y + face_size, int(bottom) + padding)))
            buffer = BytesIO()
            crop.save(buffer, format="PNG")
            content.extend([
                {"type": "text", "text": f"{hit['label']} · {hit['view']}"},
                {"type": "image", "mime_type": "image/png", "base64": b64encode(buffer.getvalue()).decode("ascii")},
            ])
    return settings.structured(MatchSuggestion, max_tokens=1200).invoke([HumanMessage(content=content)])
