"""One scheduled checkpoint for the staged oversight cutover."""

import base64
import ctypes
import hashlib
import importlib.util
import json
import os
import re
import subprocess
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path

from driver_core.audit import AuditLog

from .windows_freebuff_dispatch import (
    BURN_SESSIONS, CONTINUATION, DISK_THREAD, SCM_THREAD, SESSIONS, THREAD, VISION_THREAD,
)
from .windows_freebuff_runner import BRANCH, ISSUE, LEDGER, OWNER_ID, UncertainDriverExit, api, approved, execute

CUTOVER = 7093801996
CENSUS = 7093745521
BURNDOWN = 7093818060
AMENDMENT = 7093866656
BURN_QUEUE = 7093946738
UNBLOCK = 7094012443
TRANSITION = 7094050344
FILL = 7094198934
STANDUP = 7111294374
LANE_RESTART = 7100931819
SCM_RESTART = 7097835295
REMAINING = 7095113042
ROBBY = 7094914841
SINCE = "2026-11-23T06:55:00Z"
DYNAMIC_SINCE = "2026-11-24T00:20:00Z"
DEFAULT_CONTROL_PATH = Path.home() / ".harness" / "driver-watch" / "control.json"
ROOT = f"{LEDGER}/contents/dispatch/laptop-driver/watch/{CUTOVER}"
WORKTREE = Path(__file__).resolve().parents[1]
RECEIPTS = {
    CUTOVER: "OVERSIGHT CUTOVER - RUNNER IS THE STANDING DISPATCH CHANNEL",
    CENSUS: "OVERSIGHT FOLLOW-UP DISPATCH - T4 ENUMERATION + T5 COMPLETION",
    BURNDOWN: "OVERSIGHT DISPATCH - TONIGHT'S BURNDOWN",
    AMENDMENT: "OVERSIGHT AMENDMENT TO BURNDOWN DISPATCH 7093818060",
    BURN_QUEUE: "OVERSIGHT DISPATCH - BURN QUEUE, NEXT 3 HOURS",
    UNBLOCK: "OVERSIGHT RULING - QUEUE UNBLOCK",
    TRANSITION: "OVERSIGHT DISPATCH - TRANSITION COMPLETION",
    FILL: "OVERSIGHT DISPATCH - MAX-VELOCITY FILL RULE",
    STANDUP: "VISION STANDUP REQUEST 2026-11-23",
    LANE_RESTART: "LANE CONTINUATION WATCH RESTART DISPATCH",
    SCM_RESTART: "LANE CONTINUATION WATCH",
    REMAINING: "OVERSIGHT DISPATCH - URGENT STANDUP",
    ROBBY: "OVERSIGHT DISPATCH - ROBBY PROJECT CREATION",
}


def issue_comment(message):
    return api(ISSUE, method="POST", body={"body": message})


def owner(comment):
    return comment.get("user", {}).get("id") == OWNER_ID


def validate_receipts():
    receipts = {}
    for number, heading in RECEIPTS.items():
        receipt = api(f"repos/Treystu/harness/issues/comments/{number}")
        if (not owner(receipt) or not receipt["body"].startswith(heading)
                or not receipt["issue_url"].casefold().endswith("/treystu/harness/issues/684")):
            raise RuntimeError(f"oversight receipt {number} did not match")
        receipts[number] = receipt
    return receipts


def pause_requested():
    page = 1
    while True:
        comments = api(f"{ISSUE}?since={SINCE}&per_page=100&page={page}")
        for comment in comments:
            lines = comment["body"].strip().splitlines()
            if owner(comment) and lines and lines[0].strip() in {"PAUSE", "VISION-DISPATCH PAUSE"}:
                return comment["id"]
        if len(comments) < 100:
            return None
        page += 1


def checkpoints():
    return {entry["name"] for entry in api(f"{ROOT}?ref={BRANCH}")}


def checkpoint(name, event):
    event["at"] = datetime.now(timezone.utc).isoformat()
    content = base64.b64encode((json.dumps(event) + "\n").encode()).decode()
    api(f"{ROOT}/{name}", method="PUT", body={
        "branch": BRANCH, "message": f"Checkpoint vision watch {name}", "content": content,
    })


def read_checkpoint(name):
    response = api(f"{ROOT}/{name}?ref={BRANCH}")
    return json.loads(base64.b64decode(response["content"]))


def guard_approval():
    pause = pause_requested()
    if pause:
        raise RuntimeError(f"oversight PAUSE {pause} revoked pending desktop actions")
    expected = os.environ.get("HARNESS_VISION_HEAD")
    if expected and worktree_head() != expected:
        raise RuntimeError("the published driver changed during the dispatch")


def _hidden_subprocess_kwargs():
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def local_control_state():
    raw = os.environ.get("HARNESS_DRIVER_CONTROL_FILE", "").strip()
    path = Path(raw) if raw else DEFAULT_CONTROL_PATH
    if not path.is_file():
        return {"enabled": True, "paused": False, "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"enabled": False, "paused": True, "path": str(path), "reason": "unreadable-control-file"}
    return {
        "enabled": bool(data.get("enabled", True)),
        "paused": bool(data.get("paused", False)),
        "path": str(path),
    }


def worktree_head():
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "scripts"],
                      cwd=WORKTREE, timeout=5, check=False, **_hidden_subprocess_kwargs()).returncode:
        return None
    result = subprocess.run(["git", "rev-parse", "HEAD", "@{upstream}"], cwd=WORKTREE,
                            capture_output=True, text=True, timeout=5, check=False,
                            **_hidden_subprocess_kwargs())
    heads = result.stdout.splitlines()
    return heads[0] if result.returncode == 0 and len(heads) == 2 and heads[0] == heads[1] else None


RUNTIME_MODULES = ("windows_capture", "PIL", "driver_core")


def require_driver_runtime():
    """Refuse by name when the driving runtime is absent, before any claim.

    The documented proof venv under %TEMP% is not durable (measured 2026-11-24:
    it no longer exists), so the interpreter that runs the watch is the only
    runtime there is. Checked at the moment a dispatch would execute - not at
    tick start - so the heartbeat keeps reporting liveness while the refusal
    names exactly what is missing instead of failing inside a phase.
    """
    missing = [name for name in RUNTIME_MODULES
               if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError("driver runtime missing: " + ", ".join(missing))


def desktop_idle():
    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    status = LastInput(ctypes.sizeof(LastInput))
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(status)):
        raise RuntimeError("Windows last-input state is unavailable")
    elapsed = (ctypes.windll.kernel32.GetTickCount() - status.dwTime) & 0xffffffff
    return elapsed >= 60_000


def heartbeat(known, state):
    now = datetime.now(timezone.utc)
    bucket = now.strftime("%Y%m%d-%H") + f"-{now.minute // 15}"
    name = f"heartbeat-{bucket}.json"
    if name not in known:
        checkpoint(name, {"state": state})
        issue_comment(f"Vision watch {CUTOVER} heartbeat. {state}.")


def cure_eligible(output, reasons, allowed_actions=()):
    traces = sorted(output.glob("**/driver.jsonl"))
    receipt = output / "runner.jsonl"
    if not traces or not receipt.is_file() or not AuditLog(receipt).verify().ok:
        return False
    if any(not AuditLog(trace).verify().ok for trace in traces):
        return False
    results = [json.loads(line) for line in receipt.read_text(encoding="utf-8").splitlines()]
    if not any(r["step_id"] == "result" and all(reason in r["state"] for reason in reasons)
               for r in results):
        return False
    for trace in traces:
        for line in trace.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["kind"] != "action":
                continue
            params = row.get("consent", {}).get("params", {})
            if (row.get("action") in {"send_freebuff", "type_freebuff"}
                    or "composer" in params.get("control", "").casefold()
                    or (row.get("ok") and row["step_id"] not in allowed_actions)):
                return False
    return True


def _lane_thread_from_dispatch(body):
    thread_pattern = re.compile(r"\b(" + "|".join(re.escape(tid) for tid in SESSIONS) + r")\b")
    match = thread_pattern.search(body)
    if match:
        return match.group(1)
    lane_aliases = (
        ("scmessenger", SCM_THREAD),
        ("lane 1", THREAD),
        ("disk audit", DISK_THREAD),
        ("vision driver standup", VISION_THREAD),
    )
    lane_line = re.search(r"^Lane:\s*(.+)$", body, re.I | re.M)
    if lane_line:
        text = lane_line.group(1).casefold()
        for alias, tid in lane_aliases:
            if alias in text:
                return tid
    return None


RUNNER_ACTION = re.compile(r"^Action\s+(?:for\s+the\s+runner|requested)\b", re.I | re.M)
DISPATCH_BANNER = re.compile(r"^(?:VISION\s+DRIVER\s+)?(?:RESTART\s+)?DISPATCH\b", re.I)


def restart_dispatch(body):
    """Is this comment a restart dispatch, whatever banner the oversight used?

    The header used to have to start with the literal words "RESTART DISPATCH".
    Dispatch 7122154514 instead leads with "DISPATCH - LANE 1 RESTART, RETRY
    UNDER THE CURED BOUND", so the reserved retry was unclaimable while the
    watch reported "no unclaimed dispatches". A banner that opens with DISPATCH
    counts only when RESTART is named in the same opening block; the runner's
    instruction line and the exact quoted continuation are still required by
    the caller, so naming a lane is not by itself an instruction.
    """
    if not DISPATCH_BANNER.match(body):
        return False
    if body.upper().startswith("RESTART DISPATCH"):
        return True
    return "RESTART" in body[:600].upper()


def filed_on_issue(comments, dispatch_id):
    """Has this dispatch already been acked or resulted on the issue?

    Dispatches are executed by more than one channel (the runner alone under the
    cutover, and the web seat inside its own turn boundary). A restart that was
    already executed therefore has no local claim checkpoint, so the durable
    GitHub receipt is the only evidence that the at-most-once rule is intact.
    Widening the accepted wording without this check would re-run an older,
    already-executed restart - measured on #684: the SCMessenger restart
    7117989632 was acked at 7119856718 and its leg was later ruled closed.
    """
    pattern = re.compile(
        rf"Vision (?:restart )?(?:ack|result) #{dispatch_id}\b|#{dispatch_id}\b[^\n]*ack",
        re.I)
    return any(pattern.search(comment.get("body") or "") for comment in comments)


def parse_dynamic_dispatch(comment, now=None):
    """Validate an owner-filed VISION-DISPATCH or RESTART DISPATCH comment under cutover bounds."""
    if not owner(comment):
        return None
    cid = comment.get("id")
    if cid in RECEIPTS or cid == 7091945084:
        return None
    now = now or datetime.now(timezone.utc)
    body = (comment.get("body") or "").strip()
    if not body:
        return None
    try:
        blob = approved(comment, now)
    except RuntimeError:
        blob = None
    if blob is not None:
        mission, digest = blob
        return {
            "kind": "vision-dispatch",
            "comment_id": cid,
            "thread": mission["thread"],
            "text": mission["text"],
            "digest": digest,
        }
    # The oversight files the instruction line as either "Action for the runner:"
    # (early dispatches) or "Action requested (runner alone, ...)" (the L1-STOP
    # episode and later). Both are the same bounded restart; anything else is not
    # an instruction and is never claimed.
    if not (restart_dispatch(body) and RUNNER_ACTION.search(body)):
        return None
    # The instruction may be wrapped mid-quote: 7122154514 writes
    # '"continue in\nfull"'. Compare the flattened text so the required words
    # survive a line break, while the digest stays over the comment as filed.
    flat = re.sub(r"\s+", " ", body)
    if f'"{CONTINUATION}"' not in flat and f"'{CONTINUATION}'" not in flat:
        return None
    created = comment.get("created_at")
    if created:
        created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if now - created_at > timedelta(hours=24):
            return None
    if (re.search(r"^(?:Target|App):\s*antigravity\b", body, re.I | re.M)
            or re.search(r"\brestart\s+the\s+antigravity\b", body, re.I)):
        return {
            "kind": "antigravity-park",
            "comment_id": cid,
            "thread": "antigravity",
            "reason": "antigravity-adapter-not-calibrated",
        }
    thread = _lane_thread_from_dispatch(body)
    if not thread or thread not in SESSIONS:
        return None
    return {
        "kind": "restart",
        "comment_id": cid,
        "thread": thread,
        "text": CONTINUATION,
        "digest": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def poll_dynamic_dispatches(known, *, now=None):
    """Poll #684 for new owner-approved dispatches and execute at most one unclaimed item."""
    now = now or datetime.now(timezone.utc)
    comments = []
    page = 1
    while True:
        batch = api(f"{ISSUE}?since={DYNAMIC_SINCE}&per_page=100&page={page}")
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    comments.sort(key=lambda item: item.get("id", 0))
    state_dir = Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner"
    for comment in comments:
        parsed = parse_dynamic_dispatch(comment, now=now)
        if not parsed:
            continue
        cid = parsed["comment_id"]
        thread = parsed["thread"]
        item = f"dyn-{cid}-{thread}"
        claim = f"claim-{item}.json"
        if claim in known:
            # At-most-once stands: a claimed dispatch is never re-run by this
            # watch. Product Jev escalated the one-shot auto-retry draft
            # (advances 0.52, destructive 0.21, confidence 0.31), so retry
            # authority is oversight's to grant, not this code's to assume.
            continue
        if parsed["kind"] == "restart" and filed_on_issue(comments, cid):
            # Already executed through another channel: claim nothing, send
            # nothing, and file no duplicate verdict.
            continue
        guard_approval()
        if parsed["kind"] == "antigravity-park":
            checkpoint(claim, {"dispatch": cid, "target": "antigravity", "kind": parsed["kind"]})
            status = f"parked: {parsed['reason']}"
            checkpoint(f"result-{item}.json", {"dispatch": cid, "target": "antigravity", "state": status})
            issue_comment(f"Vision watch #{cid} / `antigravity`: {status}. FreeBuff remains active.")
            return True
        require_driver_runtime()
        if not desktop_idle():
            heartbeat(known, "waiting for owner desktop idle")
            return True
        checkpoint(claim, {"dispatch": cid, "thread": thread, "sha256": parsed["digest"]})
        out = state_dir / item
        try:
            out.mkdir(parents=True, exist_ok=True)
            mission = {"thread": thread, "dispatch": cid, "standing": True}
            # The R9 bound applies here too: a full session-list walk routinely
            # needs more than the 65 s default. Measured on the Lane 1 dispatch
            # 7119751841 (2026-11-24T04:25Z): the walk was killed at the default
            # deadline after two scroll steps, with no input sent.
            mission["phase_timeout"] = 240
            status = "parked" if execute(out, item, mission, parsed["digest"], ()) else "verified running"
        except UncertainDriverExit as error:
            checkpoint(f"interlock-{item}.json", {"dispatch": cid, "thread": thread, "state": str(error)})
            issue_comment(f"Vision watch desktop interlock #{cid} / `{thread}`. {error}")
            status = "parked with desktop interlock"
        except (OSError, RuntimeError) as error:
            status = f"parked after claim: {error}"
            issue_comment(f"Vision watch #{cid} / `{thread}` {status}.")
        checkpoint(f"result-{item}.json", {"dispatch": cid, "thread": thread, "state": status})
        return True
    return False


def run_burn(receipts, known):
    source = receipts[BURN_QUEUE]
    end = datetime.fromisoformat(source["created_at"]) + timedelta(hours=3)
    if datetime.now(timezone.utc) >= end:
        if poll_dynamic_dispatches(known):
            return
        heartbeat(known, "dynamic oversight dispatch active; no unclaimed dispatches")
        return
    digest = hashlib.sha256(source["body"].encode()).hexdigest()
    queue = [(CENSUS, SCM_THREAD), *((BURN_QUEUE if thread == "918dad1a" else BURNDOWN, thread)
                                    for thread in BURN_SESSIONS if thread != "0319b9f6")]
    now = datetime.now(timezone.utc)
    if FILL in receipts:
        hawaii = timezone(timedelta(hours=-10))
        refill = datetime.fromisoformat(receipts[FILL]["created_at"]).astimezone(hawaii)
        midnight = refill.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        if now < midnight:
            queue.append((FILL, "0319b9f6"))
    work = []
    state_dir = Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner"
    for dispatch_id, thread in queue:
        item = f"{dispatch_id}-{thread}"
        if f"claim-{item}.json" not in known:
            work.append((dispatch_id, thread, item))
        else:
            logo = f"{item}-native-logo-cure"
            if f"result-{item}.json" in known and cure_eligible(state_dir / item, ("identify-", "requires 0.90")):
                work.append((dispatch_id, thread, logo))
            if dispatch_id == CENSUS and f"result-{logo}.json" in known and cure_eligible(
                    state_dir / logo, ("did not expose a unique bounded chat list",)):
                work.append((dispatch_id, thread, f"{item}-visual-roster-cure"))
            visual = f"{item}-visual-roster-cure"
            if dispatch_id == CENSUS and f"result-{visual}.json" in known and cure_eligible(
                    state_dir / visual, ("project-census: driver exited unsuccessfully",)):
                work.append((dispatch_id, thread, f"{item}-ocr-line-shape-cure"))
            shaped = f"{item}-ocr-line-shape-cure"
            if dispatch_id == CENSUS and f"result-{shaped}.json" in known and cure_eligible(
                    state_dir / shaped, ("search dialog state is ambiguous",),
                    ("observation-foreground", "census-foreground")):
                work.append((dispatch_id, thread, f"{item}-search-dismiss-cure"))
            if thread in {"7d4a9b14", "918dad1a"} and f"result-{item}.json" in known and cure_eligible(
                    state_dir / item, ("exact OCR label", "was not verified"),
                    ("search-foreground", "close-old-search", "open-session-search",
                     "focus-search-field", "query-session", "observation-foreground", "navigate-to-bystander")):
                work.append((dispatch_id, thread, f"{item}-full-title-cure"))
    for dispatch_id, thread, item in work:
        claim = f"claim-{item}.json"
        if claim in known:
            continue
        guard_approval()
        require_driver_runtime()
        if not desktop_idle():
            heartbeat(known, "waiting for owner desktop idle")
            return
        # A create-only remote claim is the at-most-once boundary, including crashes.
        authorization = receipts.get(dispatch_id, source)
        claim_digest = hashlib.sha256(authorization["body"].encode()).hexdigest() if dispatch_id != BURNDOWN else digest
        checkpoint(claim, {"dispatch": dispatch_id, "queue": BURN_QUEUE, "thread": thread, "sha256": claim_digest})
        out = state_dir / item
        try:
            out.mkdir(parents=True)
            mission = {"thread": thread, "dispatch": dispatch_id, "standing": True}
            if dispatch_id == CENSUS:
                mission["phases"] = ("project-census",)
                mission["phase_timeout"] = 480
            status = "parked" if execute(out, item, mission, claim_digest, ()) else "verified running"
        except UncertainDriverExit as error:
            checkpoint(f"interlock-{item}.json", {"dispatch": dispatch_id, "thread": thread, "state": str(error)})
            issue_comment(f"Vision watch desktop interlock #{dispatch_id} / `{thread}`. {error}")
            status = "parked with desktop interlock"
        except (OSError, RuntimeError) as error:
            status = "parked after claim"
            issue_comment(f"Vision watch #{dispatch_id} / `{thread}` {status}. {error}")
        checkpoint(f"result-{item}.json", {"dispatch": dispatch_id, "thread": thread, "state": status})
        return
    heartbeat(known, "no unclaimed burn rows; parked rows stay isolated")


def run_restoration(receipts, known):
    state_dir = Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner"
    queue = ((STANDUP, VISION_THREAD), (LANE_RESTART, THREAD), (SCM_RESTART, SCM_THREAD),
             (REMAINING, "0319b9f6"))
    for dispatch_id, thread in queue:
        item = f"restore-{dispatch_id}-{thread}"
        if f"claim-{item}.json" in known:
            resumed = state_dir / f"restore-{STANDUP}-{VISION_THREAD}-vision-transcript-crop-cure"
            resume_trace = resumed / "vision-resume" / "driver.jsonl"
            resume_runner = resumed / "runner.jsonl"
            staged_item = f"restore-{STANDUP}-{VISION_THREAD}-start-staged-mission"
            focus_item = f"restore-{STANDUP}-{VISION_THREAD}-start-focus-cure"
            if dispatch_id == STANDUP and f"result-{staged_item}.json" in known:
                prior_start = state_dir / staged_item / "vision-start-staged" / "driver.jsonl"
                prior_run = state_dir / staged_item / "runner.jsonl"
                if (f"claim-{focus_item}.json" not in known and prior_start.is_file()
                        and prior_run.is_file() and AuditLog(prior_start).verify().ok
                        and AuditLog(prior_run).verify().ok):
                    attempts = [json.loads(line) for line in prior_start.read_text(encoding="utf-8").splitlines()]
                    clicks = [row for row in attempts if row.get("step_id") == "vision-submit-staged-mission"
                              and row.get("kind") == "action"]
                    if (len(clicks) == 1 and not clicks[0].get("ok")
                            and "FreeBuff is not the foreground window" in clicks[0].get("detail", "")):
                        staged_item = focus_item
            staged = False
            if (dispatch_id == STANDUP and f"claim-{staged_item}.json" not in known
                    and resume_trace.is_file() and resume_runner.is_file()
                    and AuditLog(resume_trace).verify().ok and AuditLog(resume_runner).verify().ok):
                events = [json.loads(line) for line in resume_trace.read_text(encoding="utf-8").splitlines()]
                resumed_actions = [row for row in events if row.get("step_id") == "vision-resume"
                                   and row.get("kind") == "action" and row.get("ok")]
                start_actions = [row for row in events if row.get("step_id") in {"vision-start", "send-once"}
                                 and row.get("kind") == "action"]
                staged = len(resumed_actions) == 1 and not start_actions
            if staged:
                item = staged_item
            elif dispatch_id == SCM_RESTART and f"result-{item}.json" in known:
                previous = state_dir / item
                receipt = previous / "runner.jsonl"
                traces = list(previous.glob("**/driver.jsonl"))
                if (not receipt.is_file() or not AuditLog(receipt).verify().ok or not traces
                        or any(not AuditLog(trace).verify().ok for trace in traces)):
                    continue
                results = [json.loads(line) for line in receipt.read_text(encoding="utf-8").splitlines()]
                if not any(row.get("step_id") == "result" and
                           "search: driver tree termination unverified" in row.get("state", "")
                           for row in results):
                    continue
                actions = [json.loads(line) for trace in traces
                           for line in trace.read_text(encoding="utf-8").splitlines()]
                if any(row["kind"] == "action" and (
                    row.get("action") not in {"click_freebuff", "scroll_freebuff", "focus_freebuff"}
                    or "composer" in row.get("consent", {}).get("params", {}).get("control", "").casefold()
                ) for row in actions):
                    continue
                item += "-project-roster-cure"
                if f"claim-{item}.json" in known:
                    if (f"result-{item}.json" not in known or not cure_eligible(
                            state_dir / item, ("executor 'scroll_freebuff' is already registered",),
                            ("observation-foreground", "navigate-to-bystander"))):
                        continue
                    item += "-scroll-registration-cure"
                    if f"claim-{item}.json" in known:
                        if (f"result-{item}.json" not in known or not cure_eligible(
                                state_dir / item, ("a census row moved during project navigation",),
                                ("observation-foreground", "navigate-to-bystander", "census-foreground",
                                 "scroll-project-sidebar-0", "scroll-project-sidebar-1",
                                 "visual-census-select-2-0"))):
                            continue
                        item += "-fresh-row-ocr-cure"
                        if f"claim-{item}.json" in known:
                            if (f"result-{item}.json" not in known or not cure_eligible(
                                    state_dir / item, ("exact OCR label 'SCMessenger Audit Lar'",),
                                    ("observation-foreground", "navigate-to-bystander", "census-foreground",
                                     "scroll-project-sidebar-0", "scroll-project-sidebar-1",
                                     "visual-census-select-2-0"))):
                                continue
                            item += "-fresh-label-cure"
                            if f"claim-{item}.json" in known:
                                if (f"result-{item}.json" not in known or not cure_eligible(
                                        state_dir / item, ("exact OCR label 'SCMessenger Audit Lar'",),
                                        ("observation-foreground", "navigate-to-bystander", "census-foreground",
                                         "scroll-project-sidebar-0", "scroll-project-sidebar-1",
                                         "visual-census-select-2-0"))):
                                    continue
                                item += "-consistent-ocr-scale-cure"
                                if f"claim-{item}.json" in known:
                                    if (f"result-{item}.json" not in known or not cure_eligible(
                                            state_dir / item, ("Jev target confidence was 0.85",),
                                            ("observation-foreground", "navigate-to-bystander",
                                             "census-foreground", "scroll-project-sidebar-0",
                                             "scroll-project-sidebar-1", "visual-census-select-2-0"))):
                                        continue
                                    item = f"restore-{dispatch_id}-{thread}-ocr2-verified-prefix-cure"
                                    if f"claim-{item}.json" in known:
                                        if (f"result-{item}.json" not in known or not cure_eligible(
                                                state_dir / item, ("Jev target confidence was 0.86",),
                                                ("observation-foreground", "navigate-to-bystander",
                                                 "census-foreground", "scroll-project-sidebar-0",
                                                 "scroll-project-sidebar-1"))):
                                            continue
                                        item = f"restore-{dispatch_id}-{thread}-exact-short-prefix-long-cure"
                                        if f"claim-{item}.json" in known:
                                            if (f"result-{item}.json" not in known or not cure_eligible(
                                                    state_dir / item, ("census yielded 0 verified matches across 0 rows",),
                                                    ("observation-foreground", "navigate-to-bystander",
                                                     "census-foreground", "scroll-project-sidebar-0"))):
                                                continue
                                            item = f"restore-{dispatch_id}-{thread}-sticky-footer-cure"
                                            if f"claim-{item}.json" in known:
                                                if (f"result-{item}.json" not in known or not cure_eligible(
                                                        state_dir / item, ("compositor geometry changed after capture",),
                                                        ("observation-foreground", "navigate-to-bystander",
                                                         "census-foreground"))):
                                                    continue
                                                item = f"restore-{dispatch_id}-{thread}-settled-geometry-cure"
                                                if f"claim-{item}.json" in known:
                                                    if (f"result-{item}.json" not in known or not cure_eligible(
                                                            state_dir / item, ("no verified overlapping chat row",),
                                                            ("observation-foreground", "navigate-to-bystander",
                                                             "census-foreground", "scroll-project-sidebar-0",
                                                             "scroll-project-sidebar-1", "scroll-project-sidebar-2",
                                                             "visual-census-select-2-0", "visual-census-select-2-1",
                                                             "expand-scm-project-3", "expand-scm-project-4",
                                                             "expand-scm-project-5"))):
                                                        continue
                                                    item = f"restore-{dispatch_id}-{thread}-visible-project-anchor-cure"
                                                    if f"claim-{item}.json" in known:
                                                        if (f"result-{item}.json" not in known or not cure_eligible(
                                                                state_dir / item,
                                                                ("fresh census row no longer matches the roster",),
                                                                ("observation-foreground", "navigate-to-bystander",
                                                                 "scroll-project-sidebar-0", "scroll-project-sidebar-1",
                                                                 "visual-census-select-2-0"))):
                                                            continue
                                                        item = f"restore-{dispatch_id}-{thread}-reacquire-row-cure"
                                                        if f"claim-{item}.json" in known:
                                                            if (f"result-{item}.json" not in known or not cure_eligible(
                                                                    state_dir / item,
                                                                    ("compositor geometry changed after capture",),
                                                                    ("observation-foreground", "navigate-to-bystander",
                                                                     "census-foreground"))):
                                                                continue
                                                            item = f"restore-{dispatch_id}-{thread}-scroll-recapture-cure"
                                                            if f"claim-{item}.json" in known:
                                                                if (f"result-{item}.json" not in known or not cure_eligible(
                                                                        state_dir / item, ("roster reordered",),
                                                                        ("observation-foreground", "navigate-to-bystander",
                                                                         "scroll-project-sidebar-0", "scroll-project-sidebar-1",
                                                                         "expand-scm-project-2", "visual-census-select-3-0",
                                                                         "visual-census-select-3-1", "scroll-project-sidebar-3"))):
                                                                    continue
                                                                item = f"restore-{dispatch_id}-{thread}-inventory-first-cure"
                                                                if f"claim-{item}.json" in known:
                                                                    continue
            elif dispatch_id == LANE_RESTART and f"result-{item}.json" in known:
                output = state_dir / item
                runner = output / "runner.jsonl"
                trace = output / "send" / "driver.jsonl"
                if (runner.is_file() and trace.is_file() and AuditLog(runner).verify().ok
                        and AuditLog(trace).verify().ok):
                    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
                    attempts = [row for row in events if row.get("step_id") == "send-once"]
                    if (len(attempts) == 1 and not attempts[0].get("ok")
                            and "the active FreeBuff document did not expose the exact pinned thread"
                            in attempts[0].get("detail", "")):
                        item += "-lane1-selected-row-cure"
                        if f"claim-{item}.json" not in known:
                            pass
                        else:
                            continue
                    else:
                        continue
                else:
                    continue
            elif dispatch_id == STANDUP and f"result-{item}.json" in known and cure_eligible(
                state_dir / item, ("search: driver tree termination unverified",),
                ("observation-foreground", "navigate-to-bystander", "scroll-project-sidebar",
                 "scroll-sidebar-top", "search-foreground", "close-old-search",
                 "sidebar-top-scroll-1", "sidebar-top-scroll-2", "sidebar-top-scroll-3",
                 "sidebar-top-scroll-4", "sidebar-top-scroll-5", "session-list-pick-1",
                 "prefix-scroll-1"),
            ):
                item += "-verified-process-stop-cure"
                if f"claim-{item}.json" in known:
                    previous = state_dir / item
                    runner = previous / "runner.jsonl"
                    traces = list(previous.glob("**/driver.jsonl"))
                    if (not runner.is_file() or not AuditLog(runner).verify().ok or not traces
                            or any(not AuditLog(trace).verify().ok for trace in traces)):
                        continue
                    rows = [json.loads(line) for trace in traces
                            for line in trace.read_text(encoding="utf-8").splitlines()]
                    if any(row["kind"] == "action" and (
                        row.get("action") not in {"click_freebuff", "scroll_freebuff", "focus_freebuff"}
                        or "composer" in row.get("consent", {}).get("params", {}).get("control", "").casefold()
                    ) for row in rows):
                        continue
                    results = [json.loads(line) for line in runner.read_text(encoding="utf-8").splitlines()]
                    if not any(row.get("step_id") == "result" and "published driver changed" in row.get("state", "")
                               for row in results):
                        continue
                    item = f"restore-{dispatch_id}-{thread}-published-identity-cure"
                    if f"claim-{item}.json" in known:
                        previous = state_dir / item
                        runner = previous / "runner.jsonl"
                        traces = list(previous.glob("**/driver.jsonl"))
                        if (not runner.is_file() or not AuditLog(runner).verify().ok or not traces
                                or any(not AuditLog(trace).verify().ok for trace in traces)):
                            continue
                        rows = [json.loads(line) for trace in traces
                                for line in trace.read_text(encoding="utf-8").splitlines()]
                        if any(row["kind"] == "action" and (
                            row.get("action") not in {"click_freebuff", "scroll_freebuff", "focus_freebuff"}
                            or "composer" in row.get("consent", {}).get("params", {}).get("control", "").casefold()
                        ) for row in rows):
                            continue
                        results = [json.loads(line) for line in runner.read_text(encoding="utf-8").splitlines()]
                        if not any(row.get("step_id") == "result" and
                                   "search: driver tree terminated after deadline" in row.get("state", "")
                                   for row in results):
                            continue
                        item = f"restore-{dispatch_id}-{thread}-targeted-vision-row-cure"
                        if f"claim-{item}.json" in known:
                            if (f"result-{item}.json" not in known or not cure_eligible(
                                    state_dir / item,
                                    ("the active FreeBuff document did not expose the exact pinned thread",),
                                    ("observation-foreground", "navigate-to-bystander", "vision-seat-open",
                                     "vision-seat-scroll-1", "vision-seat-scroll-2", "vision-seat-scroll-3",
                                     "vision-seat-scroll-4", "vision-seat-scroll-5", "vision-seat-scroll-6",
                                     "close-search-dialog"))):
                                continue
                            item = f"restore-{dispatch_id}-{thread}-last-work-identity-cure"
                            if f"claim-{item}.json" in known:
                                if (f"result-{item}.json" not in known or not cure_eligible(
                                        state_dir / item, ("vision-seat row was not visibly selected",),
                                        ("observation-foreground", "navigate-to-bystander", "vision-seat-open",
                                         "vision-seat-scroll-1", "vision-seat-scroll-2", "vision-seat-scroll-3",
                                         "vision-seat-scroll-4", "vision-seat-scroll-5", "vision-seat-scroll-6",
                                         "close-search-dialog"))):
                                    continue
                                item = f"restore-{dispatch_id}-{thread}-ocr-glyph-prefix-cure"
                                if f"claim-{item}.json" in known:
                                    if (f"result-{item}.json" not in known or not cure_eligible(
                                            state_dir / item, ("vision-seat selected view did not expose",),
                                            ("observation-foreground", "navigate-to-bystander", "vision-seat-open",
                                             "vision-seat-scroll-1", "vision-seat-scroll-2", "vision-seat-scroll-3",
                                             "vision-seat-scroll-4", "vision-seat-scroll-5", "vision-seat-scroll-6",
                                             "close-search-dialog"))):
                                        continue
                                    item = f"restore-{dispatch_id}-{thread}-vision-transcript-crop-cure"
                                    if f"claim-{item}.json" in known:
                                        if (f"result-{item}.json" not in known or not cure_eligible(
                                                state_dir / item, ("vision-seat selected view did not expose",),
                                                ("observation-foreground", "navigate-to-bystander", "vision-seat-open",
                                                 "vision-seat-scroll-1", "vision-seat-scroll-2",
                                                 "vision-seat-scroll-3", "vision-seat-scroll-4",
                                                 "vision-seat-scroll-5", "vision-seat-scroll-6",
                                                 "close-search-dialog"))):
                                            continue
                                        item = f"restore-{dispatch_id}-{thread}-mission-draft-identity-cure"
                                        if f"claim-{item}.json" in known:
                                            continue
            else:
                continue
        guard_approval()
        require_driver_runtime()
        if not desktop_idle():
            heartbeat(known, "waiting for owner desktop idle before restoration")
            return True
        digest = hashlib.sha256(receipts[dispatch_id]["body"].encode()).hexdigest()
        checkpoint(f"claim-{item}.json", {"dispatch": dispatch_id, "thread": thread, "sha256": digest})
        output = state_dir / item
        try:
            output.mkdir(parents=True)
            mission = {"thread": thread, "dispatch": dispatch_id, "standing": True}
            mission["phase_timeout"] = 240
            if item.endswith(("-last-work-identity-cure", "-ocr-glyph-prefix-cure",
                              "-vision-transcript-crop-cure", "-mission-draft-identity-cure")):
                mission["phases"] = ("search", "vision-resume")
            if item.endswith("-start-staged-mission"):
                mission["phases"] = ("vision-start-staged",)
                mission["skip_t5"] = True
            if item.endswith("-start-focus-cure"):
                mission["phases"] = ("vision-start-focus-cure",)
                mission["skip_t5"] = True
            if item.endswith(("-project-roster-cure", "-project-roster-cure-scroll-registration-cure",
                              "-scroll-registration-cure-fresh-row-ocr-cure",
                              "-fresh-row-ocr-cure-fresh-label-cure",
                              "-fresh-label-cure-consistent-ocr-scale-cure", "-ocr2-verified-prefix-cure",
                              "-exact-short-prefix-long-cure", "-sticky-footer-cure",
                              "-settled-geometry-cure", "-visible-project-anchor-cure", "-reacquire-row-cure",
                              "-scroll-recapture-cure", "-inventory-first-cure")):
                mission["phases"] = ("project-census",)
                mission["phase_timeout"] = 1500 if item.endswith("-inventory-first-cure") else 600
            state = "parked" if execute(output, item, mission, digest, (),) else "verified running"
        except UncertainDriverExit as error:
            checkpoint(f"interlock-{item}.json", {"dispatch": dispatch_id, "thread": thread, "state": str(error)})
            issue_comment(f"Vision watch desktop interlock #{dispatch_id} / `{thread}`. {error}")
            state = "parked with desktop interlock"
        except (OSError, RuntimeError) as error:
            state = "parked after claim"
            issue_comment(f"Vision watch #{dispatch_id} / `{thread}` {state}. {error}")
        checkpoint(f"result-{item}.json", {"dispatch": dispatch_id, "thread": thread, "state": state})
        return True
    return False


def main():
    control = local_control_state()
    if not control["enabled"] or control["paused"]:
        return
    head = worktree_head()
    if head is None:
        return
    known = checkpoints()
    if "owner-paused.json" in known:
        return
    if any(name.startswith("interlock-") and not name.startswith("interlock-released-")
           and f"interlock-released-{name[len('interlock-'):]}" not in known for name in known):
        return
    if "desktop-interlock.json" in known:
        if "interlock-released-7111294374.json" not in known:
            return
    if "paused.json" in known and read_checkpoint("paused.json")["state"] == "owner-paused":
        return
    pause = pause_requested()
    if pause:
        checkpoint("owner-paused.json", {"dispatch": pause, "state": "owner-paused"})
        issue_comment(f"Vision watch ack {pause}. Paused before desktop input.")
        return
    receipts = validate_receipts()
    if "armed.json" not in known:
        checkpoint("armed.json", {"dispatch": CUTOVER, "state": "staged", "next": CENSUS})
        issue_comment(f"Vision watch ack {CUTOVER}. Scheduled runner staged itself and checkpointed its state. "
                      f"Next admission is {CENSUS}.")
        return
    parked = f"parked-{CENSUS}.json"
    if parked not in known:
        checkpoint(parked, {"dispatch": CENSUS, "state": "parked", "prior": 7093959152, "ruling": UNBLOCK})
        issue_comment(f"Vision watch ack {UNBLOCK} and {TRANSITION}. Item {CENSUS} stays parked alone. "
                      f"Burn queue {BURN_QUEUE} is eligible under its own gates.")
    os.environ["HARNESS_VISION_HEAD"] = head
    if run_restoration(receipts, known):
        return
    run_burn(receipts, known)


if __name__ == "__main__":
    main()
