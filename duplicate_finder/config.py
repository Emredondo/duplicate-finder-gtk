# SPDX-License-Identifier: GPL-3.0-or-later
from copy import deepcopy
from pathlib import Path
import json
import os
import tempfile

DEFAULTS = {
    "folder": str(Path.home()), "view": "tree", "width": 1120, "height": 720,
    "x": None, "y": None, "maximized": False, "columns": {},
    "criterion": "oldest", "priority": "", "hidden": False, "recursive": True,
    "exclusions": ".Trash\n.Trash-*",
}


def config_path():
    root = os.environ.get("XDG_CONFIG_HOME", "")
    if not os.path.isabs(root):
        root = str(Path.home() / ".config")
    return Path(root) / "duplicate-finder-gtk" / "preferences.json"


def load(path=None):
    values = deepcopy(DEFAULTS)
    try:
        data = json.loads((path or config_path()).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return values
        for key, default in DEFAULTS.items():
            value = data.get(key, default)
            if default is None:
                if value is None or (type(value) is int and -100000 < value < 100000):
                    values[key] = value
            elif type(value) is type(default):
                values[key] = value
        values["width"] = min(4000, max(800, values["width"]))
        values["height"] = min(2400, max(550, values["height"]))
        if values["view"] not in ("tree", "table"):
            values["view"] = "tree"
        if values["criterion"] not in ("oldest", "newest", "priority"):
            values["criterion"] = "oldest"
        values["columns"] = {str(k): min(1200, max(45, v)) for k, v in values["columns"].items()
                             if type(v) is int}
    except (OSError, ValueError, TypeError):
        pass
    return values


def save(values, path=None):
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".preferences-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(values, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
