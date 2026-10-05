"""Detect the PW capturer extension across ALL Chrome profiles.

METHOD 1 — parse <Profile>/Preferences JSON, look under
  extensions.settings for our extension ID (location==4 => unpacked).
METHOD 2 — check <Profile>/Local Extension Settings/<EXTENSION_ID>/ exists.
Falls back to path-match when the unpacked ID is unknown/rotated.
"""
import json
import os
from pathlib import Path

PREF_PROFILES = ["Default"] + [f"Profile {i}" for i in range(1, 10)]


def _user_data_dir():
    base = os.environ.get("LOCALAPPDATA", "")
    return Path(base) / "Google" / "Chrome" / "User Data"


def _existing_profiles(user_data):
    found = []
    for name in PREF_PROFILES:
        if (user_data / name / "Preferences").exists():
            found.append(name)
    if not found and user_data.exists():
        for child in user_data.iterdir():
            if child.is_dir() and (child / "Preferences").exists():
                found.append(child.name)
    return found or ["Default"]


def _norm(p):
    try:
        return str(Path(p).resolve()).lower()
    except Exception:
        return str(p).lower()


def detect_extension(extension_id="", extension_path=""):
    user_data = _user_data_dir()
    profiles_hit, methods = [], set()
    ext_path, entry_path = "", ""
    want_id = (extension_id or "").strip().lower()

    for profile in _existing_profiles(user_data):
        prof_dir = user_data / profile
        # METHOD 1 — Preferences JSON
        try:
            prefs = json.loads((prof_dir / "Preferences").read_text(encoding="utf-8"))
            settings = prefs.get("extensions", {}).get("settings", {})
            if want_id and want_id in {k.lower(): k for k in settings}:
                key = next(k for k in settings if k.lower() == want_id)
                entry = settings[key] or {}
                profiles_hit.append(profile)
                methods.add("preferences")
                entry_path = str(entry.get("path", ""))
                if entry.get("location") == 4:
                    ext_path = entry_path or ext_path
            elif extension_path:
                # Unpacked IDs rotate: match by install path instead.
                want = _norm(extension_path)
                for key, entry in settings.items():
                    p = str((entry or {}).get("path", ""))
                    if p and (want in _norm(p) or _norm(p) in want):
                        profiles_hit.append(profile)
                        methods.add("preferences")
                        ext_path = p
                        want_id = want_id or key.lower()
                        break
        except Exception:
            pass
        # METHOD 2 — Local Extension Settings folder
        if want_id:
            try:
                folder = prof_dir / "Local Extension Settings" / want_id
                if folder.exists():
                    if profile not in profiles_hit:
                        profiles_hit.append(profile)
                    methods.add("local_storage")
            except Exception:
                pass

    profiles_hit = sorted(set(profiles_hit))
    installed = bool(profiles_hit)
    if not installed and extension_path and Path(extension_path).exists():
        ext_path = ext_path or extension_path
    return {
        "installed": installed,
        "profiles": profiles_hit,
        "extension_id": extension_id or (want_id or ""),
        "extension_path": ext_path or extension_path,
        "detection_method": "+".join(sorted(methods)) if methods else (
            "both" if False else ("preferences" if methods else "none")),
    }
