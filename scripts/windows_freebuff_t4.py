"""Inspect both exact SCMessenger search results without touching their composers."""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import byref, wintypes
from pathlib import Path

from driver_core import osal

from .windows_freebuff_dispatch import CLICK, SCM_THREAD, SCROLL, Dispatch


CENSUS_REGIONS = {
    "project": (65, 100, 465, 1085),
    "toolbar": (1120, 1044, 1480, 1104),
    "transcript-upper": (610, 108, 1550, 540),
    "transcript-lower": (610, 540, 1550, 915),
    "composer": (646, 751, 1535, 1054),
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


def scan_draft(driver, frame, *, continuation=False):
    region = (650, 756, 1530, 1050)
    if continuation:
        driver.locate_exact_text("verify-local-carrier-standup", frame,
                                 "STAND-UP (file in ledger dispatch/scm-land/STATUS.md):",
                                 (650, 838, 1220, 875))
        driver.yes("verify-local-carrier-continuation", frame,
                   "Does this text show the stand-up heading for dispatch/scm-land/STATUS.md?",
                   region=(650, 818, 1230, 910))
    else:
        driver.locate_exact_text("verify-fresh-carrier-heading", frame,
                                 "SCMESSENGER LANE - FRESH SESSION CARRIER (D-2026-11-13-032 FIRST)",
                                 (652, 790, 1400, 825))
        driver.yes("verify-visible-carrier", frame,
                   "Do the opening lines describe a FRESH SESSION CARRIER?",
                   region=(650, 756, 1395, 861))

    def scroll(action, params):
        hit, x, y = driver.renderer_point(params)
        if driver.user.GetAncestor(hit, 2) != driver.require_foreground():
            raise RuntimeError("the renderer changed before draft scrolling")
        client = wintypes.POINT(x, y)
        if not driver.user.ScreenToClient(hit, byref(client)):
            raise RuntimeError("could not bind the scroll point to the renderer")
        hover = (client.x & 0xFFFF) | ((client.y & 0xFFFF) << 16)
        if not driver.user.PostMessageW(hit, 0x0200, 0, hover):
            raise RuntimeError("the renderer rejected the draft hover")
        packed = (x & 0xFFFF) | ((y & 0xFFFF) << 16)
        if not driver.user.PostMessageW(hit, 0x020A, (params["delta"] & 0xFFFF) << 16, packed):
            raise RuntimeError("the renderer rejected draft scrolling")

    driver.driver.register_executor(SCROLL.name, scroll)
    readings = []
    unchanged = 0
    params = {"point": [1100, 930], "size": list(frame.size), "delta": -120}
    for page in range(1, 25):
        text = inspect_crop(driver, frame, f"draft-page-{page:02}", region, "-ReadText")["text"]
        if readings and readings[-1] == text:
            unchanged += 1
            if unchanged == 3:
                break
        else:
            unchanged = 0
            readings.append(text)
            (driver.output / "draft-pages.json").write_text(
                json.dumps(readings, indent=2, ensure_ascii=False), encoding="utf-8")
        driver.act("scroll-carrier-readonly", SCROLL, params)
        time.sleep(0.75)
        frame = driver.frame(f"draft-scroll-{page:02}")
    driver.audit.append("verification", step_id="draft-page-count", pages=len(readings))


def probe(driver, ordinal, *, scan=False):
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
    if scan:
        scan_draft(driver, frame)
    print(json.dumps({"candidate": ordinal, "evidence": "census.json"}))


def scan_local(driver):
    frame = driver.frame("before-local-navigation")
    driver.require_foreground()
    driver.locate_exact_text("verify-scm-project", frame, "SCMessenger", (116, 811, 265, 852))
    point = driver.locate_exact_text("locate-scm-project-row", frame, "SCMessenger", (128, 858, 280, 891))
    driver.yes("verify-scm-project-row", frame,
               "Does SCMessenger appear as a chat row immediately below its same-named folder?",
               region=(92, 810, 300, 891))
    driver.act("navigate-local-candidate", CLICK,
               {"control": "SCMessenger chat under SCMessenger project", "point": point, "size": list(frame.size)})
    time.sleep(8)
    scan_draft(driver, driver.frame("selected-local-candidate"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("search", "query", "probe", "scan-local", "scan-current"))
    parser.add_argument("--ordinal", type=int, choices=(1, 2))
    parser.add_argument("--scan-draft", action="store_true")
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
        elif args.phase == "scan-local":
            scan_local(driver)
        elif args.phase == "scan-current":
            scan_draft(driver, driver.frame("local-carrier-continuation"), continuation=True)
        else:
            probe(driver, args.ordinal, scan=args.scan_draft)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        driver.audit.append("escalation", step_id=args.phase, reason=str(error))
        print(f"BLOCKED: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
