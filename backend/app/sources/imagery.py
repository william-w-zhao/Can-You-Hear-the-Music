"""HTTP downloads and JPEG conversion shared by imagery sources."""
import io

import requests
from PIL import Image


def get(url, **kw):
    r = requests.get(url, timeout=120, **kw)
    r.raise_for_status()
    return r.content


def save_jpg(data_or_img, path, max_w=None, quality=86):
    img = data_or_img if isinstance(data_or_img, Image.Image) else Image.open(io.BytesIO(data_or_img))
    img = img.convert("RGB")
    if max_w and img.width > max_w:
        img = img.resize((max_w, round(img.height * max_w / img.width)), Image.LANCZOS)
    img.save(path, quality=quality)
    return img.size
