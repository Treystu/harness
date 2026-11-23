"""Inspect both exact SCMessenger search results without touching their composers."""

import argparse
import json
import os
import time
from pathlib import Path

from driver_core import osal

from .windows_freebuff_dispatch import CLICK, SCM_THREAD, Dispatch


def inspect_crop(driver, frame, label, region, *options):
    crop = frame.crop(region)
    crop = crop.resize((crop.width * 2, crop.height * 2))
    path = driver.output / f"{label}.png"
    driver.image_ops.invert(driver.image_ops.grayscale(crop)).save(path)
    helper = Path(__file__).with_name("windows_ocr_exact.ps1")
    response = osal.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
                         str(helper), "-Path", str(path), *options], timeout=15)
    if not response.ok:
        raise RuntimeError(f"{label}: {response.stderr.strip().splitlines()[0]}")
    return json.loads(response.stdout)


def probe(driver, ordinal):
    frame = driver.frame("search-candidates")
    driver.require_foreground()
    region = (546, 249, 1140, 926)
    point = inspect_crop(driver, frame, "candidate-ocr", region,
                         "-Label", "SCMessenger", "-Ordinal", str(ordinal))
    x, y = region[0] + round(point["x"] / 2), region[1] + round(point["y"] / 2)
    driver.yes("verify-scm-candidate", frame,
               "Does this exact search result read SCMessenger with no additional words?",
               region=(543, y - 20, 1040, y + 20))
    driver.act("navigate-scm-candidate", CLICK,
               {"control": f"SCMessenger exact search candidate {ordinal}",
                "point": [x, y], "size": list(frame.size)})
    time.sleep(7)
    frame = driver.frame("scm-selected")
    composer = inspect_crop(driver, frame, "composer-readonly", (644, 929, 1518, 1040), "-ReadText")
    activity = inspect_crop(driver, frame, "activity-readonly", (620, 70, 1546, 810), "-ReadText")
    staged = "continue in full" in composer["text"].strip().splitlines()
    newest = "#745" in activity["text"] or "cab43b2" in activity["text"].casefold()
    driver.audit.append("extraction", step_id="scm-signatures", ordinal=ordinal,
                        staged_restart=staged, newest_scm_work=newest)
    (driver.output / "ocr-local.json").write_text(
        json.dumps({"composer": composer["text"], "activity": activity["text"]}), encoding="utf-8")
    print(json.dumps({"candidate": ordinal, "staged": staged, "newest": newest}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("search", "query", "probe"))
    parser.add_argument("--ordinal", type=int, choices=(1, 2))
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    key = os.environ.pop("TYPESAFE_API_KEY", "")
    if not key or (args.phase == "probe" and args.ordinal is None):
        parser.error("trusted child key and probe ordinal are required")
    args.evidence.mkdir()
    driver = Dispatch(args.evidence, key, thread=SCM_THREAD, scoped_input=True)
    try:
        if args.phase == "search":
            driver.open_search()
        elif args.phase == "query":
            driver.search_for_session()
        else:
            probe(driver, args.ordinal)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        driver.audit.append("escalation", step_id=args.phase, reason=str(error))
        print(f"BLOCKED: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
