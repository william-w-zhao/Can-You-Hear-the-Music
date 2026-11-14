"""Coordinate helpers for building imagery and property records."""
import math

M_PER_DEG = 111_320.0


class Box:
    """A square around a point, in metres, with lon/lat <-> pixel mapping for a north-up image."""

    def __init__(self, lat, lon, half_m, size_px):
        self.lat, self.lon, self.half, self.size = lat, lon, half_m, size_px
        dlat = half_m / M_PER_DEG
        dlon = half_m / (M_PER_DEG * math.cos(math.radians(lat)))
        self.w, self.e, self.s, self.n = lon - dlon, lon + dlon, lat - dlat, lat + dlat
        self.m_per_px = 2 * half_m / size_px

    def wkt(self):
        w, e, s, n = self.w, self.e, self.s, self.n
        return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"

    def px(self, lon, lat):
        return ((lon - self.w) / (self.e - self.w) * self.size, (self.n - lat) / (self.n - self.s) * self.size)

    def lonlat(self, x, y):
        return (self.w + x / self.size * (self.e - self.w), self.n - y / self.size * (self.n - self.s))

    def as_dict(self):
        return {"lat": self.lat, "lon": self.lon, "half_m": self.half, "size_px": self.size,
                "m_per_px": self.m_per_px, "w": self.w, "e": self.e, "s": self.s, "n": self.n}


def dist_m(lat1, lon1, lat2, lon2):
    return math.hypot((lat2 - lat1) * M_PER_DEG, (lon2 - lon1) * M_PER_DEG * math.cos(math.radians(lat1)))
