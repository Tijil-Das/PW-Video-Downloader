"""Print the chapter tree for the user's current batch (needs PW_TOKEN)."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import load_config
from chapter_resolver import list_all_chapters

cfg = load_config()
tree = list_all_chapters(cfg.get("batch_slug", os.environ.get("BATCH_SLUG", "")),
                         cfg.get("batch_id", os.environ.get("BATCH_ID", "")))
print(json.dumps(tree, indent=1, ensure_ascii=False)[:3000])
