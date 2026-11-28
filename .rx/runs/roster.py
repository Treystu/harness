"""Read-only census of the project session list, through the driver's own primitives."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.windows_freebuff_dispatch import SIDEBAR, SCROLL, Dispatch

out = Path(__file__).resolve().parents[1] / "harvest"
out.mkdir(parents=True, exist_ok=True)
driver = Dispatch(out, b"harvest", thread="315608d2")
frame = driver.scroll_sidebar_to_top()
seen = []
for page in range(1, 9):
    try:
        frame, rows = driver.settled_roster(f"page-{page}", SIDEBAR, attempts=3)
    except RuntimeError as error:
        print("page", page, "unsettled:", error)
        break
    texts = [row["text"] for row in rows]
    print(f"--- page {page}: {len(rows)} rows ---")
    for row in rows:
        print(f'  y={row["y"]:7.1f}  {row["text"]}')
    if texts in seen:
        print("(repeated page, stopping)")
        break
    seen.append(texts)
    driver.act(f"page-scroll-{page}", SCROLL,
               {"point": [196, 850], "size": list(frame.size), "delta": -400})
