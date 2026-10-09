"""pywebview entry + js_api bridge (React <-> Python)."""
import json
import threading
from pathlib import Path
from queue import Queue

import webview
from server import BridgeServer
from downloader import Downloader
from chrome_detect import detect_extension
from config import load_config, save_config

# FIX 1: UI-thread JS queue. Background threads only push_js(); the
# main-thread _drain_js() (via webview.start(func=...)) performs the
# actual window.evaluate_js. Never touch window from workers.
_js_queue = Queue()
_window_ref = None


def push_js(js: str):
    _js_queue.put(js)  # callable from ANY thread


def _drain_js():
    # Runs on a timer; evaluate_js itself marshals via Invoke.
    # Background threads must NEVER touch window directly — only push_js().
    while not _js_queue.empty():
        try:
            if _window_ref is not None:
                _window_ref.evaluate_js(_js_queue.get_nowait())
            else:
                _js_queue.get_nowait()  # window gone: drop
        except Exception as e:
            print("evaluate_js failed:", e)
    threading.Timer(0.05, _drain_js).start()


class Api:
    # NOTE: pywebview scans window._js_api via dir()+getattr and RECURSES
    # into every non-callable attr having __module__ (util.get_functions).
    # So Api must expose ONLY plain methods: every reference (config,
    # downloader, server, window) lives behind an underscore name, which
    # the scanner skips. A public `window`/`downloader` attr let the scan
    # crawl Window.native COM objects off the UI thread -> the
    # CoreWebView2/AccessibilityObject.Bounds.Empty... spam + hung UI.
    def __init__(self):
        self._config = load_config()
        self._downloader = Downloader(self._config, self._on_status)
        self._server = BridgeServer(self._config, self._downloader)

    def attach_window(self, window):
        self._window = window
        global _window_ref
        _window_ref = window

    def _on_status(self, job_id, stage, pct, detail):
        # FIX 1: never touch window here (worker thread). Queue the JS;
        # the timer drain calls evaluate_js (which marshals via Invoke).
        payload = {"jobId": job_id, "stage": stage, "pct": pct, "detail": detail}
        try:
            self._server.broadcast({"type": "status", **payload})
        except Exception:
            pass
        try:
            push_js(f"window.__onJobStatus && window.__onJobStatus({json.dumps(payload)})")
        except Exception:
            pass
        if stage in ("done", "error"):
            jobs = self._downloader.list_jobs()
            rec = next((j for j in jobs if j.get("jobId") == job_id), payload)
            key = "done" if stage == "done" else "error"
            extra = {"path": rec.get("path")} if stage == "done" else {"message": detail}
            try:
                self._server.broadcast({"type": key, "jobId": job_id, **extra})
            except Exception:
                pass

    def check_extension(self):
        return detect_extension(
            self._config.get("extension_id", ""),
            self._config.get("extension_path", ""))

    def start_server(self):
        self._config["ws_port"] = int(self._config.get("ws_port", 9777))
        save_config(self._config)
        self._server.config = self._config
        self._server.start()
        return {"running": True, "port": self.port}

    def stop_server(self):
        self._server.stop()
        return {"running": False}

    @property
    def port(self):
        return int(self._config.get("ws_port", 9777))

    def server_status(self):
        return {"running": self._server.is_running(), "port": self.port}

    def list_jobs(self):
        return self._downloader.list_jobs()

    def list_all_chapters(self):
        from chapter_resolver import list_all_chapters
        return list_all_chapters(self._config.get("batch_slug", ""),
                                 self._config.get("batch_id", ""))

    def refresh_chapters(self):
        from chapter_resolver import clear_cache
        clear_cache()
        return self.list_all_chapters()

    def download_chapter_dpps(self, subject_slug, chapter_slug, subject_name, chapter_name):
        job_id = self._downloader.submit_dpps(subject_slug, chapter_slug, subject_name, chapter_name)
        return {"job_id": job_id, "queued": True}

    def test_storage(self):
        try:
            from storage import Storage
            st = Storage(self._config.get("base_storage_path", ""),
                         self._config.get("batch_name", ""))
            info = st.ensure_chapter_folders("_Test", "_Test")
            probe = Path(info["index_dir"]) / "write_probe.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_settings(self):
        det = self.check_extension()
        if det.get("extension_id") and not self._config.get("extension_id"):
            self._config["extension_id"] = det["extension_id"]
        return {**self._config, "detection": det}

    def save_settings(self, patch):
        patch = dict(patch or {})
        if "ws_port" in patch:
            patch["ws_port"] = int(patch["ws_port"])
        self._config.update(patch)
        save_config(self._config)
        self._server.config = self._config
        return self.get_settings()

    def __getattr__(self, name):
        # FIX 1c: no self-returning fallback. Unknown attrs must raise so
        # pywebview's dir()+getattr scan can't loop into nested objects
        # (the Empty.Empty.Empty... recursion spam).
        raise AttributeError(f"Api has no attribute {name!r}")

    def open_folder(self, path):
        import os
        import subprocess
        try:
            os.startfile(path)
            return {"ok": True}
        except Exception:
            try:
                subprocess.Popen(["explorer", path])
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import os
    api = Api()
    dev_url = os.environ.get("PW_DEV_URL", "")
    url = dev_url or "frontend/dist/index.html"
    window = webview.create_window(
        "PW Downloader", url=url, js_api=api,
        width=1100, height=720, min_size=(900, 600))
    api.attach_window(window)
    if api._config.get("auto_start_server", True):
        api._server.start()
    webview.start(func=_drain_js)
