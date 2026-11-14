"""Project paths and API key lookup."""
import os
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]      # backend/
ROOT = BACKEND.parent                               # project root
FRONTEND = ROOT / "frontend"
AUDIO = FRONTEND / "public" / "audio"
KIT = ROOT / "costar-hackathon-kit"
DATA = ROOT / "data"                                # shared cache: data/<sid>/
ENV_FILE = ROOT / ".env"


def secret(name: str, required: bool = True) -> str | None:
    """Read from the shell first, then from the project root's .env."""
    value = os.environ.get(name, "").strip()
    if not value and ENV_FILE.is_file():
        for line in ENV_FILE.read_text().splitlines():
            key, separator, configured = line.partition("=")
            if separator and key.strip() == name:
                value = configured.strip().strip('"').strip("'")
    if not value and required:
        raise RuntimeError(f"{name} is not set (environment or {ENV_FILE})")
    return value or None
