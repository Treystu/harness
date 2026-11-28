import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PIL import Image

base = Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner"
frames = [
    ("1330-after", base / "restore-7100931819-315608d2-scoped-20261123-1330/after-freebuff.png"),
    ("1330-before", base / "restore-7100931819-315608d2-scoped-20261123-1330/before-freebuff.png"),
    ("1345-after", base / "restore-7100931819-315608d2-scoped-20261123-1345/after-freebuff.png"),
    ("1345-prepare", base / "restore-7100931819-315608d2-scoped-20261123-1345/prepare/lane1-before-draft-settle.png"),
    ("1318-after", base / "restore-7100931819-315608d2-scoped-20261123-1318/after-freebuff.png"),
    ("running-1930", base / "restore-7100931819-315608d2-lane1-selected-row-cure/after-freebuff.png"),
]
for label, path in frames:
    if not path.is_file():
        print(label, "MISSING")
        continue
    image = Image.open(path).convert("L")
    patch = image.crop((1501, 1066, 1513, 1078))
    values = list(patch.getdata())
    darks = sum(value < 60 for value in values)
    rows = []
    for y in range(12):
        rows.append("".join("#" if values[y * 12 + x] < 60 else
                            ("+" if values[y * 12 + x] < 140 else ".") for x in range(12)))
    corners = sum(values[y * 12 + x] < 60
                  for y, x in ((0, 0), (1, 0), (0, 1), (1, 1), (10, 0), (11, 0), (10, 1), (11, 1),
                               (0, 10), (1, 10), (0, 11), (1, 11), (10, 10), (11, 10), (10, 11), (11, 11)))
    print(f"== {label} darks={darks} corners={corners}")
    print("\n".join(rows))
