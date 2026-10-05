"""Job queue: single worker wraps the EXISTING watch.py engine unchanged.

watch.py stays the backend engine (Playwright capture + N_m3u8DL-RE).
This module only queues jobs, emits stage callbacks, runs the download
command with the same flags. Do NOT reimplement capture logic here.
"""
import importlib.util
import queue
import re
import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path

ENGINE_PATH = Path(__file__).resolve().parents[2] / "downloader" / "watch.py"

_spec = importlib.util.spec_from_file_location("pw_watch_engine", ENGINE_PATH)
_engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_engine)

STAGES = ("queued", "signing", "downloading", "decrypting", "done", "error")


class Downloader:
    def __init__(self, config, on_status=None):
        self.config = config
        self.on_status = on_status or (lambda *a: None)
        self.q = queue.Queue()
        self.jobs = {}
        self.cancelled = set()
        self.lock = threading.Lock()
        self.out_dir = Path(config.get("output_dir", _engine.OUT and str(_engine.OUT)))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        t = threading.Thread(target=self._worker, daemon=True)
        t.start()

    def _emit(self, job_id, stage, pct=0, detail=""):
        with self.lock:
            rec = self.jobs.get(job_id, {})
            rec.update({"jobId": job_id, "stage": stage, "pct": pct, "detail": detail})
            self.jobs[job_id] = rec
            snapshot = dict(rec)
        try:
            self.on_status(job_id, stage, pct, detail)
        except Exception:
            pass
        return snapshot

    def submit(self, job):
        job = dict(job or {})
        job_id = str(job.get("jobId") or job.get("scheduleId") or uuid.uuid4().hex[:8])
        with self.lock:
            self.jobs[job_id] = {
                "jobId": job_id,
                "scheduleId": job.get("scheduleId", job_id),
                "name": job.get("name", job_id),
                "mpdUrl": job.get("mpdUrl", ""),
                "batchId": job.get("batchId", ""),
                "batchSubjectId": job.get("batchSubjectId", ""),
                "thumbnailUrl": job.get("thumbnailUrl", ""),
                "stage": "queued", "pct": 0, "detail": "queued", "path": None,
                "_job": job,
            }
        self._emit(job_id, "queued", 0, "queued")
        self.q.put(job_id)
        return job_id

    def cancel(self, job_id):
        self.cancelled.add(str(job_id))
        self._emit(str(job_id), "error", 0, "cancelled")
        return True

    def list_jobs(self):
        with self.lock:
            return [{k: v for k, v in rec.items() if not k.startswith("_")}
                    for rec in self.jobs.values()]

    def _worker(self):
        while True:
            job_id = self.q.get()
            try:
                if job_id in self.cancelled:
                    continue
                self._process(job_id)
            except Exception:
                traceback.print_exc()
                self._emit(job_id, "error", 0, "worker crash")
            finally:
                self.q.task_done()

    def _process(self, job_id):
        with self.lock:
            job = dict(self.jobs[job_id].get("_job", {}))
        if job_id in self.cancelled:
            return
        # --- signing: existing Playwright capture (signed URL + WP2 key) ---
        self._emit(job_id, "signing", 5, "signing URL + reading key")
        signed, kid, key = _engine.capture(job)
        if job_id in self.cancelled:
            return
        if not signed:
            self._emit(job_id, "error", 0, "signed URL never arrived")
            return
        if not key or not kid:
            # Same guard as watch.py: refuse corrupt download without key.
            self._emit(job_id, "error", 0, f"NO KEY for KID {kid}")
            return
        # --- downloading/decrypting: same N_m3u8DL-RE flags as watch.py ---
        self._emit(job_id, "downloading", 20, "downloading segments")
        name = re.sub(r"[^\w\-. ()\[\]]+", "_",
                      job.get("name", job.get("scheduleId", job_id))).strip(" .")[:150] or "lecture"
        cfg = _engine.CFG
        cmd = [cfg["nm3u8dl_path"], signed, "-H", "Accept: */*",
               "-H", "Origin: https://www.pw.live", "-H", "Referer: https://www.pw.live/",
               "-H", ("User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"),
               "--append-url-params", "--key", f"{kid}:{key}",
               "-M", "format=mkv", "--auto-select", "--thread-count", "16", "-mt",
               "--save-name", name, "--save-dir", str(self.out_dir)]
        self._emit(job_id, "decrypting", 70, f"decrypting {str(kid)[:8]}...")
        r = subprocess.run(cmd, cwd=cfg["nm3u8dl_workdir"])
        out = self.out_dir / f"{name}.mkv"
        if r.returncode == 0 and out.exists():
            with self.lock:
                self.jobs[job_id]["path"] = str(out)
            self._emit(job_id, "done", 100, f"saved ({out.stat().st_size // 1024 // 1024} MB)")
        else:
            self._emit(job_id, "error", 0, f"download FAILED (exit {r.returncode})")
