"""pywebview entry + js_api bridge (React <-> Python)."""
import json
from pathlib import Path

import webview
from server import BridgeServer
from downloader import Downloader
from chrome_detect import detect_extension
from config import load_config, save_config


class Api:
    def __init__(self):
        self.config = load_config()
        self.downloader = Downloader(self.config, self._on_status)
        self.server = BridgeServer(self.config, self.downloader)
        self.window = None

    def _on_status(self, job_id, stage, pct, detail):
        # NOTE: NO window.evaluate_js here — it synchronously blocks on the
        # WebView2 control handle and deadlocks when called from the worker
        # thread (the AccessibilityObject.Bounds traceback + hung UI).
        # React picks every update via its 3s list_jobs() poll; WS carries
        # live pushes to the extension. Never push directly to the window.
        payload = {"jobId": job_id, "stage": stage, "pct": pct, "detail": detail}
        try:
            self.server.broadcast({"type": "status", **payload})
        except Exception:
            pass
        if stage in ("done", "error"):
            jobs = self.downloader.list_jobs()
            rec = next((j for j in jobs if j.get("jobId") == job_id), payload)
            key = "done" if stage == "done" else "error"
            extra = {"path": rec.get("path")} if stage == "done" else {"message": detail}
            try:
                self.server.broadcast({"type": key, "jobId": job_id, **extra})
            except Exception:
                pass

    def check_extension(self):
        return detect_extension(
            self.config.get("extension_id", ""),
            self.config.get("extension_path", ""))

    def start_server(self):
        self.config["ws_port"] = int(self.config.get("ws_port", 9777))
        save_config(self.config)
        self.server.config = self.config
        self.server.start()
        return {"running": True, "port": self.port}

    def stop_server(self):
        self.server.stop()
        return {"running": False}

    @property
    def port(self):
        return int(self.config.get("ws_port", 9777))

    def server_status(self):
        return {"running": self.server.is_running(), "port": self.port}

    def list_jobs(self):
        return self.downloader.list_jobs()

    def list_all_chapters(self):
        from chapter_resolver import list_all_chapters
        return list_all_chapters(self.config.get("batch_slug", ""),
                                 self.config.get("batch_id", ""))

    def refresh_chapters(self):
        from chapter_resolver import clear_cache
        clear_cache()
        return self.list_all_chapters()

    def download_chapter_dpps(self, subject_slug, chapter_slug, subject_name, chapter_name):
        job_id = self.downloader.submit_dpps(subject_slug, chapter_slug, subject_name, chapter_name)
        return {"job_id": job_id, "queued": True}

    def test_storage(self):
        try:
            from storage import Storage
            st = Storage(self.config.get("base_storage_path", ""),
                         self.config.get("batch_name", ""))
            info = st.ensure_chapter_folders("_Test", "_Test")
            probe = Path(info["index_dir"]) / "write_probe.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_settings(self):
        det = self.check_extension()
        if det.get("extension_id") and not self.config.get("extension_id"):
            self.config["extension_id"] = det["extension_id"]
        return {**self.config, "detection": det}

    def save_settings(self, patch):
        patch = dict(patch or {})
        if "ws_port" in patch:
            patch["ws_port"] = int(patch["ws_port"])
        self.config.update(patch)
        save_config(self.config)
        self.server.config = self.config
        return self.get_settings()

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
    api.window = window
    if api.config.get("auto_start_server", True):
        api.server.start()
    webview.start()
