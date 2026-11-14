"""Read per-scan JSON for the cached building API."""
import json
from pathlib import Path

from fastapi import HTTPException

from app.sources.config import DATA


def scan_directory(sid: str) -> Path:
    if not sid.isascii() or not sid.isalnum():
        raise HTTPException(404, "Unknown scan")
    return DATA / sid


def read_scan_file(sid: str, filename: str) -> dict:
    try:
        return json.loads((scan_directory(sid) / filename).read_text())
    except FileNotFoundError as exc:
        raise HTTPException(404, "Cached analysis unavailable for this scan") from exc
