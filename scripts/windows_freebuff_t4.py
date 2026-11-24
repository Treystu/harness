"""Inspect both exact SCMessenger search results without touching their composers."""

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

from driver_core import osal

from .windows_freebuff_dispatch import CLICK, FOCUS, SCM_THREAD, SCROLL, TITLE, Dispatch


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
    path = (driver.output / f"{label}.png").resolve()
    driver.image_ops.invert(driver.image_ops.grayscale(crop)).save(path)
    helper = Path(__file__).with_name("windows_ocr_exact.ps1")
    response = osal.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-File",
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


def scan_transcript(driver, frame):
    driver.yes("verify-cloud-transcript", frame,
               "Does the toolbar show the word Cloud next to a cloud icon?",
               region=(1325, 1045, 1462, 1104))
    params = {"point": [1280, 450], "size": list(frame.size), "delta": 120}
    readings = []
    for page in range(1, 9):
        text = inspect_crop(driver, frame, f"transcript-page-{page}", (632, 70, 1538, 625), "-ReadText")["text"]
        if not readings or readings[-1] != text:
            readings.append(text)
        driver.act("scroll-transcript-readonly", SCROLL, params)
        time.sleep(0.85)
        frame = driver.frame(f"transcript-scroll-{page}")
    (driver.output / "transcript-pages.json").write_text(
        json.dumps(readings, indent=2, ensure_ascii=False), encoding="utf-8")
    driver.audit.append("extraction", step_id="transcript-page-count", pages=len(readings))


def probe(driver, ordinal, *, scan=False, transcript=False):
    driver.require_foreground()
    region = (546, 249, 1140, 926)
    for attempt, delay in enumerate((3, 4, 6), start=1):
        time.sleep(delay)
        frame = driver.frame(f"search-candidates-{attempt}")
        footer = inspect_crop(driver, frame, f"search-footer-{attempt}",
                              (1050, 943, 1304, 990), "-ReadText")["text"]
        if "loading" not in footer.casefold():
            break
    else:
        raise RuntimeError("SCMessenger search results did not finish loading")
    point = inspect_crop(driver, frame, "candidate-ocr", region,
                         "-Label", "SCMessenger", "-Ordinal", str(ordinal))
    x, y = region[0] + round(point["x"] / 2), region[1] + round(point["y"] / 2)
    driver.yes("verify-scm-candidate", frame,
               "Does this exact search result read SCMessenger with no additional words?",
               region=(543, y - 20, 1040, y + 20))
    fresh = driver.frame("search-candidates-before-click")
    if frame.crop(region).tobytes() != fresh.crop(region).tobytes():
        raise RuntimeError("SCMessenger search results changed during verification")
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
    if transcript:
        scan_transcript(driver, frame)
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


def project_roster(structure):
    groups = [group for group in structure["groups"]
              if group["name"] == "SCMessenger"
              and group["kind"] in {"ControlType.List", "ControlType.Tree", "ControlType.Group"}
              and any(row["kind"] in {"ControlType.ListItem", "ControlType.TreeItem", "ControlType.Hyperlink"}
                      for row in group["children"])]
    if len(groups) != 1:
        raise RuntimeError("the SCMessenger project did not expose a unique bounded chat list")
    group = groups[0]
    rows = []
    for item in group["children"]:
        name = item["name"].strip()
        if name in {"Show more", "Load more", "More chats"}:
            return rows, item
        if item["kind"] in {"ControlType.ListItem", "ControlType.TreeItem", "ControlType.Hyperlink"} and name:
            rows.append(item)
    if group["partial"] or not rows:
        raise RuntimeError("the project exposed a partial or empty chat list")
    return rows, None


def navigate_roster_row(driver, frame, row, step):
    if row["hidden"] or len(row["bounds"]) != 4:
        raise RuntimeError(f"{step}: the verified roster row is offscreen")
    bounds = driver.compositor_bounds()
    x, y, width, height = row["bounds"]
    x, y = round(x - bounds.left), round(y - bounds.top)
    right, bottom = round(x + width), round(y + height)
    if not (80 <= x < right <= 390 and 225 <= y < bottom <= 1050):
        raise RuntimeError(f"{step}: the roster row falls outside the project sidebar")
    label = row["name"].strip()
    region = (x, y, right, bottom)
    driver.locate_exact_text(f"{step}-ocr", frame, label, region)
    driver.yes(f"{step}-visible", frame, f"Does the printed text read {label!r}?", region=region)
    fresh = driver.frame(f"{step}-before-click")
    if frame.crop(region).tobytes() != fresh.crop(region).tobytes():
        raise RuntimeError(f"{step}: the roster row changed during verification")
    driver.act(step, CLICK, {"control": f"SCMessenger project list: {label}",
                             "point": [(x + right) // 2, (y + bottom) // 2],
                             "size": list(frame.size)})


def census_signature(fields):
    toolbar = fields["toolbar"].casefold()
    history = (fields["transcript-upper"] + "\n" + fields["transcript-lower"]).casefold()
    identities = fields["document_sessions"]
    return (len(identities) == 1 and identities[0].startswith(f"{SCM_THREAD}-")
            and bool(re.search(r"\blocal\b", toolbar))
            and "deepseek v4.1 flash slow" in toolbar
            and 20 <= fields["rail_marks"] <= 24
            and ("#745" in history or "cab43b2" in history)
            and "#746" in history)


def scroll_project_sidebar(driver, frame, step, delta):
    for attempt in range(3):
        try:
            driver.act(step, SCROLL, {"point": [196, 850], "size": list(frame.size), "delta": delta})
            return
        except RuntimeError as error:
            if "compositor geometry changed after capture" not in str(error) or attempt == 2:
                raise
            frame = driver.frame(f"{step}-geometry-retry-{attempt}")
    raise RuntimeError("project sidebar scroll did not complete")


def visual_project_pages(driver, frame):
    """Yield the SCM project chat rows on each verified, overlapping sidebar page."""
    started = False
    previous = []
    for page in range(24):
        reading = inspect_crop(driver, frame, f"sidebar-page-{page}", (95, 294, 321, 1058), "-ReadLines")
        lines = []
        for line in reading["lines"]:
            if line["text"] in {"Show more", "More chats"}:
                first = line["words"][0]
                lines.append((line["text"], 95 + first["x"] / 2, 294 + first["y"] / 2))
                continue
            words = [word for word in line["words"] if 95 + word["x"] / 2 >= 114]
            if words:
                label = " ".join(word["text"] for word in words)
                lines.append((label, 95 + words[0]["x"] / 2, 294 + words[0]["y"] / 2))
        roster = []
        expand = None
        ended = False
        # A newly visible SCM heading supersedes any continuation state: rows
        # and controls above it belong to a different project.
        has_anchor = any(114 <= x < 128 and label == "SCMessenger" for label, x, _ in lines)
        in_project = started and not has_anchor
        anchored = False
        for label, x, y in lines:
            heading = 114 <= x < 128
            if heading and label == "SCMessenger":
                in_project = anchored = True
                roster = []
                driver.yes(f"verify-project-heading-{page}", frame,
                           "Is the folder label SCMessenger in the project sidebar?",
                           region=(88, round(y - 5), 280, round(y + 23)))
                continue
            if not in_project:
                continue
            # The fixed footer overlays the scrolling list; it is not a project boundary.
            if label == "Invite friends":
                continue
            if heading:
                if anchored or roster:
                    ended = True
                    break
                continue
            if label in {"Show more", "More chats"} and x < 120:
                if not anchored:
                    raise RuntimeError("project expansion lacks a visible SCMessenger heading")
                expand = (label, y)
                break
            if 128 <= x <= 150:
                roster.append((label, y))
        if expand:
            label, y = expand
            region = (103, round(y - 5), 246, round(y + 23))
            point = driver.locate_exact_text(f"expand-scm-ocr-{page}", frame, label, region)
            driver.yes(f"verify-expand-scm-{page}", frame,
                       f"Does the navigation control read {label!r}?", region=region)
            fresh = driver.frame(f"expand-scm-readback-{page}")
            if frame.crop(region).tobytes() != fresh.crop(region).tobytes():
                raise RuntimeError("the project expansion control moved")
            driver.act(f"expand-scm-project-{page}", CLICK, {
                "control": "Show more within SCMessenger project", "point": point, "size": list(frame.size),
            })
            time.sleep(1.25)
            frame = driver.frame(f"scm-expanded-{page}")
            continue
        if anchored or (started and roster):
            names = [label for label, _ in roster]
            overlap = 0
            if started and not anchored and previous:
                overlap = next((n for n in range(min(len(previous), len(names)), 0, -1)
                                if previous[-n:] == names[:n]), 0)
                if not overlap:
                    raise RuntimeError("SCMessenger sidebar pages have no verified overlapping chat row")
            if anchored and started:
                if names[:len(previous)] != previous:
                    raise RuntimeError("the SCMessenger roster reordered")
                overlap = len(previous)
            started = True
            previous = names
            yield frame, page, roster[overlap:]
            if ended:
                return
        elif started and ended:
            return
        scroll_project_sidebar(driver, frame, f"scroll-project-sidebar-{page}", -240)
        time.sleep(1)
        fresh = driver.frame(f"scm-sidebar-scroll-{page}")
        if fresh.crop((95, 294, 321, 1046)).tobytes() == frame.crop((95, 294, 321, 1046)).tobytes():
            raise RuntimeError("project sidebar stopped moving before a verified end of the roster")
        frame = fresh
    raise RuntimeError("project sidebar exceeded its bounded census")


def observe_census_candidate(driver, frame, title, index):
    regions = CENSUS_REGIONS | {"composer": (640, 745, 1538, 1054), "toolbar": (680, 1044, 1480, 1104)}
    with ThreadPoolExecutor(max_workers=3) as pool:
        samples = {name: pool.submit(inspect_crop, driver, frame, f"census-{index}-{name}", rect, "-ReadText")
                   for name, rect in regions.items() if name not in {"project", "right-rail"}}
        fields = {name: task.result()["text"] for name, task in samples.items()}
    rail = frame.crop((1750, 130, 1763, 555)).convert("L")
    marks = [sum(rail.getpixel((x, y)) > 90 for x in range(rail.width)) >= 8 for y in range(rail.height)]
    fields.update(title=title, document_sessions=driver.read_app_structure(),
                  rail_marks=sum(on and (y == 0 or not marks[y - 1]) for y, on in enumerate(marks)))
    return fields


def append_census(driver, evidence, fields):
    evidence.append(fields)
    (driver.output / "project-census.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                                                        encoding="utf-8")


def reacquire_project_row(driver, label, step):
    """Find the row again beneath the visible SCM heading after an app auto-scroll."""
    for attempt in range(12):
        frame = driver.frame(f"{step}-reacquire-{attempt}")
        reading = inspect_crop(driver, frame, f"{step}-reacquire-roster-{attempt}",
                               (95, 294, 321, 1058), "-ReadLines")
        lines = []
        for line in reading.get("lines", []):
            words = [word for word in line["words"] if 95 + word["x"] / 2 >= 114]
            if words:
                lines.append((" ".join(word["text"] for word in words),
                              95 + words[0]["x"] / 2, 294 + words[0]["y"] / 2))
        anchors = [i for i, (name, x, _) in enumerate(lines) if name == "SCMessenger" and 114 <= x < 128]
        if len(anchors) > 1:
            raise RuntimeError("multiple SCM project headings appeared during reacquisition")
        if anchors:
            start = anchors[0]
            candidates = []
            for name, x, y in lines[start + 1:]:
                if 114 <= x < 128:
                    break
                if 128 <= x <= 150 and similar_census_label(label, name):
                    candidates.append((name, y))
            if len(candidates) > 1:
                raise RuntimeError("the project row was ambiguous after reacquisition")
            if candidates:
                driver.yes(f"{step}-reacquire-project", frame,
                           "Is the folder label SCMessenger visible above the chat rows?",
                           region=(88, round(lines[start][2] - 5), 280, round(lines[start][2] + 23)))
                return frame, candidates[0][1]
        scroll_project_sidebar(driver, frame, f"{step}-reacquire-scroll-{attempt}", 240)
        time.sleep(1)
    raise RuntimeError("the SCM project row could not be reacquired under its visible heading")


def visual_select_row(driver, frame, label, y, step, *, reacquire=True):
    scope = (127, round(y - 5), 318, round(y + 23))
    fresh = driver.frame(f"{step}-before")
    # Opening a preceding candidate changes sidebar styling. Re-identify this
    # row on the fresh frame; retain the stability check immediately before input.
    rows = driver.read_roster(f"{step}-fresh-roster", fresh, scope)
    current_label = rows[0]["text"].strip() if len(rows) == 1 else ""
    if not current_label or not similar_census_label(label, current_label):
        if not reacquire:
            raise RuntimeError("the fresh census row no longer matches the roster")
        frame, new_y = reacquire_project_row(driver, label, step)
        return visual_select_row(driver, frame, label, new_y, step, reacquire=False)
    point = driver.locate_exact_text(f"{step}-ocr", fresh, current_label, scope, scale=2)
    words = current_label.split()
    question = (f"Does this sidebar chat label start with {' '.join(words[:-1])!r}?" if len(words) >= 3
                else f"Does the sidebar text read {current_label!r}?")
    driver.yes(f"{step}-verify", fresh, question, region=scope)
    current = driver.frame(f"{step}-ready")
    if current.crop(scope).tobytes() != fresh.crop(scope).tobytes():
        raise RuntimeError("SCMessenger chat row changed before selection")
    driver.act(step, CLICK, {
        "control": f"SCMessenger project chat {current_label}", "point": point, "size": list(fresh.size),
    })
    return current_label


def similar_census_label(old, new):
    old, new = old.casefold().strip(), new.casefold().strip()
    return old == new or (len(old) >= 12 and len(new) >= 12 and old[:12] == new[:12]
                          and SequenceMatcher(None, old, new).ratio() >= 0.9)


def validate_census_inventory(inventory):
    if not inventory or len({name.casefold() for name in inventory}) != len(inventory):
        raise RuntimeError("the complete project roster is empty or has ambiguous visible titles")
    for index, name in enumerate(inventory):
        if any(similar_census_label(name, other) for other in inventory[index + 1:]):
            raise RuntimeError("the project roster has visually ambiguous truncated titles")


def visual_census(driver, frame):
    # Inventory without opening chats: FreeBuff moves opened chats to the top.
    inventory = []
    for _, _, rows in visual_project_pages(driver, frame):
        inventory.extend(label for label, _ in rows)
    (driver.output / "project-roster.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2),
                                                       encoding="utf-8")
    validate_census_inventory(inventory)
    evidence = []
    root = driver.output
    for index, expected in enumerate(inventory):
        driver.output = root / f"candidate-{index:03}"
        driver.output.mkdir(parents=True, exist_ok=True)
        try:
            frame = driver.scroll_sidebar_to_top()
            found = False
            for page_frame, page, rows in visual_project_pages(driver, frame):
                for label, y in rows:
                    if not similar_census_label(expected, label):
                        continue
                    label = visual_select_row(driver, page_frame, label, y, f"visual-census-select-{page}-{index}")
                    time.sleep(7)
                    opened = driver.frame(f"visual-census-{index}-open")
                    fields = observe_census_candidate(driver, opened, label, index + 1)
                    found = True
                    break
                if found:
                    break
            if not found:
                raise RuntimeError(f"the inventoried project row {expected!r} could not be reopened")
        finally:
            driver.output = root
        append_census(driver, evidence, fields)
    matches = [index for index, fields in enumerate(evidence) if census_signature(fields)]
    driver.audit.append("verification", step_id="visual-project-census-verdict",
                        inspected=len(evidence), matches=matches)
    if len(matches) != 1:
        raise RuntimeError(f"visual project census yielded {len(matches)} verified matches across {len(evidence)} rows")
    frame = driver.frame("scm-return-to-roster")
    driver.act("scroll-to-project-sidebar-top", SCROLL, {
        "point": [196, 850], "size": list(frame.size), "delta": 9600,
    })
    time.sleep(2)
    frame = driver.frame("scm-roster-top")
    target = inventory[matches[0]]
    for page_frame, _, rows in visual_project_pages(driver, frame):
        for label, y in rows:
            if similar_census_label(label, target):
                visual_select_row(driver, page_frame, label, y, "visual-reopen-unique-scm-match")
                time.sleep(3)
                reopened = driver.frame("visual-reopened-scm")
                if not census_signature(observe_census_candidate(driver, reopened, label, "reopened")):
                    raise RuntimeError("the reopened SCM view did not retain the complete identity signature")
                driver.prepare_draft()
                driver.send_draft()
                return
    raise RuntimeError("the unique SCM chat could not be reopened")


def settled_census_frame(driver):
    for attempt in range(8):
        frame = driver.frame(f"census-geometry-{attempt}")
        bounds = driver.compositor_bounds()
        if (abs(bounds.right - bounds.left - frame.width) <= 2
                and abs(bounds.bottom - bounds.top - frame.height) <= 2):
            return frame
        time.sleep(1)
    raise RuntimeError("FreeBuff capture and compositor geometry did not settle")


def census_project(driver):
    driver.goal = "Census the SCMessenger project's existing chat list and verify the pinned SCM session."
    frame = settled_census_frame(driver)
    if driver.window.api.foreground() != driver.window.handle:
        driver.verify_freebuff_logo(frame, "identify-census-window")
        driver.act("census-foreground", FOCUS, {"title": TITLE})
        frame = driver.frame("census-focused")
    frame = driver.close_search_if_open(frame)
    for attempt in range(8):
        structure = driver.read_app_structure("-Project", "SCMessenger")
        (driver.output / "project-structure.json").write_text(json.dumps(structure, ensure_ascii=False),
                                                               encoding="utf-8")
        if structure["anchors"] == 0:
            visual_census(driver, frame)
            return
        rows, expansion = project_roster(structure)
        if expansion is None:
            break
        navigate_roster_row(driver, frame, expansion, f"expand-project-list-{attempt}")
        time.sleep(1)
        frame = driver.frame(f"project-list-expanded-{attempt}")
    else:
        raise RuntimeError("the project list expansion did not reach its end")
    inventory = [(row["kind"], row["name"]) for row in rows]
    evidence = []
    for index, row in enumerate(rows, start=1):
        live, extra = project_roster(driver.read_app_structure("-Project", "SCMessenger"))
        if extra or [(item["kind"], item["name"]) for item in live] != inventory:
            raise RuntimeError("the bounded project roster changed during the census")
        navigate_roster_row(driver, frame, live[index - 1], f"census-select-{index}")
        time.sleep(3)
        frame = driver.frame(f"census-candidate-{index}")
        append_census(driver, evidence, observe_census_candidate(driver, frame, row["name"], index))
    matches = [index for index, fields in enumerate(evidence) if census_signature(fields)]
    driver.audit.append("verification", step_id="project-census-verdict",
                        inspected=len(evidence), matches=matches)
    if len(matches) != 1:
        raise RuntimeError(f"project census did not yield one pinned SCM match ({len(matches)} matches)")
    row_index = matches[0]
    live, extra = project_roster(driver.read_app_structure("-Project", "SCMessenger"))
    if extra or [(item["kind"], item["name"]) for item in live] != inventory:
        raise RuntimeError("the project roster changed after census")
    navigate_roster_row(driver, frame, live[row_index], "reopen-unique-scm-match")
    time.sleep(1.5)
    driver.verify_active_session()
    driver.prepare_draft()
    driver.send_draft()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True,
                        choices=("search", "query", "probe", "scan-local", "scan-current", "project-census"))
    parser.add_argument("--ordinal", type=int, choices=(1, 2))
    parser.add_argument("--scan-draft", action="store_true")
    parser.add_argument("--scan-transcript", action="store_true")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    key = os.environ.pop("TYPESAFE_API_KEY", "")
    if not key or (args.phase == "probe" and args.ordinal is None):
        parser.error("trusted child key and probe ordinal are required")
    args.evidence.mkdir()
    driver = Dispatch(args.evidence, key, thread=SCM_THREAD, scoped_input=True,
                      standing=args.phase == "project-census")
    try:
        if args.phase == "search":
            driver.open_search()
        elif args.phase == "project-census":
            census_project(driver)
        elif args.phase == "query":
            driver.search_for_session()
        elif args.phase == "scan-local":
            scan_local(driver)
        elif args.phase == "scan-current":
            scan_draft(driver, driver.frame("local-carrier-continuation"), continuation=True)
        else:
            probe(driver, args.ordinal, scan=args.scan_draft, transcript=args.scan_transcript)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        driver.audit.append("escalation", step_id=args.phase, reason=str(error))
        print(f"BLOCKED: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
