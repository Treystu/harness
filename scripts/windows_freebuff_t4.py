"""Inspect both exact SCMessenger search results without touching their composers."""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from driver_core import osal

from .windows_freebuff_dispatch import CLICK, SCM_THREAD, Dispatch


CENSUS_REGIONS = {
    "project": (65, 100, 465, 1085),
    "toolbar": (475, 25, 1790, 112),
    "transcript-upper": (610, 108, 1550, 540),
    "transcript-lower": (610, 540, 1550, 915),
    "composer": (630, 915, 1545, 1110),
    "right-rail": (1551, 112, 1795, 1100),
}


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
    driver.frame("scm-selected")
    time.sleep(11)
    frame = driver.frame("scm-settled")
    with ThreadPoolExecutor(max_workers=3) as pool:
        readings = {label: pool.submit(inspect_crop, driver, frame, label, region, "-ReadText")
                    for label, region in CENSUS_REGIONS.items()}
        census = {label: reading.result()["text"] for label, reading in readings.items()}
    (driver.output / "census.json").write_text(
        json.dumps(census, indent=2, ensure_ascii=False), encoding="utf-8")
    driver.audit.append("extraction", step_id="scm-census", ordinal=ordinal,
                        regions={label: len(value) for label, value in census.items()})
    print(json.dumps({"candidate": ordinal, "evidence": "census.json"}))


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
