"""Loading the preset and resolving its paths."""

import json
import os
import re
from pathlib import Path

DEFAULT_PRESET = Path(__file__).with_name("preset.json")


def load_preset(path=None):
    path = Path(path) if path else DEFAULT_PRESET
    with open(path, encoding="utf-8") as fh:
        preset = json.load(fh)
    if preset.get("schema") != 1:
        raise ValueError(f"{path}: unsupported preset schema {preset.get('schema')!r}")
    preset["_path"] = str(path)
    return preset


def expand_path(value):
    """Expand ~ and both %NAME% and $NAME style environment variables."""
    value = re.sub(r"%([^%]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), value)
    return Path(os.path.expandvars(os.path.expanduser(value)))


def output_dir(preset):
    return expand_path(preset["capture"]["output_dir"])


def pass_specs(preset):
    return preset["capture"]["passes"]
