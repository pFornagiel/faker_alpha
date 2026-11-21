"""One-off migration: flag platform-UI screenshots in already-stored materials and drop their
CLIP/DINO rows (same logic as pipeline.is_ui_screenshot), without re-running the full analysis."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ftf.ingest import Material  # noqa: E402
from ftf.pipeline import is_ui_screenshot  # noqa: E402
from ftf.store import Store  # noqa: E402

st = Store()
for mid, (f, v) in st.all().items():
    imgs = f.get("images", [])
    keep = [i for i, im in enumerate(imgs) if not is_ui_screenshot(im.get("ocr_text", ""))]
    for i, im in enumerate(imgs):
        if i not in keep:
            im["kind"] = "ui_screenshot"
    v2 = dict(v)
    for k in ("clip", "dino"):
        if k in v and len(v[k]) == len(imgs) and len(keep) < len(imgs):
            v2[k] = np.asarray(v[k])[keep] if keep else np.zeros((0, np.asarray(v[k]).shape[1]), np.float32)
    f2 = {k: x for k, x in f.items() if not k.startswith("_")}
    st.upsert(Material.from_dict(f["_material"]), f2, v2)
    print(f["name"], "ui screenshots:", len(imgs) - len(keep), "of", len(imgs))
