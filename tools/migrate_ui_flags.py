"""One-off migration: flag platform-UI screenshots in already-stored materials (same logic as
pipeline.is_ui_screenshot) so they are left out of the images view, without re-running the full analysis."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ftf.ingest import Material  # noqa: E402
from ftf.pipeline import is_ui_screenshot  # noqa: E402
from ftf.store import Store  # noqa: E402

st = Store()
for mid, (f, v) in st.all().items():
    imgs = f.get("images", [])
    n_ui = 0
    for im in imgs:
        if is_ui_screenshot(im.get("ocr_text", "")):
            im["kind"] = "ui_screenshot"
            n_ui += 1
    f2 = {k: x for k, x in f.items() if not k.startswith("_")}
    st.upsert(Material.from_dict(f["_material"]), f2, v)
    print(f["name"], "ui screenshots:", n_ui, "of", len(imgs))
