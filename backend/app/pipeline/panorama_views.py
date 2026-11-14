"""Perspective views of one room's panorama with detection boxes drawn on, for people and the review agent.

Each panorama is a cube of six square faces (0 up, 1-4 around, 5 down; see matterport.equirect()). A box on one
face is a patch of directions from the camera. To show two boxes that may be one object, we point a virtual
camera between them and resample the cube, so an object split across a face edge looks continuous again.
"""
from io import BytesIO
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.pipeline.panoramas import face_path
from app.pipeline.vision import FACE_ORDER, SHEET_MARGIN

COLORS = ((235, 104, 52), (42, 120, 214), (27, 175, 122), (220, 50, 130))
TAGS = "ABCD"


def face_images(directory, outline, row, size):
    """The six faces as arrays: cached originals where available, else upscaled contact-sheet thumbnails."""
    faces, sheet = {}, None
    for face in range(6):
        path = face_path(directory, outline, face)
        if path.is_file():
            with Image.open(path) as image:
                faces[face] = np.asarray(image.convert("RGB"))
            continue
        if sheet is None:
            with Image.open(directory / "room_sheet.jpg") as image:
                sheet = image.convert("RGB")
        x, y = SHEET_MARGIN + FACE_ORDER.index(face) * size, row * size
        faces[face] = np.asarray(sheet.crop((x, y, x + size, y + size)).resize((size * 4, size * 4), Image.BICUBIC))
    return faces


def to_direction(face, u, v):
    """Face coordinates in [-1, 1] (u right, v down) -> unit direction vectors (y up, z = face 1)."""
    one = np.ones_like(u)
    x, y, z = {
        0: (u, one, v), 1: (u, -v, one), 2: (one, -v, -u),
        3: (-u, -v, -one), 4: (-one, -v, u), 5: (u, -one, -v),
    }[face]
    vectors = np.stack([x, y, z], axis=-1)
    return vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)


def sample(faces, directions):
    """Colour seen in each direction (nearest pixel of the matching cube face)."""
    x, y, z = directions[..., 0], directions[..., 1], directions[..., 2]
    ax, ay, az = np.abs(x), np.abs(y), np.abs(z)
    out = np.zeros(directions.shape[:-1] + (3,), np.uint8)
    with np.errstate(divide="ignore", invalid="ignore"):
        for face, mask, u, v in (
            (1, (az >= ax) & (az >= ay) & (z > 0), x / az, -y / az),
            (2, (ax >= ay) & (ax >= az) & (x > 0), -z / ax, -y / ax),
            (3, (az >= ax) & (az >= ay) & (z < 0), -x / az, -y / az),
            (4, (ax >= ay) & (ax >= az) & (x < 0), z / ax, -y / ax),
            (0, (ay >= ax) & (ay >= az) & (y > 0), x / ay, z / ay),
            (5, (ay >= ax) & (ay >= az) & (y < 0), x / ay, -z / ay),
        ):
            image = faces[face]
            n = image.shape[0]
            col = np.clip(((u[mask] + 1) / 2 * n).astype(int), 0, n - 1)
            row = np.clip(((v[mask] + 1) / 2 * n).astype(int), 0, n - 1)
            out[mask] = image[row, col]
    return out


def box_outline(hit, size, steps=24):
    """Directions around the box's edge, in order, so the outline can be drawn as one closed line."""
    left, top, right, bottom = hit["box_px"]
    t = np.linspace(0, 1, steps, endpoint=False)
    xs = np.concatenate([left + (right - left) * t, np.full(steps, right), right - (right - left) * t, np.full(steps, left)])
    ys = np.concatenate([np.full(steps, top), top + (bottom - top) * t, np.full(steps, bottom), bottom - (bottom - top) * t])
    return to_direction(hit["face_index"], xs / size * 2 - 1, ys / size * 2 - 1)


def render(directory, outline, row, size, hits, *, width=960, height=640):
    """JPEG bytes: a view framing all `hits`, each outlined and tagged A, B, ... with its label."""
    faces = face_images(directory, outline, row, size)
    rings = [box_outline(hit, size) for hit in hits]
    centres = [ring.mean(axis=0) for ring in rings]
    forward = np.sum([c / np.linalg.norm(c) for c in centres], axis=0)
    forward /= np.linalg.norm(forward)
    up = np.array([0.0, 1.0, 0.0]) if abs(forward[1]) < 0.9 else np.array([0.0, 0.0, -1.0])
    right = np.cross(up, forward)
    right /= np.linalg.norm(right)
    up = np.cross(forward, right)
    basis = np.stack([right, up, forward])

    # Fit every outline inside the frame with a margin, between a 50° and 140° horizontal field of view.
    points = np.concatenate(rings) @ basis.T
    ahead = points[points[:, 2] > 0.05]
    reach_x = np.max(np.abs(ahead[:, 0] / ahead[:, 2])) if len(ahead) else 1.0
    reach_y = np.max(np.abs(ahead[:, 1] / ahead[:, 2])) if len(ahead) else 1.0
    focal = min(0.40 * width / max(reach_x, 1e-3), 0.40 * height / max(reach_y, 1e-3))
    focal = float(np.clip(focal, (width / 2) / math.tan(math.radians(70)), (width / 2) / math.tan(math.radians(25))))

    px, py = np.meshgrid(np.arange(width) + 0.5, np.arange(height) + 0.5)
    rays = (right * ((px - width / 2) / focal)[..., None] + up * ((height / 2 - py) / focal)[..., None] + forward)
    image = Image.fromarray(sample(faces, rays / np.linalg.norm(rays, axis=-1, keepdims=True)))

    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("Arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    for index, (hit, ring) in enumerate(zip(hits, rings)):
        colour = COLORS[index % len(COLORS)]
        local = ring @ basis.T
        visible = local[:, 2] > 0.05
        xy = [(width / 2 + focal * x / z, height / 2 - focal * y / z) if ok else None
              for (x, y, z), ok in zip(local, visible)]
        segment = []
        for point in xy + xy[:1]:
            if point is None:
                if len(segment) > 1:
                    draw.line(segment, fill=colour, width=4)
                segment = []
            else:
                segment.append(point)
        if len(segment) > 1:
            draw.line(segment, fill=colour, width=4)
        shown = [p for p in xy if p is not None]
        if shown:
            x0 = min(p[0] for p in shown)
            y0 = min(p[1] for p in shown)
            tag = f"{TAGS[index % len(TAGS)]} · {hit['label']}"
            box = draw.textbbox((x0, y0), tag, font=font)
            tx, ty = max(0, min(width - (box[2] - box[0]) - 8, x0)), max(0, y0 - (box[3] - box[1]) - 10)
            draw.rectangle((tx, ty, tx + box[2] - box[0] + 8, ty + box[3] - box[1] + 8), fill=colour)
            draw.text((tx + 4, ty + 2), tag, fill=(255, 255, 255), font=font)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()
