import os
from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy config.example.yaml to config.yaml and fill in credentials."
        )
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    # Expand ~ in paths
    cfg["drafts_path"] = str(Path(cfg["drafts_path"]).expanduser())
    cfg["site_path"] = str(Path(cfg["site_path"]).expanduser())

    return cfg
