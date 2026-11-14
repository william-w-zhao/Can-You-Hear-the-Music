"""Project paths and API key lookup."""
import os
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]      # backend/
ROOT = BACKEND.parent                               # project root
FRONTEND = ROOT / "frontend"
AUDIO = FRONTEND / "public" / "audio"
KIT = ROOT / "costar-hackathon-kit"
DATA = ROOT / "data"                                # shared cache: data/<sid>/
ENV_FILES = [ROOT / ".env", ROOT / "key-check" / ".env"]


def secret(name: str, required: bool = True) -> str | None:
    """Environment first, then the .env files. Never log the value."""
    value = os.environ.get(name, "").strip()
    for f in ENV_FILES:
        if value:
            break
        if f.exists():
            for line in f.read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() == name:
                    value = v.strip().strip('"').strip("'")
    if not value and required:
        raise RuntimeError(f"{name} is not set (environment or {', '.join(map(str, ENV_FILES))})")
    return value or None
