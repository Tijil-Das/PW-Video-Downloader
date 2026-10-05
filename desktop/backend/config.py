"""Settings load/save for the PW desktop app (separate from watcher config)."""
import json
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
DESKTOP_CFG = BACKEND_DIR / "config.json"
WATCHER_CFG = BACKEND_DIR.parents[1] / "downloader" / "config.json"
EXTENSION_DIR = BACKEND_DIR.parents[1] / "extension"

DEFAULTS = {
    "ws_port": 9777,
    "auto_start_server": True,
    "extension_id": "",
    "extension_path": str(EXTENSION_DIR),
}


def _seed_from_watcher():
    try:
        if WATCHER_CFG.exists():
            return json.loads(WATCHER_CFG.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def load_config():
    cfg = dict(DEFAULTS)
    cfg.update(_seed_from_watcher())
    # Re-assert desktop keys (watcher file must not clobber them).
    for k, v in DEFAULTS.items():
        if k not in cfg:
            cfg[k] = v
    try:
        if DESKTOP_CFG.exists():
            saved = json.loads(DESKTOP_CFG.read_text(encoding="utf-8"))
            cfg.update(saved)
    except Exception:
        pass
    if not cfg.get("extension_path"):
        cfg["extension_path"] = str(EXTENSION_DIR)
    return cfg


def save_config(config):
    DESKTOP_CFG.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config
