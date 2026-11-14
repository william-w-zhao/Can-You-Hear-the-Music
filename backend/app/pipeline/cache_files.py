"""Publish cache files atomically for readers in the web app."""
import json
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_json(path, value):
    with NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=1, allow_nan=False)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
