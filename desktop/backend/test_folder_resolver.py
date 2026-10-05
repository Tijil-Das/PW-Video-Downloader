"""Live test for folder_resolver.resolve_folder_path.

Reads PW_TOKEN from the environment, resolves one hardcoded lecture,
prints the result as formatted JSON. Exit 0 on success, 1 on error.
"""
import json
import os
import sys

from folder_resolver import resolve_folder_path

SAMPLE = {
    "scheduleId": "6ab7498453695c3f89876602",
    "name": "Units and Measurements 2: Propagation of Errors || Accuracy and Precision || Vernier Caliper || Screw Gauge || NO DPP",
    "batchId": "6aa790b23e605f161edbf979",
    "batchSlug": "mission-100-jee-2027-225226",
    "batchSubjectId": "6aa90f52e46d8219d24b02d1",
    "thumbnailUrl": "https://static.pw.live/5eb393ee95fab7468a79d189/ADMIN/ed01427b-e17f-4dd7-a42d-0b739e8230cd.png",
}


def main():
    token = os.environ.get("PW_TOKEN", "")
    result = resolve_folder_path(SAMPLE, token)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    assert "lecture_date" in result, "missing lecture_date in output"
    assert "thumbnail_url" in result, "missing thumbnail_url in output"
    assert "relative_path" in result, "missing relative_path in output"
    assert "subject_slug" in result, "missing subject_slug in output"
    assert "chapter_slug" in result, "missing chapter_slug in output"
    assert "chapter_id" in result, "missing chapter_id in output"
    sys.exit(0 if not result.get("error") else 1)


if __name__ == "__main__":
    main()
