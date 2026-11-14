"""Shared paths, key loading, Matterport GraphQL and small geo helpers (used by explorer/ and acoustics/)."""
import math
import os
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent          # shared/
ROOT = HERE.parent                              # project root
KIT = ROOT / "costar-hackathon-kit"
DATA = ROOT / "data"                            # one cache per model: data/<sid>/, used by both apps
ENV_FILES = [ROOT / ".env", ROOT / "key-check" / ".env"]

MP_API = "https://api.matterport.com/api/models/graph"
VEXCEL = "https://api.vexcelgroup.com/v2"
SITE = os.environ.get("HACKATHON_SITE", "https://beta-app.matterport.com/2026-princeton-hackathon").rstrip("/")
M_PER_DEG = 111_320.0


def secret(name, required=True):
    """Environment first, then explorer/.env, then key-check/.env. Never printed."""
    v = os.environ.get(name, "").strip()
    for f in ENV_FILES:
        if v:
            break
        if f.exists():
            for line in f.read_text().splitlines():
                k, _, val = line.partition("=")
                if k.strip() == name:
                    v = val.strip().strip('"').strip("'")
    if not v and required:
        raise SystemExit(f"{name} is not set (looked in the environment and {', '.join(str(p) for p in ENV_FILES)}).")
    return v or None


_session = None


def mp(query, **variables):
    """Run a Matterport Model API query; return `data`."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.auth = (secret("MATTERPORT_API_KEY"), secret("MATTERPORT_API_TOKEN"))
    r = _session.post(MP_API, json={"query": query, "variables": variables}, timeout=120)
    if r.status_code in (401, 403):
        raise SystemExit(f"Matterport rejected the key (HTTP {r.status_code}).")
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(f"GraphQL error: {body['errors'][0].get('message')}")
    return body["data"]


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
