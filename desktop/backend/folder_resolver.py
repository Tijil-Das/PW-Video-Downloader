"""Resolve human-readable subject/chapter names for a captured PW lecture.

Calls the schedule-details endpoint and builds a Windows-safe relative path.
"""
import logging
import re
import uuid
from datetime import datetime

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE = "https://api.penpencil.co/v1/batches"


def _sanitize(name: str) -> str:
    if not name or not isinstance(name, str):
        return "_Unsorted"
    s = re.sub(r'[\\/:*?"<>|]', "_", name)
    s = s.strip(" .")
    s = re.sub(r"_+", "_", s)
    s = s[:120].strip(" .")
    return s if s else "_Unsorted"


def _parse_date(raw):
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        iso = s.replace("Z", "+00:00") if s.endswith("Z") else s
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d")
    except ValueError:
        pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else None


def _build_path(subject_name, chapter_name, lecture_name, lecture_date=None):
    s = _sanitize(subject_name) if subject_name else "_Unsorted"
    c = _sanitize(chapter_name) if chapter_name else "_Unsorted"
    n = _sanitize(lecture_name) if lecture_name else "_Unsorted"
    if lecture_date:
        n = f"{lecture_date} - {n}"
    return f"{s}/{c}/{n}.mkv"


def _fail(lecture_name, message, thumbnail_url=None):
    logger.info("folder_resolver error: %s", message)
    return {
        "subject_name": None,
        "chapter_name": None,
        "lecture_name": lecture_name,
        "lecture_date": None,
        "lecture_date_iso": None,
        "thumbnail_url": thumbnail_url,
        "relative_path": _build_path(None, None, lecture_name),
        "error": message,
    }


def resolve_folder_path(lecture: dict, pw_token: str | None = None) -> dict:
    """
    Given a captured lecture dict and a PW Bearer token, fetch the
    schedule-details endpoint and return a dict with the resolved
    human-readable path components.

    If pw_token is None/empty, falls back to token_store.get_token()
    (extension-pushed token -> disk -> PW_TOKEN env).

    Returns:
      {
        "subject_name": "Physics By Saleem Ahmad Sir",
        "chapter_name": "Electrostatics",
        "lecture_name": "Units and Measurements 2...",   # from input
        "lecture_date": "2025-10-01",                    # YYYY-MM-DD or None
        "lecture_date_iso": "2025-10-01T03:15:00.000Z",  # raw value or None
        "thumbnail_url": "https://static.pw.live/.../<uuid>.png",  # passthrough or None
        "relative_path": "Physics By Saleem Ahmad Sir/Electrostatics/2025-10-01 - Units and Measurements 2....mkv",
        "error": None                                     # or a string on failure
      }
    """
    raw_name = lecture.get("name") if isinstance(lecture, dict) else None
    thumbnail_url = lecture.get("thumbnailUrl") if isinstance(lecture, dict) else None
    if not thumbnail_url:
        thumbnail_url = None
    if not pw_token:
        try:
            from token_store import get_token
            pw_token = get_token()
        except Exception:
            pw_token = None
    if not pw_token:
        return _fail(raw_name, "no pw_token available", thumbnail_url)
    if not isinstance(lecture, dict):
        return _fail(None, "missing required field: batchId", thumbnail_url)
    for field in ("batchId", "batchSubjectId", "scheduleId"):
        if not lecture.get(field):
            return _fail(raw_name, f"missing required field: {field}", thumbnail_url)
    batch_id = lecture["batchId"]
    batch_subject_id = lecture["batchSubjectId"]
    schedule_id = lecture["scheduleId"]
    url = f"{BASE}/{batch_id}/subject/{batch_subject_id}/schedule/{schedule_id}/schedule-details"
    headers = {
        "Authorization": f"Bearer {pw_token}",
        "client-id": "5eb393ee95fab7468a79d189",
        "client-type": "WEB",
        "client-version": "3219",
        "version": "3.2.19",
        "x-sdk-version": "0.0.20",
        "Origin": "https://www.pw.live",
        "Referer": "https://www.pw.live/",
        "Content-Type": "application/json",
        "randomid": str(uuid.uuid4()),
    }
    logger.info("Fetching schedule-details: %s", url)
    try:
        resp = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.Timeout:
        return _fail(raw_name, "schedule-details request timed out", thumbnail_url)
    except requests.exceptions.RequestException as exc:
        return _fail(raw_name, f"request failed: {exc}"[:200], thumbnail_url)
    if resp.status_code != 200:
        return _fail(raw_name, f"HTTP {resp.status_code}: {resp.text[:200]}", thumbnail_url)
    try:
        payload = resp.json()
    except ValueError:
        return _fail(raw_name, "invalid JSON response", thumbnail_url)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return _fail(raw_name, "unexpected response shape", thumbnail_url)
    subject = data.get("subject") or {}
    subject_name = subject.get("name") if isinstance(subject, dict) else None
    tags = data.get("tags")
    chapter_name = tags[0] if isinstance(tags, list) and tags else None
    raw_date = next((data.get(k) for k in ("startTime", "date", "createdAt", "scheduleDate") if data.get(k)), None)
    parsed_date = _parse_date(raw_date)
    logger.info("date raw=%s parsed=%s", raw_date, parsed_date)
    logger.info("thumbnail url=%s", thumbnail_url)
    relative_path = _build_path(subject_name, chapter_name, raw_name, parsed_date)
    logger.info("Resolved subject=%r chapter=%r", subject_name, chapter_name)
    return {
        "subject_name": subject_name,
        "chapter_name": chapter_name,
        "lecture_name": raw_name,
        "lecture_date": parsed_date,
        "lecture_date_iso": raw_date,
        "thumbnail_url": thumbnail_url,
        "relative_path": relative_path,
        "error": None,
    }
