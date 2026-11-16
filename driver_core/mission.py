"""#483 B3/B4 -- the mission envelope, its epoch, and the approval binding.

The issue's two halves are an executor (B3: poll the private ledger, claim,
heartbeat, per-field read-back, file receipts) and a security model (B4: an
author allowlist, GitHub text treated as data, and an approval binding for
irreversible actions that is action + target + screenshot fingerprint + expiry,
single-use). The live executor is not producible from this lane -- it needs the
private ledger, a serving driver-core and a supervised desktop -- but the
security model is exactly the part that must be right *before* any executor is
allowed to run, and it is provable offline.

What this module declares, and refuses rather than infers:

* **the author allowlist** -- a mission is accepted only from a declared author.
  An empty allowlist is default-deny, and the refusal says so, because the
  failure mode of a permissive default ("nobody configured it, so allow
  everyone") is a public repo writing missions into a private ledger.
* **the mission epoch** -- GitHub has no writer lease, so a mission carries the
  epoch it was filed under; an expired or undatable epoch is refused before the
  action is even resolved. Stale work is the failure this prevents: a mission
  that sat in a queue for an hour must not execute against today's screen.
* **the action boundary** -- GitHub text is data. A mission names one action,
  and that name must resolve in the declared vocabulary; a payload cannot carry
  a command, a path, a selector or an undeclared parameter, because the same
  refusal that guards the decision tier guards the parser.
* **the approval binding** -- one single-use approval, bound to the exact
  action, target and screenshot fingerprint it was issued for, with its own
  expiry. It is stored through :class:`driver_core.consent_ledger.RestConsentLedger`,
  so "available" -> "pending" -> "spent" is one durable transition: a spent
  approval can never execute twice, and a crash mid-execution leaves the state
  pending rather than silently available again.
"""
import json
import os
import time

from .actions import DEFAULT_VOCABULARY
from .consent_ledger import (ConsentLedgerError, RestConsentLedger)
from .errors import VocabularyError

#: The mission envelope's schema name. Versioned like every other record this
#: package carries: a reader that does not know this name refuses it.
MISSION_SCHEMA = "mission@1"

#: The approval's schema name, for the same reason.
APPROVAL_SCHEMA = "approval@1"

#: How long a mission's epoch is good for when the mission does not say.
#: Fifteen minutes: long enough for a poll cycle plus a supervised step, short
#: enough that a mission left in a queue cannot execute against a screen that
#: has moved on.
DEFAULT_EPOCH_SECONDS = 900.0

#: How long one approval is good for. Two minutes, matching a capture grant:
#: the operator's act is close enough to the execution to be meaningful.
DEFAULT_APPROVAL_SECONDS = 120.0

#: How far a mission's epoch stamp may run ahead of the reader's clock before it
#: is a clock disagreement rather than jitter. Same reasoning as the frame gate.
MAX_CLOCK_LEAD = 1.0

#: The fields a mission must carry, exactly. Undeclared fields are refused, not
#: ignored: a payload that smuggles an extra key is trying to influence
#: execution through a channel this contract does not have.
REQUIRED_FIELDS = ("action", "author", "epoch", "id", "params")

#: The fields a mission may carry in addition to the required ones.
OPTIONAL_FIELDS = ("approval", "fingerprint", "note", "target")

#: Every field a mission may carry. Anything else is refused by name.
MISSION_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


_APPROVAL_ID = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class MissionRefused(VocabularyError):
    """A mission the executor may not run, with the reason attached."""


def _is_number(value):
    import math
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _checked_author(author):
    if not isinstance(author, str) or not author.strip():
        raise MissionRefused(
            f"a mission needs a non-blank author, got {author!r}")
    return author.strip().lower()


def author_allowed(author, allowlist):
    """``(ok, detail)``: is this mission's author on the declared list?

    The allowlist is code-owned and exact after case-folding. An empty
    allowlist is default-deny with its own wording, because a permissive
    default would mean a public surface could write missions into a private
    ledger the moment nobody configured it.
    """
    try:
        checked = _checked_author(author)
    except MissionRefused as exc:
        return False, str(exc)
    declared = tuple(a.strip().lower() for a in (allowlist or ()))
    if not declared:
        return False, ("no mission authors are allowlisted; a mission from "
                       f"{checked!r} is refused (declare the authors in code)")
    if checked not in declared:
        return False, (f"author {checked!r} is not on the mission allowlist "
                       f"(declared: {list(declared)})")
    return True, ""


def mission_epoch(*, clock=None, ttl=DEFAULT_EPOCH_SECONDS):
    """A mission's epoch record: when it was issued and when it stops being valid."""
    now = (clock or time.time)()
    if not _is_number(now):
        raise MissionRefused(
            f"the epoch clock returned {now!r}, so no epoch can be issued")
    if not _is_number(ttl) or ttl < 0:
        raise MissionRefused(
            f"an epoch ttl must be a finite number of seconds, got {ttl!r}")
    return {"issued_at": float(now), "expires_at": float(now) + float(ttl),
            "ttl": float(ttl)}


def check_epoch(epoch, *, now=None):
    """``(ok, detail)``: is this mission still inside its epoch?

    Refusals name which of the four things went wrong: no epoch, an epoch with
    no usable expiry, one stamped in the future (the filer and the executor
    disagree about the clock, and no window makes that safe), or one that has
    simply expired.
    """
    reader = time.time() if now is None else float(now)
    if not isinstance(epoch, dict):
        return False, (f"a mission needs an epoch record, got "
                       f"{type(epoch).__name__}; an undated mission cannot be "
                       f"told from a stale one")
    expires_at = epoch.get("expires_at")
    if not _is_number(expires_at):
        return False, "a mission's epoch carries no usable expires_at"
    issued_at = epoch.get("issued_at")
    if _is_number(issued_at) and float(issued_at) - reader > MAX_CLOCK_LEAD:
        return False, (f"a mission's epoch is stamped {float(issued_at) - reader:.3f}s "
                       f"in the future; the filer and the executor disagree "
                       f"about the clock, so no window makes this safe")
    if reader > float(expires_at):
        return False, (f"mission epoch expired {reader - float(expires_at):.3f}s "
                       f"ago; a stale mission is refused rather than retried")
    return True, ""


def approval_grant(*, action, target, fingerprint, expires_at):
    """The exact material one approval is bound to.

    Four fields, in the issue's own words: action + target + screenshot
    fingerprint + expiry. Nothing else is part of the grant, so nothing else
    can be changed without becoming a different approval.
    """
    if not isinstance(action, str) or not action.strip():
        raise MissionRefused(f"an approval needs an action name, got {action!r}")
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        raise MissionRefused(
            "an approval needs the screenshot fingerprint it was granted for; "
            f"got {fingerprint!r}")
    if not _is_number(expires_at):
        raise MissionRefused(
            f"an approval needs a finite expires_at, got {expires_at!r}")
    return {"schema": APPROVAL_SCHEMA, "action": action.strip(),
            "target": target if isinstance(target, (str, dict)) else repr(target),
            "fingerprint": fingerprint.strip(),
            "expires_at": float(expires_at)}


class ApprovalStore:
    """Single-use approvals, bound to their exact grant and spent durably.

    One store owns one directory: an ``approvals/<id>.json`` record carries the
    four bound fields, and the SQLite REST ledger carries the spend-once state.
    Both are needed and neither is redundant -- the record is what an execution
    is compared against (including its expiry, which a hash cannot carry), and
    the ledger is what makes "spent" survive a restart and refuse a second run.
    """

    def __init__(self, root, *, max_records=None):
        self.root = os.path.abspath(root)
        kwargs = {} if max_records is None else {"max_records": max_records}
        self._ledger = RestConsentLedger(
            os.path.join(self.root, "mission-approvals.sqlite3"), **kwargs)

    def _path(self, approval_id):
        text = str(approval_id or "").strip()
        if not _APPROVAL_ID.match(text) or text in (".", ".."):
            raise MissionRefused(
                "approval id must be a plain identifier (letters, digits, "
                f"'.', '_', '-'), got {approval_id!r}")
        directory = os.path.join(self.root, "approvals")
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, text + ".json")

    def issue(self, approval_id, *, action, target, fingerprint, expires_at):
        """Bind one id to one exact grant and return its execution guard."""
        grant = approval_grant(action=action, target=target,
                               fingerprint=fingerprint,
                               expires_at=expires_at)
        guard = self._ledger.bind(str(approval_id), grant)
        record = {"id": str(approval_id), **grant}
        path = self._path(approval_id)
        temporary = f"{path}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
        os.replace(temporary, path)
        return guard

    def read(self, approval_id):
        """The issued record, or ``None`` when nothing was issued under that id."""
        try:
            with open(self._path(approval_id), encoding="utf-8") as handle:
                data = json.load(handle)
        except (FileNotFoundError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def validate(self, approval_id, *, action, target, fingerprint, now=None):
        """``(guard, "")`` when this id may run this exact grant, else ``(None, why)``.

        Every refusal names the field that stopped it. The comparison is against
        the issued record, so a re-issued id cannot be pointed at a new target,
        and expiry is checked here because it is a clock fact rather than part
        of the hashed grant.
        """
        reader = time.time() if now is None else float(now)
        record = self.read(approval_id)
        if record is None:
            return None, f"unknown approval {approval_id!r}; nothing was issued"
        wanted = approval_grant(action=action, target=target,
                                fingerprint=fingerprint,
                                expires_at=record.get("expires_at"))
        for field in ("action", "target", "fingerprint"):
            if record.get(field) != wanted[field]:
                return None, (
                    f"approval {approval_id!r} was issued for a different "
                    f"{field}; it does not authorise this execution")
        if reader > float(record["expires_at"]):
            return None, (f"approval {approval_id!r} expired "
                          f"{reader - float(record['expires_at']):.3f}s ago; "
                          f"the operator must grant a new one")
        try:
            guard = self._ledger.bind(str(approval_id), wanted)
        except ConsentLedgerError:
            return None, (f"approval {approval_id!r} is bound to a different "
                          f"grant in the replay ledger")
        except Exception as exc:  # a storage failure is a refusal, not a pass
            return None, f"approval {approval_id!r} could not be read: {exc}"
        if not guard.available():
            return None, (f"approval {approval_id!r} has already been spent; "
                          f"a spent approval cannot execute twice")
        return guard, ""

    def spend(self, guard, *, succeeded=True):
        """Move one claimed approval to spent (or back to available on failure)."""
        if not guard.claim():
            raise MissionRefused(
                "this approval is no longer available; it was spent by another "
                "execution between validation and claim")
        guard.finish(succeeded=succeeded)


def parse_mission(payload, *, allowlist, vocabulary=DEFAULT_VOCABULARY,
                  now=None):
    """Normalise one mission, or refuse it by name.

    The order is deliberate: identity first, then time, then the action
    boundary, then the parameters. A mission from an unlisted author is refused
    without its action ever being resolved, so a hostile payload cannot even
    reach the vocabulary lookup that would tell it which names exist.
    """
    reader = time.time() if now is None else float(now)
    if not isinstance(payload, dict):
        raise MissionRefused(
            f"a mission must be a mapping, got {type(payload).__name__}")
    unknown = sorted(set(payload) - set(MISSION_FIELDS))
    if unknown:
        raise MissionRefused(
            f"a mission declares {list(MISSION_FIELDS)}; unknown field(s) "
            f"{unknown}")
    missing = sorted(f for f in REQUIRED_FIELDS if f not in payload)
    if missing:
        raise MissionRefused(f"a mission is missing required field(s) {missing}")

    ok, why = author_allowed(payload["author"], allowlist)
    if not ok:
        raise MissionRefused(why)
    ok, why = check_epoch(payload["epoch"], now=reader)
    if not ok:
        raise MissionRefused(why)

    raw_action = payload["action"]
    try:
        action = vocabulary.resolve(raw_action)
    except VocabularyError as exc:
        raise MissionRefused(str(exc)) from None

    if not isinstance(payload["params"], dict):
        raise MissionRefused(
            f"a mission's params must be a mapping, got "
            f"{type(payload['params']).__name__}")
    try:
        params = action.check_params(payload["params"])
    except VocabularyError as exc:
        raise MissionRefused(str(exc)) from None

    if action.requires_human_confirmation:
        for field in ("approval", "fingerprint", "target"):
            if field not in payload:
                raise MissionRefused(
                    f"action {action.name!r} is irreversible: the mission must "
                    f"carry {field!r} so the approval can be bound to it")

    mission = {"schema": MISSION_SCHEMA, "id": str(payload["id"]),
               "author": _checked_author(payload["author"]),
               "action": action.name, "params": params,
               "epoch": dict(payload["epoch"])}
    for field in ("approval", "fingerprint", "note", "target"):
        if field in payload:
            mission[field] = payload[field]
    return mission


def log_refusal(root, reason, *, mission_id=None, author=None, clock=None):
    """Append one refusal to the mission log; return the record written.

    A refusal that is not logged is a refusal nobody can audit, so this is part
    of the refusal path rather than an optional convenience. The record carries
    the reason verbatim and never a payload, so a hostile mission cannot get
    its own text into a log this lane later reads as trusted.
    """
    now = (clock or time.time)()
    record = {"schema": "mission-log@1", "event": "mission_refused",
              "ts": float(now), "reason": str(reason)}
    if mission_id is not None:
        record["mission_id"] = str(mission_id)
    if author is not None:
        record["author"] = str(author)
    path = os.path.join(os.path.abspath(root), "missions.log.jsonl")
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return record
