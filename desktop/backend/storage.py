"""Phase 1 — Storage: base/batch roots + per-chapter folder management.

Layout under {base_path}:
  Library/batches/<batch>/<subject>/<chapter>/     video .mkv files
  Library/thumbnails/<batch>/<subject>/<chapter>/  thumbnail .png files
  Library/dpps/<batch>/<subject>/<chapter>/        DPP PDFs
  Index/batches/<batch>/<subject>/<chapter>/       metadata.json
"""
from pathlib import Path

from folder_resolver import sanitize as _sanitize


class Storage:
    def __init__(self, base_path: str, batch_name: str):
        if not (base_path or "").strip():
            raise ValueError("base_storage_path is empty — set it in Settings first")
        if not (batch_name or "").strip():
            raise ValueError("batch_name is empty — set it in Settings first")
        self.base = Path(base_path).expanduser()
        self.batch = _sanitize(batch_name)

    def _chapter_root(self, root: str, subject_name: str, chapter_name: str) -> Path:
        return (self.base / root / "batches" / self.batch
                / _sanitize(subject_name) / _sanitize(chapter_name))

    def ensure_chapter_folders(self, subject_name: str, chapter_name: str) -> dict:
        video_dir = self.base / "Library" / "batches" / self.batch / _sanitize(subject_name) / _sanitize(chapter_name)
        thumb_dir = self.base / "Library" / "thumbnails" / self.batch / _sanitize(subject_name) / _sanitize(chapter_name)
        dpp_dir = self.base / "Library" / "dpps" / self.batch / _sanitize(subject_name) / _sanitize(chapter_name)
        index_dir = self.base / "Index" / "batches" / self.batch / _sanitize(subject_name) / _sanitize(chapter_name)
        for d in (video_dir, thumb_dir, dpp_dir, index_dir):
            d.mkdir(parents=True, exist_ok=True)

        def _file(target: Path, lecture_name: str, ext: str) -> str:
            safe = _sanitize(lecture_name)
            return str(target / f"{safe}{ext}")

        return {
            "video_dir": str(video_dir),
            "thumb_dir": str(thumb_dir),
            "dpp_dir": str(dpp_dir),
            "index_dir": str(index_dir),
            "video_path": lambda lecture_name: _file(video_dir, lecture_name, ".mkv"),
            "thumb_path": lambda lecture_name: _file(thumb_dir, lecture_name, ".png"),
            "index_path": str(index_dir / "metadata.json"),
        }

    def list_batches(self) -> list:
        root = self.base / "Library" / "batches"
        if not root.is_dir():
            return []
        return sorted([p.name for p in root.iterdir() if p.is_dir()])

    def chapter_exists(self, subject_name: str, chapter_name: str) -> bool:
        return (self.base / "Library" / "batches" / self.batch
                / _sanitize(subject_name) / _sanitize(chapter_name)).is_dir()
