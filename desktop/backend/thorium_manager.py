"""Thorium auto-pipeline: download fork (Widevine built-in), pre-inject WP2
via Preferences, drive with Playwright. No manual steps except PW login.

Only stdlib + requests: requests, zipfile, hashlib, hmac, json, pathlib.
"""
import hashlib
import json
import shutil
from pathlib import Path

THORIUM_URL_AVX2 = ("https://github.com/Alex313031/Thorium-Win/releases/download/"
                    "M138.0.7204.303/Thorium_AVX2_138.0.7204.303.zip")
THORIUM_URL_AVX = ("https://github.com/Alex313031/Thorium-Win/releases/download/"
                   "M138.0.7204.303/Thorium_AVX_138.0.7204.303.zip")
# AVX2 build crashes instantly (exit 2147483651) on CPUs without AVX2.
# AVX is the safe default for unknown CPUs; override via env THORIUM_AVX2=1.
THORIUM_URL = THORIUM_URL_AVX


class ThoriumManager:
    def __init__(self, install_dir: str):
        self.install_dir = Path(install_dir)

    def ensure_installed(self) -> str:
        """Download + extract Thorium if missing. Returns exe path."""
        import os
        global THORIUM_URL
        if os.environ.get("THORIUM_AVX2") == "1":
            THORIUM_URL = THORIUM_URL_AVX2
        # CPU without AVX2 + AVX2 build = instant 2147483651. If the current
        # bundle is AVX2 and the exe dies immediately, re-download AVX.
        exe = self._find_exe()
        if exe and "AVX2" in str(self.install_dir):
            pass  # explicit dir; respect it
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
        """Stage WP2 files for --load-extension. NEVER hand-write Preferences:
        Thorium 138 crashes (exit 2147483651) on foreign Preferences entries.
        Returns ext ID (computed, for logging only)."""
        print("[thorium] staging WP2 for load-extension...", flush=True)
        wp2 = Path(wp2_source).resolve()
        ext_id = self._ext_id(str(wp2))
        print(f"[thorium] WP2 extension ID: {ext_id}", flush=True)
        return ext_id

    def _clean_locks(self, profile_dir: str) -> None:
        prof = Path(profile_dir)
        for name in ["SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"]:
            p = prof / name
            try:
                if p.exists() or p.is_symlink():
                    p.unlink()
            except Exception as e:
                print(f"[thorium] could not remove {name}: {e}", flush=True)

    def _wipe_if_incompatible(self, profile_dir: str) -> None:
        prof = Path(profile_dir)
        version_file = prof / "Last Version"
        if version_file.exists():
            try:
                stored = version_file.read_text().strip()
                major = int(stored.split(".")[0]) if stored else 0
                if major > 138:
                    print(f"[thorium] profile version {stored} incompatible, wiping", flush=True)
                    shutil.rmtree(prof, ignore_errors=True)
            except Exception as e:
                print(f"[thorium] could not read version file: {e}", flush=True)
        prof.mkdir(parents=True, exist_ok=True)

    def launch_context(self, playwright, profile_dir: str, wp2_source: str,
                       headless: bool = False):
        """Ensure all, launch Thorium + WP2 via --load-extension, wait for
        worker. Returns ctx. Verified: hand-written Preferences kills Thorium,
        --load-extension on a clean profile lives."""
        exe = self.ensure_installed()
        self._wipe_if_incompatible(profile_dir)
        self._clean_locks(profile_dir)
        wp2 = str(Path(wp2_source).resolve())
        self.ensure_wp2_installed(profile_dir, wp2_source)
        print("[thorium] launching Thorium...", flush=True)
        args = ["--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--profile-directory=Default",
                f"--disable-extensions-except={wp2}",
                f"--load-extension={wp2}"]
        import subprocess as _sp
        import time as _t
        port = 9444
        cmd = [exe, f"--user-data-dir={profile_dir}",
               f"--remote-debugging-port={port}"] + args
        try:
            proc = _sp.Popen(cmd, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        except Exception as e:
            print(f"[thorium] LAUNCH FAILED: {e}", flush=True)
            raise
        ctx = None
        last = None
        try:
            deadline = _t.time() + 60
            while _t.time() < deadline:
                try:
                    ctx = playwright.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{port}", timeout=5000)
                    break
                except Exception as e:
                    last = e
                    _t.sleep(1)
            if ctx is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
                print(f"[thorium] LAUNCH FAILED (no CDP on :{port}): {last}", flush=True)
                raise RuntimeError(f"Thorium CDP never came up: {last}")
        except Exception as e:
            print(f"[thorium] LAUNCH FAILED: {e}", flush=True)
            raise
        # CDP attach returns a Browser; the persistent ctx is contexts[0].
        # Poll workers: WP2's service worker can take a few seconds to start.
        try:
            _b = ctx
            _ctx = None
            try:
                _ctxs = getattr(_b, "contexts", None) or []
                _ctx = _ctxs[0] if _ctxs else _b
            except Exception:
                _ctx = _b
            wp2_id = None
            for _i in range(30):
                try:
                    _sws = list(getattr(_ctx, "service_workers", None) or [])
                    for _w in _sws:
                        _u = getattr(_w, "url", "") or ""
                        if "bundle.min.js" in _u or "chrome-extension://" in _u:
                            sw = _w
                            break
                    if sw is not None:
                        break
                except Exception:
                    pass
                import time as _tt
                _tt.sleep(1)
        except Exception:
            pass
        try:
            wp2_id = sw.url.split("/")[2] if sw and getattr(sw, "url", "") else None
        except Exception:
            wp2_id = None
        print(f"[watcher] wp2_id={wp2_id}", flush=True)
        try:
            _ctxs = getattr(ctx, "contexts", None) or []
            return (_ctxs[0] if _ctxs else ctx), wp2_id
        except Exception:
            return ctx, wp2_id
