"""Phase 5 — list every chapter in a batch with slugs for the DPP UI."""
import logging
import time
import uuid

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE = "https://api.penpencil.co"
_CACHE, _CACHE_AT = {}, 0
_TTL = 600


def _headers(tok):
    return {
        "Authorization": f"Bearer {tok}",
        "client-id": "5eb393ee95fab7468a79d189",
        "client-type": "WEB",
        "client-version": "3219",
        "Origin": "https://www.pw.live",
        "Referer": "https://www.pw.live/",
        "Content-Type": "application/json",
        "randomid": str(uuid.uuid4()),
    }


def _token(pw_token):
    if pw_token:
        return pw_token
    try:
        from token_store import get_token
        return get_token()
    except Exception:
        return None


def clear_cache():
    global _CACHE, _CACHE_AT
    _CACHE, _CACHE_AT = {}, 0


def list_all_chapters(batch_slug, batch_id, pw_token=None):
    """[{subject_name, subject_slug, subject_id, chapters:[{chapter_name, chapter_slug, chapter_id, lecture_count}]}]"""
    global _CACHE, _CACHE_AT
    key = (batch_slug, batch_id)
    if key in _CACHE and time.time() - _CACHE_AT < _TTL:
        return _CACHE[key]
    tok = _token(pw_token)
    if not tok:
        return {"error": "no pw_token available", "subjects": []}
    if not batch_slug or not batch_id:
        return {"error": "missing batch_slug/batch_id", "subjects": []}
    try:
        det = requests.get(f"{BASE}/v3/batches/{batch_id}/details",
                           headers=_headers(tok), timeout=15)
    except Exception as e:
        return {"error": f"details failed: {e}"[:200], "subjects": []}
    if det.status_code != 200:
        return {"error": f"HTTP {det.status_code}: {det.text[:150]}", "subjects": []}
    try:
        subjects = det.json().get("data", {}).get("subjects", [])
    except Exception:
        return {"error": "invalid JSON", "subjects": []}
    out = []
    for s in subjects or []:
        s_slug = s.get("slug") or ""
        s_name = s.get("subject") or s.get("name") or ""
        s_id = s.get("_id") or s.get("subjectId") or ""
        chapters = []
        page = 1
        while True:
            try:
                r = requests.get(
                    f"{BASE}/v2/batches/{batch_slug}/subject/{s_slug}/topics?page={page}",
                    headers=_headers(tok), timeout=15)
            except Exception as e:
                logger.warning("topics failed: %s", e)
                break
            if r.status_code != 200:
                break
            try:
                payload = r.json()
            except Exception:
                break
            data = payload.get("data", [])
            if isinstance(data, dict):
                data = data.get("topics", data.get("data", []))
            if not data:
                break
            for t in data:
                if isinstance(t, dict):
                    chapters.append({
                        "chapter_name": t.get("name") or t.get("title") or "",
                        "chapter_slug": t.get("slug") or "",
                        "chapter_id": t.get("_id") or "",
                        "lecture_count": t.get("lectureCount") or t.get("count") or 0,
                    })
            if isinstance(payload.get("data"), dict) and payload["data"].get("hasMore") is False:
                break
            if len(data) < 20:
                break
            page += 1
            if page > 50:
                break
        out.append({"subject_name": s_name, "subject_slug": s_slug,
                    "subject_id": s_id, "chapters": chapters})
    _CACHE, _CACHE_AT = {key: out}, time.time()
    return out
