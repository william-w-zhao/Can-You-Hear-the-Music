"""Vexcel orthoimagery for a building and its surroundings."""
import time

import requests

from app.sources.config import secret
from app.sources.imagery import save_jpg

VEXCEL = "https://api.vexcelgroup.com/v2"


def fetch_vexcel(box, outdir, bundle):
    print("Vexcel: ortho clip")
    t = time.time()
    r = requests.post(f"{VEXCEL}/ortho/extract", headers={"X-API-KEY": secret("VEXCEL_API_KEY")}, timeout=300, json={
        "wkt": box.wkt(), "srid": 4326, "layer": "urban,urban-r,wide-area,urban-g", "crop": "bounding_box",
        "image-format": "png", "destination-dimensions": f"{box.size},{box.size}", "attribution": "false"})
    if r.status_code in (401, 403):
        raise RuntimeError(f"Vexcel answered {r.status_code} (key, or location outside Houston/LA)")
    r.raise_for_status()
    (outdir / "ortho.png").write_bytes(r.content)
    save_jpg(r.content, outdir / "ortho.jpg", 1600, quality=88)
    bundle["vexcel"] = {"box": box.as_dict(), "bytes": len(r.content), "seconds": round(time.time() - t, 1),
                        "layer": "urban,urban-r,wide-area,urban-g", "capture_time": None,
                        "note": "The ortho extract returns no capture date or time."}
