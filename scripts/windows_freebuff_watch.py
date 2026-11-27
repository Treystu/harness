"""One scheduled checkpoint for the staged oversight cutover."""

import base64
import ctypes
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path

from driver_core.audit import AuditLog

from .windows_freebuff_dispatch import (
    BURN_SESSIONS, CONTINUATION, DISK_THREAD, SCM_THREAD, SESSIONS, THREAD, VISION_THREAD,
)
from .windows_freebuff_runner import (
    BRANCH, ISSUE, LEDGER, OWNER_ID, UncertainDriverExit,
    _hidden_subprocess_kwargs as _runner_hidden_kwargs,
    api as _DEFAULT_RUNNER_API,
    approved, execute,
)
api = _DEFAULT_RUNNER_API

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
_NOT_MODIFIED = object()
_POLL_STATS = {"requests": 0, "conditional_304s": 0}
_GH_TOKEN_CACHE = {"token": None}
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


def monitor_state_path():
    raw = os.environ.get("HARNESS_DRIVER_MONITOR_STATE", "").strip()
    if raw:
        return Path(raw)
    wdir = os.environ.get("HARNESS_DRIVER_WATCH_DIR", "").strip()
    if wdir:
        return Path(wdir) / "dispatch-monitor-state.json"
    return DEFAULT_CONTROL_PATH.parent / "dispatch-monitor-state.json"


def _monitor_enabled():
    if os.environ.get("HARNESS_DRIVER_MONITOR_STATE", "").strip():
        return True
    if os.environ.get("HARNESS_DRIVER_WATCH_DIR", "").strip():
        return True
    return api is _DEFAULT_RUNNER_API


def _load_monitor_state():
    path = monitor_state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_monitor_state(state):
    path = monitor_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _gh_auth_token():
    if _GH_TOKEN_CACHE["token"]:
        return _GH_TOKEN_CACHE["token"]
    try:
        res = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=10, check=False,
            **_runner_hidden_kwargs(),
        )
        tok = (res.stdout or "").strip() if res.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        tok = ""
    if tok:
        _GH_TOKEN_CACHE["token"] = tok
    return tok


def _http_get_conditional(endpoint, etag=None, attempts=3):
    token = _gh_auth_token()
    if not token:
        return api(endpoint), None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "harness-driver-watch",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }
    if etag:
        headers["If-None-Match"] = etag
    url = f"https://api.github.com/{endpoint}"
    delays = (1.5, 3.0)
    transient_codes = {429, 500, 502, 503, 504}
    for attempt in range(max(1, attempts)):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw), resp.headers.get("ETag")
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return _NOT_MODIFIED, etag
            body = exc.read().decode("utf-8", errors="replace")[:220]
            err = RuntimeError(f"GitHub GET HTTP {exc.code} for {endpoint}: {body}")
            if attempt + 1 < attempts and exc.code in transient_codes:
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            raise err from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            err = RuntimeError(f"GitHub GET failed for {endpoint}: {exc}")
            if attempt + 1 < attempts:
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            raise err from exc
    raise RuntimeError(f"GitHub GET failed for {endpoint}")


def _default_http_get_conditional_ref():
    return _http_get_conditional


def api_conditional(endpoint, *, etag=None):
    _POLL_STATS["requests"] += 1
    if api is not _DEFAULT_RUNNER_API and _http_get_conditional is _ORIG_HTTP_CONDITIONAL:
        return api(endpoint), None
    data, new_etag = _http_get_conditional(endpoint, etag=etag)
    if data is _NOT_MODIFIED:
        _POLL_STATS["conditional_304s"] += 1
    return data, new_etag


_ORIG_HTTP_CONDITIONAL = _http_get_conditional


def issue_comment(message):
    response = api(ISSUE, method="POST", body={"body": message})
    _clear_comments_etag()
    return response


def owner(comment):
    return comment.get("user", {}).get("id") == OWNER_ID


def validate_receipts():
    if _monitor_enabled():
        state = _load_monitor_state()
        cached = state.get("validated_receipts")
        if isinstance(cached, dict) and all(str(num) in cached for num in RECEIPTS):
            return {int(k): v for k, v in cached.items()}
    receipts = {}
    for number, heading in RECEIPTS.items():
        _POLL_STATS["requests"] += 1
        receipt = api(f"repos/Treystu/harness/issues/comments/{number}")
        if (not owner(receipt) or not receipt["body"].startswith(heading)
                or not receipt["issue_url"].casefold().endswith("/treystu/harness/issues/684")):
            raise RuntimeError(f"oversight receipt {number} did not match")
        receipts[number] = receipt
    if _monitor_enabled():
        state = _load_monitor_state()
        state["validated_receipts"] = {
            str(k): {"id": v.get("id"), "created_at": v.get("created_at"), "body": v.get("body", "")}
            for k, v in receipts.items()
        }
        _save_monitor_state(state)
    return receipts


def _comment_body(comment):
    return (comment.get("body") or "").lstrip("\ufeff")


def _parse_iso(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _compact_comment(comment):
    user = comment.get("user") or {}
    return {
        "id": comment.get("id"),
        "user": {"id": user.get("id")},
        "created_at": comment.get("created_at"),
        "updated_at": comment.get("updated_at") or comment.get("created_at"),
        "body": comment.get("body") or "",
    }


def _sync_issue_comments(since_floor=DYNAMIC_SINCE):
    """Fetch #684 comments incrementally with ?since=<watermark> + ETag 304 caching."""
    if not _monitor_enabled():
        comments = []
        page = 1
        while True:
            _POLL_STATS["requests"] += 1
            batch = api(f"{ISSUE}?since={since_floor}&per_page=100&page={page}")
            comments.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return comments

    state = _load_monitor_state()
    cache = state.get("comments_by_id") if isinstance(state.get("comments_by_id"), dict) else {}
    watermark = state.get("comments_watermark") or min(SINCE, DYNAMIC_SINCE)
    etag = state.get("comments_etag") if cache else None

    first, first_etag = api_conditional(f"{ISSUE}?since={watermark}&per_page=100&page=1", etag=etag)
    if first is _NOT_MODIFIED:
        floor_dt = _parse_iso(since_floor)
        return [
            item for item in cache.values()
            if not item.get("created_at") or _parse_iso(item["created_at"]) >= floor_dt
        ]

    batches = [first]
    page = 1
    while len(batches[-1]) >= 100:
        page += 1
        more, _ = api_conditional(f"{ISSUE}?since={watermark}&per_page=100&page={page}")
        batches.append(more)

    new_watermark = watermark
    changed_watermark = False
    for batch in batches:
        for item in batch:
            cid = item.get("id")
            if cid is None:
                continue
            compact = _compact_comment(item)
            cache[str(cid)] = compact
            ts = compact.get("updated_at") or compact.get("created_at") or ""
            if ts and ts > new_watermark:
                new_watermark = ts
                changed_watermark = True

    state["comments_by_id"] = cache
    state["comments_watermark"] = new_watermark
    state["comments_etag"] = None if (changed_watermark or len(batches) > 1) else first_etag
    _save_monitor_state(state)
    floor_dt = _parse_iso(since_floor)
    return [
        item for item in cache.values()
        if not item.get("created_at") or _parse_iso(item["created_at"]) >= floor_dt
    ]


def pause_requested():
    for comment in sorted(_sync_issue_comments(since_floor=SINCE), key=lambda item: item.get("id", 0)):
        lines = _comment_body(comment).strip().splitlines()
        if owner(comment) and lines and lines[0].strip() in {"PAUSE", "VISION-DISPATCH PAUSE"}:
            return comment["id"]
    return None


def checkpoints():
    if not _monitor_enabled():
        _POLL_STATS["requests"] += 1
        return {entry["name"] for entry in api(f"{ROOT}?ref={BRANCH}")}
    state = _load_monitor_state()
    etag = state.get("checkpoints_etag")
    cached = state.get("known_checkpoints")
    data, new_etag = api_conditional(f"{ROOT}?ref={BRANCH}", etag=etag)
    if data is _NOT_MODIFIED and isinstance(cached, list):
        return set(cached)
    names = [entry["name"] for entry in data]
    state["known_checkpoints"] = names
    state["checkpoints_etag"] = new_etag
    _save_monitor_state(state)
    return set(names)


def checkpoint(name, event):
    event["at"] = datetime.now(timezone.utc).isoformat()
    content = base64.b64encode((json.dumps(event) + "\n").encode()).decode()
    body = {"branch": BRANCH, "message": f"Checkpoint vision watch {name}", "content": content}
    try:
        api(f"{ROOT}/{name}", method="PUT", body=body)
    except RuntimeError as error:
        # A checkpoint path that already exists answers 422 "'sha' wasn't
        # supplied" (measured 2026-11-27: skip-dyn-7226574169-9ecc3453.json was
        # written once, the checkpoint list never learned the name, and every
        # tick after that failed - a canary fault that stopped the claim scan and
        # left a filed dispatch unclaimed). The record is the same record, so
        # update it with its own sha instead of failing the tick.
        if "sha" not in str(error).casefold() or "422" not in str(error):
            raise
        existing = api(f"{ROOT}/{name}?ref={BRANCH}")
        if not isinstance(existing, dict) or not existing.get("sha"):
            raise
        body["sha"] = existing["sha"]
        api(f"{ROOT}/{name}", method="PUT", body=body)
    if _monitor_enabled():
        state = _load_monitor_state()
        known_list = list(state.get("known_checkpoints") or [])
        if name not in known_list:
            known_list.append(name)
            state["known_checkpoints"] = known_list
            state["checkpoints_etag"] = None
            _save_monitor_state(state)


def read_checkpoint(name):
    response = api(f"{ROOT}/{name}?ref={BRANCH}")
    # A missing checkpoint comes back as a dict carrying "message", and an
    # unexpected body is not a checkpoint either: name it instead of failing on
    # a KeyError that reads like a code defect rather than an absent file.
    if not isinstance(response, dict) or "content" not in response:
        raise RuntimeError(f"checkpoint {name} is not readable")
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
        return {
            "enabled": True,
            "paused": False,
            "cancelled_lanes": (),
            "continuous_burndown": False,
            "watched_lanes": (THREAD,),
            "antigravity_calibrated": False,
            "from_file": False,
            "path": str(path),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {
            "enabled": False,
            "paused": True,
            "cancelled_lanes": (),
            "continuous_burndown": False,
            "watched_lanes": (THREAD,),
            "antigravity_calibrated": False,
            "from_file": True,
            "path": str(path),
            "reason": "unreadable-control-file",
        }
    lanes = data.get("cancelled_lanes") or ()
    if not isinstance(lanes, (list, tuple)):
        lanes = ()
    watched = data.get("watched_lanes") or (THREAD,)
    if not isinstance(watched, (list, tuple)):
        watched = (THREAD,)
    return {
        "enabled": bool(data.get("enabled", True)),
        "paused": bool(data.get("paused", False)),
        "cancelled_lanes": tuple(str(lane) for lane in lanes),
        "continuous_burndown": bool(data.get("continuous_burndown", True)),
        "watched_lanes": tuple(str(lane) for lane in watched),
        "antigravity_calibrated": bool(data.get("antigravity_calibrated", False)),
        "from_file": True,
        "path": str(path),
    }


def _head_pair():
    """``(status, head, upstream)`` for the worktree, read without touching the network."""
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "scripts"],
                      cwd=WORKTREE, timeout=5, check=False, **_hidden_subprocess_kwargs()).returncode:
        return "dirty-scripts", "", ""
    result = subprocess.run(["git", "rev-parse", "HEAD", "@{upstream}"], cwd=WORKTREE,
                            capture_output=True, text=True, timeout=5, check=False,
                            **_hidden_subprocess_kwargs())
    heads = result.stdout.splitlines()
    if result.returncode != 0 or len(heads) != 2:
        return "unreadable-upstream", "", ""
    return "ok", heads[0], heads[1]


def refresh_upstream():
    """Fetch the configured upstream branch so a stale remote-tracking ref cannot refuse a tick.

    Measured 2026-11-25: ``7a7d7ca1`` was pushed, but the local
    ``treystu/laptop-vision-20261122`` ref still named ``798148ce``. Every
    scheduled tick therefore read HEAD != upstream and returned before its first
    checkpoint - 13:11Z to 15:06Z, ~55 silent ticks that each looked like a
    healthy run in ``driver-watch.log``.
    """
    result = subprocess.run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
                            cwd=WORKTREE, capture_output=True, text=True, timeout=5, check=False,
                            **_hidden_subprocess_kwargs())
    ref = result.stdout.strip()
    if result.returncode != 0 or "/" not in ref:
        return False
    remote, branch = ref.split("/", 1)
    fetched = subprocess.run(["git", "fetch", "--quiet", "--no-tags", remote, branch],
                             cwd=WORKTREE, capture_output=True, text=True, timeout=60, check=False,
                             **_hidden_subprocess_kwargs())
    return fetched.returncode == 0


def worktree_head(*, refresh=False):
    status, head, upstream = _head_pair()
    if status == "ok" and head == upstream:
        return head
    if refresh and refresh_upstream():
        status, head, upstream = _head_pair()
        if status == "ok" and head == upstream:
            return head
    return None


def head_refusal_detail():
    """Name why the worktree gate refused, so the filing is actionable."""
    status, head, upstream = _head_pair()
    if status == "dirty-scripts":
        return "uncommitted changes under scripts/ in the driver worktree"
    if status == "unreadable-upstream":
        return "the driver worktree has no readable upstream branch"
    return f"HEAD {head[:8]} is not published at upstream {upstream[:8]}"


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


def foreground_blocker():
    """Return (hwnd, pid, title) when a non-FreeBuff window holds foreground and blocks focus.

    Mode (d) cure: returning before writing claim-dyn-...json keeps one-shot
    claims unspent during an external foreground lock (e.g. Windows Security).
    """
    if os.name != "nt":
        return None
    from driver_core import osal
    from .windows_freebuff_capture import FreeBuffWindow
    from .windows_focus import activate_exact

    pids = FreeBuffWindow.processes()
    api_win = osal._WindowsWindowApi()
    hwnd = int(api_win.foreground() or 0)
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.GetWindowThreadProcessId.restype = wintypes.DWORD

    def _pid_of(handle):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(wintypes.HWND(handle), ctypes.byref(pid))
        return int(pid.value)

    if hwnd and _pid_of(hwnd) in pids:
        return None
    if not pids:
        title = api_win.title_of(hwnd) or "" if hwnd else "no FreeBuff process"
        return (hwnd, _pid_of(hwnd) if hwnd else 0, title or "no FreeBuff window")
    win = object.__new__(FreeBuffWindow)
    win.api = api_win
    win.user = user
    candidates = win.candidates(pids=pids)
    if not candidates:
        title = api_win.title_of(hwnd) or "" if hwnd else "no visible FreeBuff window"
        return (hwnd, _pid_of(hwnd) if hwnd else 0, title or "no visible FreeBuff window")
    target_hwnd, _ = candidates[0]
    if activate_exact(target_hwnd, api_win.foreground):
        return None
    holder = int(api_win.foreground() or 0)
    holder_pid = _pid_of(holder) if holder else 0
    holder_title = api_win.title_of(holder) or "" if holder else "unknown foreground window"
    return (holder, holder_pid, holder_title)


LAST_SCAN = {}


def current_evidence():
    return dict(LAST_SCAN) or None


def describe_scan(evidence):
    """Render the scan's own counts.

    ``heartbeat`` used to take a literal string, so a tick that had scanned
    nothing and a tick that had scanned everything said the same words - the
    2026-11-24 blindness ran ~8 h behind heartbeats that read "no unclaimed
    dispatches". Every number here is measured by ``scan_dispatch_comments`` in
    the same tick that posts it.
    """
    if not evidence:
        return ""
    text = (f"scan saw {evidence.get('owner', 0)} owner comment(s) through "
            f"#{evidence.get('scanned_through', 0)}; "
            f"{evidence.get('dispatches', 0)} dispatch-shaped and parseable; "
            f"{evidence.get('claimable', 0)} claimable")
    unparsed = evidence.get("unparsed") or ()
    if isinstance(unparsed, dict):
        text += "; not claimable: " + ", ".join(
            f"#{cid} ({reason})" for cid, reason in sorted(unparsed.items()))
    elif unparsed:
        text += "; not claimable: " + ", ".join(f"#{cid}" for cid in sorted(unparsed))
    if "polls" in evidence:
        text += f"; polls={evidence.get('polls', 0)} (304={evidence.get('conditional_304s', 0)})"
    return text


def heartbeat(known, state, evidence=None):
    now = datetime.now(timezone.utc)
    bucket = now.strftime("%Y%m%d-%H") + f"-{now.minute // 15}"
    name = f"heartbeat-{bucket}.json"
    if name not in known:
        checkpoint(name, {"state": state, "evidence": evidence or {}})
        detail = describe_scan(evidence)
        message = f"Vision watch {CUTOVER} heartbeat. {state}."
        if detail:
            message += f" {detail}."
        issue_comment(message)


def canary(evidence):
    """Prove this tick could see, and name it when it could not.

    The expected cure shape for the blindness class: a tick that read an empty
    or unadvanced page must fail loudly instead of reporting a quiet success.
    """
    problems = []
    if not evidence.get("owner"):
        problems.append("the scan returned no owner comments at all")
    if not evidence.get("scanned_through"):
        problems.append("the scan advanced no cursor")
    return problems


def report_claim_fault(known, error):
    """Alert #684 once per hour per distinct claim-loop failure signature (Mode (c)/R20)."""
    now = datetime.now(timezone.utc)
    detail = f"{type(error).__name__}: {error}"
    digest = hashlib.sha256(detail.encode("utf-8")).hexdigest()[:8]
    name = "canary-fault-" + now.strftime("%Y%m%d-%H") + f"-{digest}.json"
    if name in known:
        return False
    if isinstance(known, set):
        known.add(name)
    try:
        checkpoint(name, {"state": "claim-loop-fault", "error": detail})
    except (RuntimeError, OSError):
        if isinstance(known, set):
            known.discard(name)
        return False
    try:
        issue_comment(f"Vision watch {CUTOVER} canary FAILED: claim-loop fault ({detail}).")
    except (RuntimeError, OSError):
        return False
    return True


def report_foreground_blocked(known, cid, thread, blocker):
    """Alert #684 once per hour per blocked dispatch/holder while keeping claim unspent."""
    hwnd, pid, title = blocker
    now = datetime.now(timezone.utc)
    sig = f"{cid}:{pid}:{title}"
    digest = hashlib.sha256(sig.encode("utf-8")).hexdigest()[:8]
    name = "foreground-blocked-" + now.strftime("%Y%m%d-%H") + f"-{digest}.json"
    if name in known:
        return False
    known.add(name)
    checkpoint(name, {
        "dispatch": cid, "thread": thread, "state": "foreground-blocked",
        "hwnd": hwnd, "pid": pid, "title": title,
    })
    issue_comment(
        f"Vision watch {CUTOVER} foreground BLOCKED before claim on #{cid} / `{thread}`: "
        f"hwnd {hwnd} pid {pid} title {title!r}; claim kept unspent for retry."
    )
    return True


def report_stale_pickup(known, cid, thread, age_seconds, reason):
    """Alert #684 at most once per 15m bucket when an unclaimed dispatch exceeds 300s."""
    now = datetime.now(timezone.utc)
    bucket = now.strftime("%Y%m%d-%H") + f"-{now.minute // 15}"
    digest = hashlib.sha256(f"{cid}:{reason}".encode("utf-8")).hexdigest()[:8]
    name = f"stale-pickup-{bucket}-{digest}.json"
    if name in known:
        return False
    if isinstance(known, set):
        known.add(name)
    checkpoint(name, {
        "dispatch": cid, "thread": thread, "state": "stale-pickup",
        "age_seconds": round(age_seconds, 1), "reason": reason,
    })
    issue_comment(
        f"Vision watch {CUTOVER} pickup SLA ALERT on #{cid} / `{thread}`: "
        f"unclaimed after {int(age_seconds)}s (>300s) while {reason}."
    )
    return True


CURSOR = re.compile(r"^cursor-(\d+)\.json$")


def advance_cursor(evidence, known=()):
    """Hold the scan's position durably, without a write on every tick.

    ``?since=DYNAMIC_SINCE`` is a constant, so every tick re-reads the same two
    days and a 403 part-way through a page leaves no record of how far the last
    complete scan actually reached. The watermark records that position and only
    writes when it moves.

    It is ``cursor-<id>.json``, not ``cursor.json``: the ledger is create-only
    by design (that is what makes a claim at-most-once), and a rewrite of an
    existing path is refused with HTTP 422 "sha wasn't supplied" - measured on
    the first live paused tick at 2026-11-25T04:27Z.
    """
    position = evidence.get("scanned_through") or 0
    if not position:
        return evidence
    reached = [int(match.group(1)) for name in known if (match := CURSOR.match(name))]
    highest = max(reached, default=0)
    evidence["cursor_advanced"] = position > highest
    if position > highest:
        checkpoint(f"cursor-{position}.json", {
            "scanned_through": position,
            "comments": evidence.get("scanned", 0),
            "at": datetime.now(timezone.utc).isoformat(),
        })
    return evidence


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


def dynamic_phase_timeout(item):
    """Per-phase bound for one claimed dynamic dispatch.

    Measured 2026-11-24: CivicScope (dispatch 7127711668) reached page 11 of the
    expanded session walk and was parked at the old 240 s bound while still
    censusing, so the bound - not the lane - ended the run. Expanding every
    collapsed section makes the walk deeper by design (that is the cure for the
    Kalshi and Harness Audit refusals), so the bound has to cover the deeper list
    the app actually renders. The walk still stops at its own end test; this only
    stops the clock from cutting a real census short.
    """
    return 480 if item else 240


LANE_ALIASES = (
    ("scmessenger audit", "0319b9f6"),
    ("scmessenger", SCM_THREAD),
    ("lane 1", THREAD),
    ("lane 2", "9ecc3453"),
    ("disk audit", DISK_THREAD),
    ("vision driver standup", VISION_THREAD),
    ("bigenergyco", "0d7e2f37"),
    ("harness audit", "918dad1a"),
    ("kalshi", "7d4a9b14"),
    ("civicscope", "46472fcc"),
    ("agensi", "26646448"),
)


_STOP_EPISODE_LANE = (
    (re.compile(r"\bL1-STOP-\d+\b", re.I), THREAD),
    (re.compile(r"\bSCM-STOP-\d+\b", re.I), SCM_THREAD),
)
_OPENING_STOPPED = re.compile(
    r"^\s*(?:[\ufeff#>*\-\s]+|\*{2})*([^\n:]+?)\s+is\s+(?:PRESUMED\s+)?STOPPED\b",
    re.I | re.M,
)


def _lane_thread_from_dispatch(body):
    """Which lane is this dispatch addressed to?

    Forms in the oversight's own history: a thread id anywhere in the body,
    a ``Lane:`` line, the lane/episode named in the banner (7145072019,
    7146588401, 7176494509 ``RESTART DISPATCH - episode L1-STOP-1112``), or an
    explicit opening subject declaration (``Lane 1 is PRESUMED STOPPED``).

    Arbitrary body prose is still not read: a lane mentioned in discussion prose
    cannot redirect a dispatch.
    """
    thread_pattern = re.compile(r"\b(" + "|".join(re.escape(tid) for tid in SESSIONS) + r")\b")
    match = thread_pattern.search(body)
    if match:
        return match.group(1)
    lane_line = re.search("^" + _MD_PREFIX + r"Lane\*{0,2}:\s*(.+)$", body, re.I | re.M)
    non_empty = [re.sub(r"^[\ufeff#>*\-\s]+|\*{2}", "", ln).strip()
                 for ln in body.splitlines() if ln.strip()]
    if lane_line:
        text = lane_line.group(1).casefold()
    else:
        banner = non_empty[0] if non_empty else ""
        text = banner.casefold()
        for pat, tid in _STOP_EPISODE_LANE:
            if pat.search(banner):
                return tid
    for alias, tid in LANE_ALIASES:
        if alias in text:
            return tid
    if not lane_line and non_empty:
        head_block = "\n".join(non_empty[:3])
        if stopped := _OPENING_STOPPED.search(head_block):
            subj = stopped.group(1).casefold()
            for alias, tid in LANE_ALIASES:
                if alias in subj:
                    return tid
    return None


_MD_PREFIX = r"\ufeff?(?:[ \t]+|[#*>-]+[ \t]+)*\*{0,2}"
# Measured 2026-11-25T04:30Z: dispatch 7151203687 (Lane 1, L1-STOP-1035) writes
# its instruction as "Runner: in-place restart only - exactly \"continue in
# full\"", which none of the Action forms matched, so the dispatch that the
# oversight filed to bring this lane back was unreadable by the watch that was
# supposed to execute it. Also tolerate Markdown bold/heading prefixes (7154645137).
# Measured 2026-11-25T21:02Z: dispatch 7174526907 writes its instruction as
# "Requested runner action: in-place restart only - exactly \"continue in
# full\"". The qualifier in front of "Action" made a live restart unreadable, so
# the two-word lead-in is declared rather than special-cased.
RUNNER_ACTION = re.compile(
    "^" + _MD_PREFIX
    + r"(?:(?:Requested\s+)?(?:Runner\s+)?Action"
    + r"(?:\s+(?:for\s+the\s+runner(?:\s+alone)?|requested))?"
    + r"|Requested\s+runner\s+action|Runner)\*{0,2}\s*[:(]",
    re.I | re.M)
# A STEER hands the runner text to deliver rather than a bounded restart; it is
# never claimed, but 7149636711 carried the owner's whole sequencing order and
# must be named rather than dropped into an empty queue.
STEER_TEXT = re.compile("^" + _MD_PREFIX + r"Text\s+for\s+the\s+runner\b", re.I | re.M)
CANCELLATION = re.compile("^" + _MD_PREFIX + r"(?:OVERSIGHT\s+)?CANCELLATION\b", re.I | re.M)
EPISODE = re.compile(r"episode\*{0,2}:?\s+([A-Za-z0-9][A-Za-z0-9-]{3,})", re.I)
STAGED_CARRIER_RESUME = re.compile(
    r"\bResume\s*(?:->|\u2192|then)\s*Start\b[^\n]{0,80}\bstaged\b"
    r"|\bResume\s+mission\b[^\n]{0,80}\bStart(?:\s+mission)?\b",
    re.I,
)
# The oversight's own banners are not one shape: measured on #684, dispatches
# arrived as "RESTART DISPATCH", "## RESTART DISPATCH", "VISION DRIVER DISPATCH",
# "OVERSIGHT RESTART DISPATCH" (7143702385) and "LANE CONTINUATION WATCH"
# (7124370203, 7124855073), and the steer 7149636711 as "STEER DISPATCH". The
# narrow pattern is why the census could claim "zero unclaimed dispatches" while
# four of those sat unread; a banner that matches here still has to carry an
# instruction line and the exact continuation before anything is claimed.
DISPATCH_BANNER = re.compile(
    "^" + _MD_PREFIX
    + r"(?:(?:OVERSIGHT\s+)?(?:(?:VISION\s+DRIVER\s+)?(?:RESTART\s+|STEER\s+)?|BURN\s+WINDOW\s+)DISPATCH\b"
    r"|LANE\s+CONTINUATION\s+WATCH\b)",
    re.I,
)


# Burn-window dispatches write the instruction mid-paragraph ("... State: staged
# since 12:03 HST with its /mission carrier ... Action: re-read session state
# <=60s before acting; restart in place (Resume -> Start on the staged carrier)").
# Measured 2026-11-25: all six 08:51Z burn rows matched the banner and resolved
# to a lane, and failed only this line-start rule, so they sat in every
# heartbeat's "not claimable" list for three hours while oversight read the
# 2-minute tick cadence as the delay. The widening is burn-window only: a
# mid-paragraph "Action:" in any other banner is still not an instruction.
BURN_WINDOW_BANNER = re.compile("^" + _MD_PREFIX + r"BURN\s+WINDOW\s+DISPATCH\b", re.I)
BURN_INLINE_ACTION = re.compile(r"(?:^|\s)Action\*{0,2}:\s*\S", re.I)


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
    first = next(
        (re.sub(r"^[\ufeff#>*\-\s]+|\*{2}", "", line).strip()
         for line in body.splitlines() if line.strip()),
        "",
    )
    if re.match(r"^(?:OVERSIGHT\s+)?(?:(?:VISION\s+DRIVER\s+)?RESTART|BURN\s+WINDOW)\s+DISPATCH\b", first, re.I):
        return True
    return "RESTART" in body[:600].upper()


def episode_closed(comments, comment, parsed):
    """Has the oversight cancelled this dispatch's own episode?

    Every restart dispatch states its own bound: "execute only while episode X is
    still OPEN". Until 2026-11-25 no code read an episode's state at all; the
    claim scan relied on the claim file and the 24-hour TTL, so a dispatch filed
    against a long-closed episode (7129310215, L1-STOP-974) still executed.
    Charts supersession (a newer restart for the lane) and an owner CANCELLATION
    that names this dispatch or its episode both close it. A cancellation that
    names only the lane does not: 7144433519 cancelled L1-STOP-1010 by name, not
    every later Lane 1 episode.
    """
    body = _comment_body(comment)
    match = EPISODE.search(body)
    episode = match.group(1).casefold() if match else None
    for other in comments:
        if other.get("id", 0) <= parsed["comment_id"] or not owner(other):
            continue
        text = _comment_body(other)
        if not CANCELLATION.search(text):
            continue
        if str(parsed["comment_id"]) in text:
            return True
        if episode and episode in text.casefold():
            return True
    return False


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
    body = _comment_body(comment).strip()
    if not body:
        return None
    filed_at = comment.get("created_at") or ""
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
            "filed_at": filed_at,
            "digest": digest,
        }
    # The oversight files the instruction line as "Action for the runner:"
    # (early dispatches), "Action requested (runner alone, ...)" (the L1-STOP
    # episode), or "Runner action requested:" (episode L1-STOP-1014 and the
    # SCMessenger restart). All three are the same bounded restart; anything
    # else is not an instruction and is never claimed.
    instruction = RUNNER_ACTION.search(body)
    if not instruction and BURN_WINDOW_BANNER.match(body):
        instruction = BURN_INLINE_ACTION.search(body)
    if not (restart_dispatch(body) and instruction):
        return None
    # The instruction may be wrapped mid-quote: 7122154514 writes
    # '"continue in\nfull"'. Compare the flattened text so the required words
    # survive a line break, while the digest stays over the comment as filed.
    flat = re.sub(r"\s+", " ", body)
    has_continuation = (f'"{CONTINUATION}"' in flat or f"'{CONTINUATION}'" in flat)
    if has_continuation:
        mode = "continuation"
    elif STAGED_CARRIER_RESUME.search(flat):
        mode = "staged-resume"
    else:
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
            "filed_at": filed_at,
        }
    thread = _lane_thread_from_dispatch(body)
    if not thread or thread not in SESSIONS:
        return None
    return {
        "kind": "restart",
        "mode": mode,
        "comment_id": cid,
        "thread": thread,
        "text": CONTINUATION,
        "filed_at": filed_at,
        "digest": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


# Only the claim window's own expiry is final enough to stop naming: a comment
# older than 24 hours can never be claimed, and nothing about it can change. A
# shape refusal stays named while the comment is young enough to act on, because
# oversight may still re-file it in a shape the watch can read - and once it
# ages out it retires under this same rule.
PERMANENT_REFUSALS = ("stale-beyond-24h",)


def refusal_reason(comment, *, now=None):
    """Why this dispatch-shaped comment is not claimable, named by cause.

    The heartbeat used to print a bare list of ids, so a dispatch refused for a
    shape the code could read looked identical to one that had simply timed out
    of the claim window. Each cause is named here by the same tests
    ``parse_dynamic_dispatch`` applies, in the same order, with the 24-hour
    claim bound first because it is final: a comment never changes.
    """
    body = _comment_body(comment).strip()
    if not body:
        return "empty-body"
    created = comment.get("created_at")
    if created and now is not None:
        created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if now - created_at > timedelta(hours=24):
            return "stale-beyond-24h"
    if not restart_dispatch(body):
        return "banner-names-no-restart"
    instruction = RUNNER_ACTION.search(body)
    if not instruction and BURN_WINDOW_BANNER.match(body):
        instruction = BURN_INLINE_ACTION.search(body)
    if not instruction:
        return "no-instruction"
    flat = re.sub(r"\s+", " ", body)
    if (f'"{CONTINUATION}"' not in flat and f"'{CONTINUATION}'" not in flat
            and not STAGED_CARRIER_RESUME.search(flat)):
        return "no-continuation"
    thread = _lane_thread_from_dispatch(body)
    if not thread or thread not in SESSIONS:
        return "no-lane"
    return "unclassified"


def retire_refusal(known, cid, reason):
    """Record a final refusal once, then stop naming it every two minutes.

    Measured 2026-11-27: 85 ids filled every heartbeat's "not claimable" list for
    three days - nearly all stale past the claim's own 24-hour bound - so the
    list could no longer be read as a queue and a genuinely unreadable fresh
    dispatch would have been invisible inside it. Each final refusal is written
    to the local checkpoint with its reason (durable and auditable); the
    heartbeat then names only refusals that are still young enough to act on.
    """
    if reason not in PERMANENT_REFUSALS:
        return False
    name = f"refuse-dyn-{cid}.json"
    if name in known:
        return True
    checkpoint(name, {"dispatch": cid, "state": "unclaimable", "reason": reason,
                      "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    if isinstance(known, set):
        known.add(name)
    return True


def scan_dispatch_comments(now=None, known=()):
    """Read the whole dispatch page once, and measure what it held.

    Every number the heartbeat reports comes from this one read, so "nothing to
    claim" and "nothing I can read" can no longer print the same sentence.
    """
    now = now or datetime.now(timezone.utc)
    comments = _sync_issue_comments(since_floor=DYNAMIC_SINCE)
    comments.sort(key=lambda item: item.get("id", 0))
    parsed = {}
    for comment in comments:
        result = parse_dynamic_dispatch(comment, now=now)
        if result:
            parsed[comment.get("id")] = result
    # Anything that carries a dispatch banner and still did not parse is named:
    # a STEER that the parser cannot read must not disappear into an empty queue.
    # Only intent counts as drift: a dispatch-shaped comment that also names an
    # episode or carries an instruction line. Otherwise every oversight
    # discussion post would be reported as unreadable and the alarm would be
    # noise instead of a signal.
    unparsed = {}
    for comment in comments:
        if not owner(comment) or comment.get("id") in parsed:
            continue
        body = _comment_body(comment)
        if not DISPATCH_BANNER.match(body):
            continue
        if not (RUNNER_ACTION.search(body) or STEER_TEXT.search(body)
                or EPISODE.search(body)):
            continue
        unparsed[comment.get("id")] = refusal_reason(comment, now=now)
    evidence = {
        "scanned": len(comments),
        "owner": sum(1 for comment in comments if owner(comment)),
        "scanned_through": max((comment.get("id", 0) for comment in comments), default=0),
        "dispatches": len(parsed),
        "claimable": 0,
        "unparsed": unparsed,
        "parsed": parsed,
        "polls": _POLL_STATS["requests"],
        "conditional_304s": _POLL_STATS["conditional_304s"],
    }
    advance_cursor(evidence, known)
    return comments, evidence


def _clear_comments_etag():
    if not _monitor_enabled():
        return
    state = _load_monitor_state()
    if state.get("comments_etag") is not None:
        state["comments_etag"] = None
        _save_monitor_state(state)


def _age_seconds(parsed, now):
    filed = parsed.get("filed_at") or ""
    if not filed:
        return 0.0
    return max(0.0, (now - _parse_iso(filed)).total_seconds())


def skipped_verdict(known, parsed, reason):
    """File the verdict for a dispatch the watch deliberately did not run.

    Measured 2026-11-25: the scan silently ``continue``d on superseded,
    cancelled and closed-episode rows, so on #684 "superseded" and "lost" read
    identically and the audit named exactly those dispatches as unaccounted for.
    One durable verdict per dispatch, never repeated.
    """
    cid = parsed["comment_id"]
    lane = parsed.get("thread") or "unknown"
    name = f"skip-dyn-{cid}-{lane}.json"
    if name in known:
        return False
    known.add(name)
    filed_at = parsed.get("filed_at") or ""
    skipped_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    checkpoint(name, {
        "dispatch": cid,
        "thread": lane,
        "state": "superseded",
        "reason": reason,
        "filed_at": filed_at or None,
        "skipped_at": skipped_at,
    })
    timing = f" (filed {filed_at}, dispositioned {skipped_at})" if filed_at else ""
    issue_comment(f"Vision watch #{cid} / `{lane}`: superseded, no input sent. {reason}.{timing}")
    return True


def antigravity_adapter_ready(control=None):
    """True when #703 Antigravity calibration receipt or control override is active."""
    ctrl = control if control is not None else local_control_state()
    if ctrl.get("antigravity_calibrated"):
        return True
    try:
        from .windows_antigravity_adapter import load_calibration
        return load_calibration() is not None
    except Exception:
        return False


def _execute_antigravity(out, cid, parsed):
    from .windows_antigravity_adapter import execute_antigravity_dispatch
    return execute_antigravity_dispatch(out, cid, parsed)


def _stop_killswitch_active(comments):
    pattern = re.compile(r"^" + _MD_PREFIX + r"(?:VISION-DISPATCH\s+)?STOP\b", re.I | re.M)
    for item in comments:
        if owner(item) and pattern.search(_comment_body(item)):
            return True
    return False


def _standing_lane_still(lane, comments=(), *, idle_minutes=30, cooldown_minutes=20, now=None):
    """True when the queue is non-empty and Lane 1 + repo have been still."""
    now = now or datetime.now(timezone.utc)
    recent_floor = now - timedelta(minutes=cooldown_minutes)
    lane_token = f"`{lane}`"
    for item in comments:
        ts = item.get("created_at")
        if not ts or _parse_iso(ts) < recent_floor:
            continue
        body = _comment_body(item)
        if lane_token in body and (
            body.startswith("Vision restart ") or body.startswith("Vision standing restart log")
        ):
            return False
    issues = api("repos/Treystu/harness/issues?state=open&per_page=1")
    if not issues:
        return False
    commits = api("repos/Treystu/harness/commits?sha=main&per_page=1")
    pulls = api("repos/Treystu/harness/pulls?state=open&sort=updated&direction=desc&per_page=1")
    c295 = api(
        "repos/Treystu/harness/issues/295/comments?since="
        f"{(now - timedelta(minutes=idle_minutes)).strftime('%Y-%m-%dT%H:%M:%SZ')}&per_page=20"
    )
    if _stop_killswitch_active(c295):
        return False
    latest_ts = None
    for src, key in ((commits, ("commit", "committer", "date")),):
        if src:
            ts = src[0].get(key[0], {}).get(key[1], {}).get(key[2])
            if ts:
                dt = _parse_iso(ts)
                if latest_ts is None or dt > latest_ts:
                    latest_ts = dt
    if pulls:
        ts = pulls[0].get("updated_at")
        if ts:
            dt = _parse_iso(ts)
            if latest_ts is None or dt > latest_ts:
                latest_ts = dt
    for item in c295:
        ts = item.get("created_at")
        if ts:
            dt = _parse_iso(ts)
            if latest_ts is None or dt > latest_ts:
                latest_ts = dt
    if latest_ts is not None and (now - latest_ts) < timedelta(minutes=idle_minutes):
        return False
    return True


def poll_standing_burndown_restarts(known, cancelled=(), control=None, *, now=None,
                                    idle_minutes=30, cooldown_minutes=20):
    """Standing Rule 7183684276: autonomous in-place restart when continuous burndown is still."""
    now = now or datetime.now(timezone.utc)
    ctrl = control if control is not None else local_control_state()
    if not ctrl.get("continuous_burndown"):
        return False
    if pause_requested():
        return False
    comments = _sync_issue_comments(since_floor=SINCE)
    if _stop_killswitch_active(comments):
        return False
    watched = tuple(ctrl.get("watched_lanes") or (THREAD,))
    state = _load_monitor_state() if _monitor_enabled() else {}
    restarts = state.get("standing_restarts") if isinstance(state.get("standing_restarts"), dict) else {}
    state_dir = Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner"
    for lane in watched:
        if lane in cancelled or lane != THREAD:
            continue
        last_raw = restarts.get(lane)
        if last_raw:
            try:
                if (now - _parse_iso(last_raw)) < timedelta(minutes=cooldown_minutes):
                    continue
            except ValueError:
                pass
        if not _standing_lane_still(
            lane, comments, idle_minutes=idle_minutes, cooldown_minutes=cooldown_minutes, now=now
        ):
            continue
        require_driver_runtime()
        if not desktop_idle():
            return "deferred"
        blocker = foreground_blocker()
        if blocker is not None:
            return "deferred"
        guard_approval()
        bucket = now.strftime("%Y%m%d-%H%M%S")
        item = f"standing-{bucket}-{lane}"
        out = state_dir / item
        try:
            out.mkdir(parents=True, exist_ok=True)
            mission = {
                "thread": lane,
                "dispatch": "standing-7183684276",
                "standing": True,
                "skip_pre_ack": True,
                "phase_timeout": dynamic_phase_timeout(item),
            }
            digest = hashlib.sha256(f"{item}:standing-7183684276".encode()).hexdigest()
            status = "parked" if execute(out, item, mission, digest, ()) else "verified running"
        except UncertainDriverExit as error:
            checkpoint(f"interlock-{item}.json", {"dispatch": "standing-7183684276", "thread": lane, "state": str(error)})
            issue_comment(f"Vision standing restart interlock `{lane}`: {error}")
            status = "parked with desktop interlock"
        except (OSError, RuntimeError) as error:
            status = f"parked after standing attempt: {error}"
            issue_comment(f"Vision standing restart log (Rule 7183684276) / `{lane}`: {status}.")
        finally:
            _clear_comments_etag()
        checkpoint(f"standing-result-{bucket}-{lane}.json", {
            "rule": 7183684276, "thread": lane, "state": status,
        })
        if _monitor_enabled():
            fresh_state = _load_monitor_state()
            map_r = fresh_state.get("standing_restarts") if isinstance(fresh_state.get("standing_restarts"), dict) else {}
            map_r[lane] = now.isoformat()
            fresh_state["standing_restarts"] = map_r
            _save_monitor_state(fresh_state)
        return True
    return False


def poll_dynamic_dispatches(known, *, now=None, unclaimed=None, cancelled=()):
    """Poll #684 for new owner-approved dispatches and execute at most one unclaimed item.

    ``unclaimed`` is an optional sink: a dispatch-shaped owner comment that the
    parser refuses is recorded in it as ``{id: reason}``. The watch reported "no
    unclaimed dispatches" for two hours while 7145072019 and 7146588401 sat
    unparsed, so "nothing to claim" and "nothing I can read" must not read the
    same - and a bare id could not say which of the two a row was.
    """
    now = now or datetime.now(timezone.utc)
    comments, evidence = scan_dispatch_comments(now=now, known=known)
    LAST_SCAN.clear()
    LAST_SCAN.update({key: value for key, value in evidence.items() if key != "parsed"})
    # Episode supersession: only the newest parsed restart per lane is claimable.
    # Measured 2026-11-25 01:06Z, after the wording cure went live: the scan takes
    # the oldest unclaimed id first, so it claimed 7129310215 (episode L1-STOP-974,
    # filed 10:50Z, superseded fourteen hours later) instead of the pending
    # L1-STOP-1014. Every dispatch says "execute only while this episode is still
    # OPEN"; this is that condition in code, from GitHub evidence alone.
    newest_restart = {}
    for comment in comments:
        parsed = parse_dynamic_dispatch(comment, now=now)
        if parsed and parsed["kind"] == "restart":
            lane = parsed["thread"]
            newest_restart[lane] = max(newest_restart.get(lane, 0), parsed["comment_id"])
    claimable = 0
    state_dir = Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner"
    for comment in comments:
        parsed = parse_dynamic_dispatch(comment, now=now)
        if not parsed:
            body = _comment_body(comment)
            if unclaimed is not None and owner(comment) and DISPATCH_BANNER.match(body):
                cid = comment.get("id")
                reason = refusal_reason(comment, now=now)
                if retire_refusal(known, cid, reason):
                    continue
                unclaimed[cid] = reason
            continue
        cid = parsed["comment_id"]
        if parsed["kind"] == "restart" and newest_restart.get(parsed["thread"]) != cid:
            # A later restart for this lane exists: this episode is closed and
            # nothing is sent for it. The later dispatch is the one that speaks.
            skipped_verdict(known, parsed, "a newer restart for this lane supersedes this episode")
            continue
        if parsed["kind"] == "restart" and episode_closed(comments, comment, parsed):
            # The oversight cancelled this episode by name: no input for it.
            skipped_verdict(known, parsed, "the oversight cancelled this episode by name")
            continue
        if parsed["kind"] == "restart" and parsed["thread"] in cancelled:
            # The operator cancelled this lane at the control surface; a restart
            # for it is closed until that entry is removed. Measured 2026-11-25:
            # control.json carried cancelled_lanes=["315608d2"] while the watch
            # still treated Lane 1 restarts as claimable.
            skipped_verdict(known, parsed, "the operator cancelled this lane at the control surface")
            continue
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
        claimable += 1
        LAST_SCAN["claimable"] = claimable
        guard_approval()
        if parsed["kind"] == "antigravity-park":
            if antigravity_adapter_ready():
                require_driver_runtime()
                if not desktop_idle():
                    heartbeat(known, "waiting for owner desktop idle", current_evidence())
                    return "deferred"
                checkpoint(claim, {"dispatch": cid, "target": "antigravity", "kind": "antigravity-restart"})
                if isinstance(known, set):
                    known.add(claim)
                out = state_dir / item
                try:
                    out.mkdir(parents=True, exist_ok=True)
                    status = _execute_antigravity(out, cid, parsed)
                except (OSError, RuntimeError) as error:
                    status = f"parked after claim: {error}"
                finally:
                    _clear_comments_etag()
                result_name = f"result-{item}.json"
                checkpoint(result_name, {"dispatch": cid, "target": "antigravity", "state": status})
                if isinstance(known, set):
                    known.add(result_name)
                issue_comment(f"Vision restart result #{cid} / `antigravity`: {status}.")
                return True
            checkpoint(claim, {"dispatch": cid, "target": "antigravity", "kind": parsed["kind"]})
            if isinstance(known, set):
                known.add(claim)
            status = f"parked: {parsed['reason']}"
            result_name = f"result-{item}.json"
            checkpoint(result_name, {"dispatch": cid, "target": "antigravity", "state": status})
            if isinstance(known, set):
                known.add(result_name)
            issue_comment(f"Vision watch #{cid} / `antigravity`: {status}. FreeBuff remains active.")
            return True
        require_driver_runtime()
        age_s = _age_seconds(parsed, now)
        if not desktop_idle():
            if age_s > 300:
                report_stale_pickup(known, cid, thread, age_s, "waiting for owner desktop idle")
            heartbeat(known, "waiting for owner desktop idle", current_evidence())
            return "deferred"
        blocker = foreground_blocker()
        if blocker is not None:
            report_foreground_blocked(known, cid, thread, blocker)
            if age_s > 300:
                report_stale_pickup(known, cid, thread, age_s, f"foreground blocked by {blocker[2]!r}")
            return "deferred"
        checkpoint(claim, {"dispatch": cid, "thread": thread, "sha256": parsed["digest"]})
        if isinstance(known, set):
            known.add(claim)
        out = state_dir / item
        try:
            out.mkdir(parents=True, exist_ok=True)
            mission = {
                "thread": thread,
                "dispatch": cid,
                "standing": True,
                "filed_at": parsed.get("filed_at") or "",
                "phase_timeout": dynamic_phase_timeout(item),
            }
            if parsed.get("mode") == "staged-resume":
                mission["phases"] = ("search", "query", "select", "vision-resume")
            status = "parked" if execute(out, item, mission, parsed["digest"], ()) else "verified running"
        except UncertainDriverExit as error:
            checkpoint(f"interlock-{item}.json", {"dispatch": cid, "thread": thread, "state": str(error)})
            issue_comment(f"Vision watch desktop interlock #{cid} / `{thread}`. {error}")
            status = "parked with desktop interlock"
        except (OSError, RuntimeError) as error:
            status = f"parked after claim: {error}"
            issue_comment(f"Vision watch #{cid} / `{thread}` {status}.")
        finally:
            _clear_comments_etag()
        result_name = f"result-{item}.json"
        checkpoint(result_name, {"dispatch": cid, "thread": thread, "state": status})
        if isinstance(known, set):
            known.add(result_name)
        return True
    return False


def run_burn(receipts, known, cancelled=()):
    source = receipts[BURN_QUEUE]
    end = datetime.fromisoformat(source["created_at"]) + timedelta(hours=3)
    if datetime.now(timezone.utc) >= end:
        unclaimed = {}
        drained = 0
        while drained < 20:
            unclaimed.clear()
            try:
                claimed = poll_dynamic_dispatches(known, unclaimed=unclaimed, cancelled=cancelled)
            except Exception as error:
                report_claim_fault(known, error)
                return
            if not claimed:
                break
            drained += 1
            if claimed == "deferred":
                return
        if drained:
            return
        control = local_control_state()
        if control.get("continuous_burndown") and control.get("from_file"):
            try:
                standing_outcome = poll_standing_burndown_restarts(known, cancelled=cancelled, control=control)
            except Exception as error:
                report_claim_fault(known, error)
                return
            if standing_outcome:
                return
        evidence = current_evidence()
        problems = canary(evidence or {})
        if problems:
            heartbeat(known, "dynamic oversight dispatch active; canary FAILED: "
                             + "; ".join(problems), evidence)
            return
        if unclaimed:
            details = ", ".join(f"#{cid} ({reason})"
                               for cid, reason in sorted(unclaimed.items()))
            heartbeat(known, f"dynamic oversight dispatch active; {len(unclaimed)} "
                             f"dispatch(es) present but not claimable: {details}",
                      evidence)
            return
        heartbeat(known, "dynamic oversight dispatch active; no unclaimed dispatches", evidence)
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
            heartbeat(known, "waiting for owner desktop idle", current_evidence())
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
    heartbeat(known, "no unclaimed burn rows; parked rows stay isolated", current_evidence())


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
            heartbeat(known, "waiting for owner desktop idle before restoration", current_evidence())
            return True
        digest = hashlib.sha256(receipts[dispatch_id]["body"].encode()).hexdigest()
        checkpoint(f"claim-{item}.json", {"dispatch": dispatch_id, "thread": thread, "sha256": digest})
        output = state_dir / item
        try:
            output.mkdir(parents=True)
            mission = {"thread": thread, "dispatch": dispatch_id, "standing": True}
            mission["phase_timeout"] = dynamic_phase_timeout(item)
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


def report_refusal(reason):
    """A tick that refuses to drive must file why, at most once per 15m bucket.

    Silence is the failure mode this exists for: ``main`` has several refusing
    returns (unpublished head, stale interlock, an owner pause in the ledger) and
    each of them used to exit 0 with no checkpoint and no comment, which is
    indistinguishable from a tick that did its work. Every refusal path now names
    itself through here.
    """
    known = checkpoints()
    now = datetime.now(timezone.utc)
    bucket = now.strftime("%Y%m%d-%H") + f"-{now.minute // 15}"
    digest = hashlib.sha256(reason.encode("utf-8")).hexdigest()[:8]
    name = f"refusal-{bucket}-{digest}.json"
    if name in known:
        return False
    known.add(name)
    checkpoint(name, {"state": "refused", "reason": reason})
    issue_comment(
        f"Vision watch {CUTOVER} refused this tick: {reason}. No desktop action taken."
    )
    return True


def report_paused(control):
    """A paused watch with work waiting must say so, within one tick.

    Measured 2026-11-25: the control surface was paused at 01:28Z and three
    dispatches (7151203687, 7149910847, 7151843755) sat unclaimed for hours with
    no filing about it - pause was permanent, silent, and invisible to oversight.
    This runs no desktop action at all: it reads the dispatch page and files at
    most one escalation per hour naming what is waiting.
    """
    known = checkpoints()
    comments, evidence = scan_dispatch_comments(known=known)
    del comments
    cancelled = tuple(control.get("cancelled_lanes") or ())
    newest = {}
    for cid, parsed in evidence["parsed"].items():
        if parsed["kind"] == "restart":
            lane = parsed["thread"]
            newest[lane] = max(newest.get(lane, 0), cid)
    waiting = []
    for cid, parsed in sorted(evidence["parsed"].items()):
        lane = parsed.get("thread")
        if lane in cancelled:
            continue
        if parsed["kind"] == "restart" and newest.get(lane) != cid:
            continue
        if f"claim-dyn-{cid}-{lane}.json" in known:
            continue
        waiting.append(cid)
    # Once per hour per distinct waiting set: the same queue must not be filed
    # twice, and a dispatch that arrives while paused must still be announced.
    digest = hashlib.sha256(",".join(str(cid) for cid in waiting).encode()).hexdigest()[:8]
    name = "paused-escalation-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H") + f"-{digest}.json"
    if not waiting or name in known:
        return False
    checkpoint(name, {"state": "paused-with-pending", "waiting": sorted(waiting)})
    issue_comment(f"Vision watch {CUTOVER} is PAUSED at the control surface with "
                  f"{len(waiting)} dispatch(es) waiting: "
                  + ", ".join(f"#{cid}" for cid in sorted(waiting))
                  + ". Nothing will run until the control surface is unpaused. "
                  + describe_scan(evidence))
    return True


def main():
    _POLL_STATS["requests"] = 0
    _POLL_STATS["conditional_304s"] = 0
    control = local_control_state()
    if not control["enabled"]:
        return
    if control["paused"]:
        # Escalate, do not act: a pause that never speaks is the stall mode.
        report_paused(control)
        return
    head = worktree_head(refresh=True)
    if head is None:
        report_refusal(head_refusal_detail())
        return
    known = checkpoints()
    if "owner-paused.json" in known:
        report_refusal("an owner pause is recorded in the ledger (owner-paused.json)")
        return
    if any(name.startswith("interlock-") and not name.startswith("interlock-released-")
           and f"interlock-released-{name[len('interlock-'):]}" not in known for name in known):
        report_refusal("an unreleased desktop interlock is recorded in the ledger")
        return
    if "desktop-interlock.json" in known:
        if "interlock-released-7111294374.json" not in known:
            report_refusal("desktop-interlock.json is recorded with no release checkpoint")
            return
    if "paused.json" in known and read_checkpoint("paused.json")["state"] == "owner-paused":
        report_refusal("paused.json records an owner pause")
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
    run_burn(receipts, known, control.get("cancelled_lanes", ()))


if __name__ == "__main__":
    main()
