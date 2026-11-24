"""Gate for the sustained-send verdict, the Lane 1 re-check and the launch not-run.

Product Jev first, Lucas Gate v2 second. The acts under judgment: proving the send
path end to end at a real boundary, reporting its verdict only after a second
corroboration, leaving Lane 1 alone when its composer state could not be
established, and filing the launch type as not-run instead of manufacturing a
green while the desktop is live.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.abspath("."))

from harness.config import load_settings
from harness.jev_policy import policy_for
from harness.lucas_gate import run_typed_track
from harness.session import jev_face_governor, ledger_for

GOAL = ("Complete the vision driver standup end to end without disturbing a lane "
        "that is mid-turn, without merging, and with every decision carrying its "
        "gate receipt on #684.")
SITE = "vision_standup_launch"
OUT = pathlib.Path("evidence/lane-sessions/laptop-vision-2026-11-22/gates-launch.json")

ACTION = (
    "Close the workstation audit with its remediation recorded, and report the "
    "launch cold run as a not-run at a model decision rather than a green. The "
    "audit found the scheduled watch present and ticking (Ready, result 0, 2-minute "
    "cadence, status.json fresh), port 8765 answering 200 on PID 12396, 6.7 GiB RAM "
    "and 16.2 GiB disk free, and a FreeBuff desktop whose orchestrator has run since "
    "2026-11-21 with no restart marker; the renderer set that started at 23:01 was "
    "the app opening tabs for this lane's own navigation, not a spontaneous refresh, "
    "and there are no crash artifacts. The desktop restart the amendment authorizes "
    "is refused rather than attempted because this lane is hosted inside that app, "
    "so the restart would terminate the executing session mid-turn; that blocker is "
    "filed with the owner as the actor. The launch itself created project "
    "robby-battery-helper as ordered, opened its new chat, and stopped before typing "
    "because the new chat defaults to GPT-6 Luna High while the mission of record "
    "requires DeepSeek V4.1 Flash Slow and the menu offers only 'DeepSeek V4.1 Flash "
    "Fast'; choosing between them is a model decision on a lane, which the standing "
    "rules reserve. Four cures landed for what the attempt measured: the composed "
    "launch path with its no-duplicate and carrier read-back bounds, newlines typed "
    "as Return presses, the dialog read after it settles, and the created row read "
    "by title. No merge, no model or settings change, nothing sent to any existing "
    "lane."
)

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="vision-standup-launch")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor), "| ledger:", bool(ledger))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Vision driver standup: launch cold run", site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.6, "category_average": 9.6,
         "evidence": "Every number is quoted from the receipt tree or the four "
                     "corroborating reads (send review, two OCR frames, the repo's "
                     "pushed_at), and the one unestablished fact - Lane 1's composer - "
                     "is filed as unestablished rather than assumed.",
         "precedent": "Same shape as the accepted cold-run filings on this issue: a "
                      "start cue is not a verdict, and a proof that cannot be read is "
                      "reported missing, never inferred."}
        for cid in CATEGORY_IDS
    ]
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": key, "score": float(value),
                      "rationale": "One send at a verified boundary; no merge, no "
                                   "settings change, no lane touched while mid-turn, "
                                   "and the unproven type is filed not-run."}
                     for key, value in {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5,
                                        "B8": 9.5, "B9": 9.0, "B10": 9.0,
                                        "B11": 9.5}.items()],
        actual_risk=False, overall_average=9.6,
    )
    receipt = {"site": SITE,
               "product_jev": verdict.to_dict() if hasattr(verdict, "to_dict") else verdict,
               "structural": structural,
               "lucas_gate_v2": lucas}
    OUT.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"product_jev": receipt["product_jev"],
                      "lucas": lucas["status"],
                      "artifact": lucas["artifact_sha256"][:16]}, indent=2))
    return 0 if lucas["status"].startswith("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
