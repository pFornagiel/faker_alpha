"""UI smoke test: open the running Streamlit app and screenshot every tab.
    .venv/bin/streamlit run app.py --server.headless true --server.port 8599 &
    .venv/bin/python tools/ui_screenshots.py http://localhost:8599 docs/screenshots
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"
out = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 1100})
    pg.goto(url, wait_until="networkidle", timeout=120000)
    pg.wait_for_selector("text=FakerAlpha", timeout=120000)
    pg.wait_for_selector('[role="tab"]', timeout=120000); pg.wait_for_timeout(3000)
    tabs = pg.locator('[role="tab"]')
    n = tabs.count()
    for i in range(n):
        name = tabs.nth(i).inner_text().strip()
        tabs.nth(i).click()
        pg.wait_for_timeout(9000 if "Graf" in name else 3500)
        errs = pg.locator('[data-testid="stException"]').count()
        f = out / f"tab{i}.png"
        pg.screenshot(path=str(f), full_page=True)
        print(f"{i} {name!r} exceptions={errs} -> {f}")
    b.close()
