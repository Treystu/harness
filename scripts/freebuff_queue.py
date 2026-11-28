"""One source of truth for the Freebuff lane dispatch queue issue.

Measured 2026-11-28: issue #684 reached GitHub's hard 2,500-comment ceiling, so
every POST to ``.../issues/684/comments`` answers HTTP 403 ("Commenting is
disabled on issues with more than 2500 comments"). The laptop driver watch then
ticked in ``state: error`` and nothing could be claimed or filed -- an outage
with no failure the driver could recover from on its own.

The rule, stated here once and only here:

* The live queue id lives in ``queue.json`` (``HARNESS_FREEBUFF_QUEUE_STATE``;
  default ``~/.harness/driver-watch/queue.json``). ``windows_freebuff_runner``,
  ``windows_freebuff_watch`` and ``harness/laptop_driver_ctl`` all resolve the
  queue through this module, so there is one number, not three literals.
* ``history`` records every queue this driver has used. Reads cover the live
  queue AND the history (plus the original #684, never dropped), so a dispatch
  filed on an older queue and any receipt for it keep resolving until they
  drain.
* A POST the comment cap rejects rolls the queue over instead of failing: the
  newest open ``Freebuff lane dispatch queue`` issue is reused, or one is
  created, the mapping is recorded, and the post is retried on the new queue.
  Callers never see the 403.

Nothing here needs a token of its own: ``gh`` is the credential the runner
already uses, and it is the same user that would file a dispatch by hand.
"""
import json
import os
import subprocess
from pathlib import Path

REPO = "Treystu/harness"
#: The queue every dispatch and receipt in this driver's history was filed on.
DEFAULT_QUEUE = 684
#: GitHub's ceiling; a queue at or past it cannot accept another comment.
COMMENT_CAP = 2500
#: Title prefix a rolled-over queue carries, used to locate (not duplicate) one.
TITLE_PREFIX = "Freebuff lane dispatch queue"
STATE_ENV = "HARNESS_FREEBUFF_QUEUE_STATE"


def state_path():
    """Where the queue mapping lives: one file, resolved identically by all callers."""
    raw = os.environ.get(STATE_ENV, "").strip()
    if raw:
        return Path(raw)
    watch_dir = os.environ.get("HARNESS_DRIVER_WATCH_DIR", "").strip()
    base = Path(watch_dir) if watch_dir else Path.home() / ".harness" / "driver-watch"
    return base / "queue.json"


def load(path=None):
    """The recorded mapping, defaulting to the original queue when absent."""
    target = Path(path) if path else state_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    try:
        current = int(raw.get("current"))
    except (TypeError, ValueError):
        current = DEFAULT_QUEUE
    history = []
    for item in raw.get("history") or ():
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value != current and value not in history:
            history.append(value)
    return {
        "current": current,
        "history": history,
        "rolled_at": str(raw.get("rolled_at") or ""),
        "reason": str(raw.get("reason") or ""),
    }


def save(state, path=None):
    """Write the mapping atomically: a half-written queue file would be an outage."""
    target = Path(path) if path else state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"current": int(state["current"]), "history": [int(i) for i in state.get("history") or ()],
         "rolled_at": state.get("rolled_at") or "", "reason": state.get("reason") or ""},
        indent=2, sort_keys=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(payload + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def queue_id(path=None):
    """The live dispatch queue issue number."""
    return load(path)["current"]


def queue_ids(path=None):
    """Every queue to read: live first, then history, then the original queue.

    #684 is never dropped even when a fresh state file forgets it, because the
    dispatches and receipts already filed there have to keep resolving.
    """
    state = load(path)
    ordered = [state["current"]] + state["history"]
    if DEFAULT_QUEUE not in ordered:
        ordered.append(DEFAULT_QUEUE)
    return ordered


def comments_endpoint(issue):
    return f"repos/{REPO}/issues/{int(issue)}/comments"


def endpoints(path=None):
    """The comment endpoints to read, live queue first."""
    return [comments_endpoint(issue) for issue in queue_ids(path)]


def issue_url(issue):
    return f"https://api.github.com/repos/{REPO}/issues/{int(issue)}"


def comment_belongs_to_queue(comment, path=None):
    """Is this comment on a queue this driver reads (live or historical)?"""
    url = str((comment or {}).get("issue_url") or "").casefold()
    return any(url.endswith(f"/issues/{issue}") for issue in queue_ids(path))


def is_comment_cap_error(message):
    """Did GitHub refuse this POST because the issue's comment list is full?"""
    text = str(message or "").casefold()
    if "more than 2500 comments" in text:
        return True
    return "commenting is disabled" in text and "comment" in text


def record_rotation(new_issue, old_issue, reason, path=None):
    """Record that ``new_issue`` is live and ``old_issue`` is now history."""
    state = load(path)
    history = [int(old_issue)] + [issue for issue in state["history"] if issue != int(old_issue)]
    if int(new_issue) in history:
        history.remove(int(new_issue))
    updated = {
        "current": int(new_issue),
        "history": history,
        "rolled_at": _utc_now(),
        "reason": str(reason or "")[:400],
    }
    save(updated, path)
    return updated


def retarget(issue, reason="", path=None):
    """Designate ``issue`` the live queue, keeping every earlier one readable.

    Roll-over happens by itself when a POST is capped; oversight can also name
    the successor channel (2026-11-28: #844 succeeded #684, after the automatic
    roll-over had already chosen #843). A designation is authoritative -- the
    previous live queue moves to ``history`` with the rest, so a dispatch or
    receipt filed there keeps resolving instead of becoming invisible.
    """
    try:
        number = int(issue)
    except (TypeError, ValueError):
        raise ValueError(f"a queue is an issue number, not {issue!r}") from None
    if number <= 0:
        raise ValueError(f"a queue is an issue number, not {issue!r}")
    state = load(path)
    if number == state["current"]:
        return state
    return record_rotation(number, state["current"], f"retargeted: {reason}".strip(": "), path)


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh(args, timeout=60):
    kwargs = {"capture_output": True, "text": True, "encoding": "utf-8", "timeout": timeout,
              "check": False}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    result = subprocess.run(["gh", *args], **kwargs)
    if result.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(args)} failed: {(result.stderr or result.stdout or '').strip()[:220]}")
    return result.stdout or ""


def locate_replacement(current, listed=None):
    """The newest open roll-over queue that is not ``current``, or None.

    A concurrent tick may already have created one; reusing it keeps one live
    queue instead of racing two, and keeps the mapping single-valued.
    """
    if listed is None:
        raw = _gh(["issue", "list", "--repo", REPO, "--state", "open",
                   "--search", f"{TITLE_PREFIX} in:title",
                   "--json", "number,title", "--limit", "20"])
        listed = json.loads(raw or "[]")
    candidates = []
    for item in listed or ():
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        if number == int(current):
            continue
        if str(item.get("title") or "").startswith(TITLE_PREFIX):
            candidates.append(number)
    return max(candidates) if candidates else None


def create_replacement(current, reason=""):
    """File the next queue issue and return its number."""
    body = (
        "Roll-over of the Freebuff lane dispatch queue.\n\n"
        f"#{int(current)} reached GitHub's hard {COMMENT_CAP}-comment ceiling, so it "
        "cannot accept another dispatch, claim or receipt. This issue is the live "
        "queue from now on.\n\n"
        "The driver reads this queue AND every queue in its history, so dispatches "
        "and receipts already filed on the previous queue keep resolving until they "
        "drain. File dispatches here in the same `## RESTART DISPATCH` form.\n\n"
        f"Roll-over reason: {(reason or 'comment cap').strip()[:200]}\n"
    )
    output = _gh(["issue", "create", "--repo", REPO,
                  "--title", f"{TITLE_PREFIX} (rollover after #{int(current)})",
                  "--body", body])
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("gh issue create returned no URL for the replacement queue")
    return int(lines[-1].rstrip("/").rsplit("/", 1)[-1])


def post(body, *, post_to, path=None, locate=None, create=None):
    """Post a queue comment, rolling over when the live queue is comment-capped.

    ``post_to(issue, text)`` performs the POST and raises ``RuntimeError`` on
    failure; ``locate``/``create`` are injectable so the roll-over is testable
    without touching GitHub.
    """
    state = load(path)
    try:
        return post_to(state["current"], body)
    except RuntimeError as error:
        if not is_comment_cap_error(str(error)):
            raise
        replacement = None
        try:
            replacement = (locate or locate_replacement)(state["current"])
        except (RuntimeError, ValueError):
            replacement = None
        if not replacement:
            replacement = (create or create_replacement)(state["current"], str(error))
        record_rotation(replacement, state["current"], str(error), path)
        return post_to(int(replacement), body)


def main(argv=None):
    """Designate or print the queue mapping; the printed state is the read-back."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="freebuff_queue",
        description="Show or set the Freebuff lane dispatch queue issue.")
    parser.add_argument("--state", default=None, help="queue.json to read/write")
    parser.add_argument("--retarget", type=int, default=None, metavar="ISSUE",
                        help="designate ISSUE the live queue")
    parser.add_argument("--reason", default="", help="why the queue moved; recorded")
    args = parser.parse_args(argv)
    if args.retarget is not None:
        retarget(args.retarget, args.reason, args.state)
    state = load(args.state)
    print(json.dumps(state, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
