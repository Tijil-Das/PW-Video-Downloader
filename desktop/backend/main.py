"""pywebview entry + js_api bridge (React <-> Python)."""
import json
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
        payload = {"jobId": job_id, "stage": stage, "pct": pct, "detail": detail}
        self.server.broadcast({"type": "status", **payload})
        if stage in ("done", "error"):
            jobs = self.downloader.list_jobs()
            rec = next((j for j in jobs if j.get("jobId") == job_id), payload)
            key = "done" if stage == "done" else "error"
            extra = {"path": rec.get("path")} if stage == "done" else {"message": detail}
            self.server.broadcast({"type": key, "jobId": job_id, **extra})
        if self.window:
            try:
                self.window.evaluate_js(
                    f"window.__onJobStatus({json.dumps(payload)})")
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
