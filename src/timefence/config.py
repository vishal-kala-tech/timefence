import json
from pathlib import Path


def load_config(path: Path) -> dict:
    with path.open() as f: cfg = json.load(f)

    if cfg.get("version") != 1 or not isinstance(cfg.get("resources"), dict):
        raise ValueError("Unsupported or invalid config")

    return cfg
