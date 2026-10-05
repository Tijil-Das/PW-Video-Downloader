"""Phase 3 — LibraryIndex: one metadata.json per chapter + registry ops."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

try:
    from filelock import FileLock
except Exception:
    FileLock = None


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LibraryIndex:
    def __init__(self, storage):
        self.storage = storage
        self._locks = {}
        self._locks_guard = threading.Lock()

    def _meta_path(self, subject, chapter):
        info = self.storage.ensure_chapter_folders(subject, chapter)
        return Path(info["index_path"])

    def _guard(self, path):
        with self._locks_guard:
            return self._locks.setdefault(str(path), threading.Lock())

    def load(self, subject, chapter):
        p = self._meta_path(subject, chapter)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"lectures": [], "dpps": []}

    def save(self, subject, chapter, data):
        p = self._meta_path(subject, chapter)
        p.parent.mkdir(parents=True, exist_ok=True)
        if FileLock:
            with FileLock(str(p) + ".lock"):
                p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            with self._guard(p):
                p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _base(self, subject, chapter, extra=None):
        d = self.load(subject, chapter)
        d.update({
            "batch_name": getattr(self.storage, "batch", ""),
            "subject_name": subject,
            "chapter_name": chapter,
        })
        if extra:
            d.update({k: v for k, v in extra.items() if v is not None})
        d.setdefault("lectures", [])
        d.setdefault("dpps", [])
        return d

    def upsert_lecture(self, subject, chapter, lecture, extra=None):
        d = self._base(subject, chapter, (extra or {}).get("meta"))
        ex = dict(extra or {})
        ex.pop("meta", None)
        sid = lecture.get("schedule_id") or lecture.get("scheduleId")
        rows = d["lectures"]
        row = next((r for r in rows if r.get("schedule_id") == sid), None)
        if row is None:
            row = {"schedule_id": sid}
            rows.append(row)
        row.update({
            "schedule_id": sid,
            "name": lecture.get("name"),
            "date": lecture.get("date") or lecture.get("lecture_date"),
            "date_iso": lecture.get("date_iso") or lecture.get("lecture_date_iso"),
            "thumbnail_url": lecture.get("thumbnail_url") or lecture.get("thumbnailUrl"),
            "video_file": ex.get("video_file"),
            "thumb_file": ex.get("thumb_file"),
            "kid": ex.get("kid") or lecture.get("kid"),
            "key": ex.get("key") or lecture.get("key"),
            "downloaded_at": ex.get("downloaded_at") or _now(),
            "size_bytes": ex.get("size_bytes"),
        })
        self.save(subject, chapter, d)

    def upsert_dpp(self, subject, chapter, dpp, extra=None):
        d = self._base(subject, chapter, (extra or {}).get("meta"))
        ex = dict(extra or {})
        ex.pop("meta", None)
        fname = dpp.get("file_name") or ex.get("file_name")
        rows = d["dpps"]
        row = next((r for r in rows if r.get("file_name") == fname), None)
        if row is None:
            row = {"file_name": fname}
            rows.append(row)
        row.update({
            "dpp_name": dpp.get("dpp_name") or dpp.get("name"),
            "date": dpp.get("date"),
            "date_iso": dpp.get("date_iso"),
            "file_name": fname,
            "url": dpp.get("url"),
            "downloaded_at": ex.get("downloaded_at") or _now(),
            "size_bytes": ex.get("size_bytes"),
        })
        self.save(subject, chapter, d)

    def list_chapters(self):
        base = Path(self.storage.base) / "Index" / "batches" / self.storage.batch
        out = []
        if not base.is_dir():
            return out
        for meta in sorted(base.rglob("metadata.json")):
            try:
                d = json.loads(meta.read_text(encoding="utf-8"))
            except Exception:
                continue
            rel = meta.parent.relative_to(base)
            parts = list(rel.parts)
            out.append({
                "subject": d.get("subject_name") or (parts[0] if len(parts) > 0 else ""),
                "chapter": d.get("chapter_name") or (parts[1] if len(parts) > 1 else ""),
                "lecture_count": len(d.get("lectures", [])),
                "dpp_count": len(d.get("dpps", [])),
            })
        return out
