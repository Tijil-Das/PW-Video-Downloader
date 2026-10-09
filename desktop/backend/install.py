"""Single dependency installer for the PW Downloader desktop app.

start.bat runs this on every launch; it installs anything missing and
exits 0 only when every import works. Python + Node sides both covered.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parent
FRONTEND = ROOT / "desktop" / "frontend"

PY_DEPS = ["pywebview", "websockets", "playwright", "requests", "filelock", "pyinstaller"]


def _pip(*args):
    cmd = [sys.executable, "-m", "pip", *args]
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd).returncode == 0


def ensure_python():
    missing = []
    names = {"pywebview": "webview", "websockets": "websockets",
             "playwright": "playwright", "requests": "requests",
             "filelock": "filelock", "pyinstaller": "PyInstaller"}
    for dep in PY_DEPS:
        try:
            __import__(names[dep])
        except Exception:
            missing.append(dep)
    if not missing:
        print("[install] python deps OK (all import)", flush=True)
        return True
    print(f"[install] missing python deps: {missing}", flush=True)
    req = BACKEND / "requirements.txt"
    ok = _pip("install", "-r", str(req)) if req.exists() else _pip("install", *missing)
    if not ok:
        return False
    # Verify everything imports.
    bad = []
    for dep in PY_DEPS:
        try:
            __import__(names[dep])
        except Exception:
            bad.append(dep)
    if bad:
        print(f"[install] STILL missing: {bad}", flush=True)
        return False
    print("[install] python deps OK", flush=True)
    return True


def ensure_node():
    nm = FRONTEND / "node_modules"
    if nm.exists():
        print("[install] node_modules present", flush=True)
        return True
    print("[install] installing frontend deps (npm install)...", flush=True)
    r = subprocess.run(["npm", "install", "--prefix", str(FRONTEND)])
    if r.returncode != 0 or not nm.exists():
        print("[install] npm install FAILED", flush=True)
        return False
    print("[install] frontend deps OK", flush=True)
    return True


def main():
    ok = ensure_python() and ensure_node()
    print("[install] ALL READY" if ok else "[install] FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
