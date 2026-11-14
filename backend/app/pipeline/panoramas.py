"""Download and cache the original Matterport panorama faces used in room sheets."""
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests
from PIL import Image, ImageChops, ImageStat

from app.sources.matterport import mp

Q_SKY = """query($id: ID!) { model(id: $id) { panoLocations { id skybox(resolution: "2k") { children } } } }"""


def skyboxes(sid):
    return {pano["id"]: (pano.get("skybox") or {}).get("children")
            for pano in mp(Q_SKY, id=sid)["model"]["panoLocations"]}


def face_path(directory, room, face_index):
    panorama = room.get("sheet_panorama_id") or "legacy"
    return directory / "room_photos" / f"{room['id']}-{panorama}-{face_index}.jpg"


def download_face(url):
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    with Image.open(BytesIO(response.content)) as image:
        return image.convert("RGB"), response.content if image.format == "JPEG" else None


def save_face(path, image, jpeg):
    path.parent.mkdir(exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            if jpeg is None:
                image.save(stream, format="JPEG", quality=95)
            else:
                stream.write(jpeg)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def recover_face(directory, room, face_index, thumbnail, sky):
    """Verify a recovered face against the saved thumbnail before reusing its boxes."""
    pano = room.get("sheet_panorama_id") or next(
        (pano for pano in room["panos"] if len(sky.get(pano) or []) == 6), None
    )
    if not pano or len(sky.get(pano) or []) != 6:
        return None
    image, jpeg = download_face(sky[pano][face_index])
    difference = ImageChops.difference(image.resize(thumbnail.size), thumbnail)
    # The original contact sheet was JPEG-compressed, so pixel values differ slightly.
    if max(ImageStat.Stat(difference).mean) > 15:
        return None
    path = face_path(directory, room, face_index)
    save_face(path, image, jpeg)
    return path
