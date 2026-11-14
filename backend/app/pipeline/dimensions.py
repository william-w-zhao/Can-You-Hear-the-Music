"""Read horizontal room spans from the scaled floor plan, independent of photos."""
from math import isfinite

import numpy as np
from scipy.spatial import ConvexHull, QhullError


def room_spans(polygon, pixels_per_metre):
    """Return the long and short sides of the smallest rectangle around an outline."""
    if not pixels_per_metre or not isfinite(pixels_per_metre) or pixels_per_metre <= 0:
        return None
    points = np.asarray(polygon, dtype=float)
    if len(points) < 3 or not np.isfinite(points).all():
        return None
    try:
        hull = points[ConvexHull(points).vertices]
    except QhullError:
        return None
    edges = np.roll(hull, -1, axis=0) - hull
    axes = edges / np.linalg.norm(edges, axis=1, keepdims=True)
    along = np.ptp(hull @ axes.T, axis=0)
    across = np.ptp(hull @ np.stack((-axes[:, 1], axes[:, 0])), axis=0)
    index = int(np.argmin(along * across))
    return tuple(round(float(span / pixels_per_metre), 2) for span in
                 sorted((along[index], across[index]), reverse=True))


def room_dimensions(room, geometry):
    spans = room_spans(room.get("polygon_px") or [], (geometry.get("floorplan") or {}).get("resolution"))
    footprint_source = "point_cloud" if geometry.get("method", "").startswith("point-cloud") else "matterport"
    if room.get("height_measured"):
        height_source = "matterport"
    else:
        height_source = room.get("height_source") or (
            "point_cloud_estimate" if footprint_source == "point_cloud" else "assumed"
        )
    return {
        "length_m": spans[0] if spans else None,
        "width_m": spans[1] if spans else None,
        "height_m": room.get("height_m"),
        "area_m2": room.get("area_m2"),
        "volume_m3": room.get("volume_m3"),
        "footprint_source": footprint_source,
        "height_source": height_source,
    }
