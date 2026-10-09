"""Thorium auto-pipeline: download fork (Widevine built-in), pre-inject WP2
via Preferences, drive with Playwright. No manual steps except PW login.

Only stdlib + requests: requests, zipfile, hashlib, hmac, json, pathlib.
"""
import hashlib
import json
import shutil
from pathlib import Path

THORIUM_URL = ("https://github.com/Alex313031/Thorium-Win/releases/download/"
               "M138.0.7204.303/Thorium_AVX2_138.0.7204.303.zip")


class ThoriumManager:
    def __init__(self, install_dir: str):
        self.install_dir = Path(install_dir)

    def ensure_installed(self) -> str:
        """Download + extract Thorium if missing. Returns exe path."""
        exe = self._find_exe()
        if exe:
            return str(exe)
        print("[thorium] downloading Thorium v138...", flush=True)
        import requests
        self.install_dir.mkdir(parents=True, exist_ok=True)
        zpath = self.install_dir / "thorium.zip"
        with requests.get(THORIUM_URL, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(zpath, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
        print("[thorium] extracting...", flush=True)
        import zipfile
        with zipfile.ZipFile(zpath) as z:
            z.extractall(self.install_dir)
        try:
            zpath.unlink(missing_ok=True)
        except Exception:
            pass
        exe = self._find_exe()
        if not exe:
            raise RuntimeError("thorium.exe not found after extract")
        print(f"[thorium] installed: {exe}", flush=True)
        return str(exe)

    def _find_exe(self):
        cands = [self.install_dir / "thorium.exe",
                 self.install_dir / "BIN" / "thorium.exe"]
        for c in cands:
            if c.exists():
                return c
        hits = sorted(self.install_dir.rglob("thorium.exe"))
        return hits[0] if hits else None

    @staticmethod
    def _ext_id(abs_path: str) -> str:
        h = hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:32]
        return "".join(chr(ord("a") + int(c, 16)) for c in h)

    def ensure_wp2_installed(self, profile_dir: str, wp2_source: str) -> str:
        """Pre-inject WP2 into the profile via Preferences. Returns ext ID."""
        print("[thorium] injecting WP2 into profile...", flush=True)
        wp2 = Path(wp2_source).resolve()
        prof = Path(profile_dir)
        ext_id = self._ext_id(str(wp2))
        dest = prof / "Default" / "Extensions" / ext_id / "1.2.7_0"
        dest.mkdir(parents=True, exist_ok=True)
        for item in wp2.iterdir():
            t = dest / item.name
            try:
                if item.is_dir():
                    if t.exists():
                        shutil.rmtree(t, ignore_errors=True)
                    shutil.copytree(item, t)
                else:
                    shutil.copy2(item, t)
            except Exception as e:
                print(f"[thorium] copy skipped {item.name}: {e}", flush=True)
        manifest = json.loads((wp2 / "manifest.json").read_text(encoding="utf-8"))
        prefs_path = prof / "Default" / "Preferences"
        prefs = {}
        if prefs_path.exists():
            try:
                prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
            except Exception:
                prefs = {}
        exts = prefs.setdefault("extensions", {})
        settings = exts.setdefault("settings", {})
        settings[ext_id] = {
            "active_permissions": {
                "api": manifest.get("permissions", []),
                "explicit_host": manifest.get("host_permissions", []),
                "manifest_permissions": [],
                "scriptable_host": [],
            },
            "creation_flags": 38,
            "from_webstore": False,
            "incognito": False,
            "location": 4,
            "manifest": manifest,
            "path": str(wp2),
            "state": 1,
            "was_installed_by_default": False,
            "was_installed_by_oem": False,
        }
        exts.setdefault("ui", {})["developer_mode"] = True
        if prefs.pop("protection", None) is not None:
            print("[thorium] dropped stale Preferences MAC; browser re-signs", flush=True)
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        prefs_path.write_text(json.dumps(prefs), encoding="utf-8")
        print(f"[thorium] WP2 extension ID: {ext_id}", flush=True)
        return ext_id

    def launch_context(self, playwright, profile_dir: str, wp2_source: str,
                       headless: bool = False):
        """Ensure all, launch Thorium + WP2, wait for worker. Returns ctx."""
        exe = self.ensure_installed()
        self.ensure_wp2_installed(profile_dir, wp2_source)
        print("[thorium] launching Thorium...", flush=True)
        ctx = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            executable_path=exe,
            headless=bool(headless),
            args=["--autoplay-policy=no-user-gesture-required",
                  "--mute-audio",
                  "--disable-blink-features=AutomationControlled",
                  "--no-sandbox"])
        sw = None
        try:
            sws = list(getattr(ctx, "service_workers", None) or [])
            sw = sws[0] if sws else ctx.wait_for_event("serviceworker", timeout=15000)
        except Exception:
            pass
        wp2_id = None
        try:
            wp2_id = sw.url.split("/")[2] if sw and getattr(sw, "url", "") else None
        except Exception:
            pass
        print(f"[watcher] wp2_id={wp2_id}", flush=True)
        return ctx, wp2_id
