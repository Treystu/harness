"""#483 B3 -- the local mission executor: poll, claim, read back, receipt.

The security half of this issue (:mod:`driver_core.mission`) has been on main
since #551. What was missing is the thing it guards: an executor that takes one
mission from a private inbox, proves it still says what was parsed, executes it
through the caller's action tier, and files a receipt -- with no human relaying
text between GitHub and the machine.

Design commitments, each one a refusal rather than a feature:

* **The inbox is private and declared.** A root carries a ``manifest.json``
  naming the repository it belongs to and asserting ``private: true``. The
  executor refuses to poll a root whose manifest is missing, public, or names
  another repository, because "missions live on the private ledger only" is not
  a convention that survives an operator pointing a flag at the wrong clone.
* **One file is one mission, at the top level.** No recursion, no symlinks, no
  real path outside the root, no oversized document. A tampered inbox stops the
  poll by name instead of being skipped, because a file that is not a mission
  file is evidence the root is wrong rather than noise to ignore.
* **The token is scoped and never printed.** :class:`MissionToken` carries
  capabilities (``read_missions``, ``write_receipts``) and a repository. A
  receipt cannot be filed by a read-only token, and neither ``repr`` nor the
  refusal text carries the secret -- only a short fingerprint for correlation.
* **A claim is a lease, not a promise.** GitHub has no writer lease, so the
  local store owns one: claim, heartbeat, finish. A second executor holding the
  same root is refused while a heartbeat is fresh, and may take over one that
  has gone silent.
* **Read-back before execution.** The mission is re-read from disk and compared
  field by field with what was parsed; below ``95`` the mission is parked and
  nothing runs. This is the #452 READY pattern: what executes must be what was
  reviewed, not what a file happened to contain a moment later.
* **File and continue.** A refused or failed mission is parked with a receipt;
  the next mission in the queue is still processed. One bad mission cannot stop
  the lane, and nothing is silently retried forever.

The transport is deliberately not implemented here. GitHub is a transport, and
a transport that cannot be exercised offline (no token, no private repo, no
network in the test harness) would be a second, unproven copy of these
guarantees. The caller supplies the action tier; the tests supply both halves.
"""

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import mission as missions
from .actions import DEFAULT_VOCABULARY

#: The inbox manifest's schema name.
INBOX_SCHEMA = "mission-inbox@1"

#: The receipt's schema name. Versioned like every other record here.
RECEIPT_SCHEMA = "mission-receipt@1"

#: The manifest file every private root must carry.
MANIFEST_FILE = "manifest.json"

#: The directory names inside one root. Declared, because an executor that
#: guessed at "inbox" or "new" would read a directory it was not shown.
MISSIONS_DIR = "missions"
RECEIPTS_DIR = "receipts"
ARCHIVE_DIR = "archive"
PARKED_DIR = "parked"

#: One mission file may not exceed this. A mission is a short instruction plus
#: its parameters; a megabyte is already far past any legitimate one.
MAX_MISSION_BYTES = 1 << 20

#: The read-back bar, in hundredths, from the issue: "per-field read-back of
#: placed missions at >=95/100 before Enter".
READ_BACK_THRESHOLD = 95.0

#: How long a claim is good for without a heartbeat, in seconds. Long enough
#: for one supervised step, short enough that a crashed executor is not a
#: permanent lock.
DEFAULT_LEASE_SECONDS = 60.0

#: What a token can be scoped to. Two capabilities, because the executor does
#: exactly two things to the ledger: reads missions and writes receipts.
CAPABILITIES = ("read_missions", "write_receipts")

#: Claim states. "claimed" is a live lease; "done" and "parked" are terminal,
#: which is what makes a mission single-use at the executor level.
CLAIMED = "claimed"
DONE = "done"
PARKED = "parked"

#: One mission id is a plain identifier, never a path fragment.
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class MissionToken:
    """A capability-scoped credential for one private ledger.

    The secret is held, never rendered. ``repr`` and ``str`` carry the
    repository, the capabilities and a short fingerprint -- enough to correlate
    two log lines, not enough to replay the credential in them.
    """

    def __init__(self, secret, *, capabilities, repo):
        if not isinstance(secret, str) or not secret:
            raise missions.MissionRefused(
                "a mission token needs a non-empty value")
        declared = tuple(capabilities or ())
        unknown = sorted(set(declared) - set(CAPABILITIES))
        if unknown:
            raise missions.MissionRefused(
                f"mission token declares unknown capabilit(ies) {unknown}; "
                f"declared capabilities are {list(CAPABILITIES)}")
        if not isinstance(repo, str) or not repo.strip():
            raise missions.MissionRefused(
                f"a mission token needs the repository it is scoped to, got "
                f"{repo!r}")
        self._secret = secret
        self.capabilities = declared
        self.repo = repo.strip()

    @property
    def fingerprint(self):
        """A short, stable digest of the secret, for correlating log lines."""
        return hashlib.sha256(self._secret.encode("utf-8")).hexdigest()[:16]

    def require(self, capability):
        """Refuse unless this token was scoped for ``capability``."""
        if capability not in self.capabilities:
            raise missions.MissionRefused(
                f"this mission token is not scoped for {capability!r}; "
                f"scoped: {list(self.capabilities)} (repo {self.repo!r}, "
                f"fp {self.fingerprint})")

    def __repr__(self):
        return (f"MissionToken(repo={self.repo!r}, "
                f"capabilities={list(self.capabilities)}, "
                f"fp={self.fingerprint})")

    __str__ = __repr__


def _atomic_write(path, record):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = f"{path}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_json(path, *, limit=MAX_MISSION_BYTES):
    size = os.path.getsize(path)
    if size > limit:
        raise missions.MissionRefused(
            f"{os.path.basename(path)} is {size} bytes; the inbox carries at "
            f"most {limit}")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except ValueError as exc:
        raise missions.MissionRefused(
            f"{os.path.basename(path)} is not valid JSON: {exc}") from None


class MissionInbox:
    """One private root: a manifest, a missions directory, receipts, archives."""

    def __init__(self, root, *, token):
        self.root = os.path.abspath(root)
        self.token = token
        self._manifest = self._read_manifest()

    def _read_manifest(self):
        path = os.path.join(self.root, MANIFEST_FILE)
        if not os.path.isfile(path):
            raise missions.MissionRefused(
                f"the mission root {self.root!r} carries no {MANIFEST_FILE}; "
                "refusing to poll a directory nobody declared")
        record = _read_json(path, limit=64 * 1024)
        if not isinstance(record, dict):
            raise missions.MissionRefused(
                f"{MANIFEST_FILE} must be a mapping, got "
                f"{type(record).__name__}")
        if record.get("schema") != INBOX_SCHEMA:
            raise missions.MissionRefused(
                f"{MANIFEST_FILE} declares schema {record.get('schema')!r}; "
                f"this executor reads {INBOX_SCHEMA}")
        if record.get("private") is not True:
            raise missions.MissionRefused(
                f"the mission root {self.root!r} is not declared private; "
                "missions are filed on a private ledger only, never a public "
                "repository")
        if record.get("repo") != self.token.repo:
            raise missions.MissionRefused(
                f"the mission root belongs to {record.get('repo')!r}, but the "
                f"token is scoped to {self.token.repo!r}; refusing to read "
                "another repository's missions")
        return record

    @property
    def manifest(self):
        return dict(self._manifest)

    def _directory(self, name):
        """One directory inside the declared root, refusing redirection.

        ``os.makedirs`` follows a pre-existing symlink, and the old read-side
        check only looked at the mission file itself, so a symlinked
        ``missions/`` made the executor read and remove files outside the
        declared root. The directory is validated here, once, because receipts
        and archives use the same helper (#683 finding 27).
        """
        path = os.path.join(self.root, name)
        os.makedirs(path, exist_ok=True)
        if os.path.islink(path):
            raise missions.MissionRefused(
                f"the inbox directory {name!r} is a symlink; the inbox reads "
                "and writes only inside its own root")
        if os.path.dirname(os.path.realpath(path)) != os.path.realpath(self.root):
            raise missions.MissionRefused(
                f"the inbox directory {name!r} resolves outside the root")
        return path

    def _mission_path(self, filename):
        """Resolve one top-level mission file, refusing every near miss."""
        if not isinstance(filename, str) or not filename.endswith(".json"):
            raise missions.MissionRefused(
                f"{filename!r} is not a mission file name")
        stem = filename[:-5]
        if not _ID.match(stem):
            raise missions.MissionRefused(
                f"mission file name {filename!r} is not a plain identifier")
        directory = self._directory(MISSIONS_DIR)
        path = os.path.join(directory, filename)
        if os.path.islink(path):
            raise missions.MissionRefused(
                f"mission file {filename!r} is a symlink; the inbox reads only "
                "files it can name inside its own root")
        real = os.path.realpath(path)
        if os.path.dirname(real) != os.path.realpath(directory):
            raise missions.MissionRefused(
                f"mission file {filename!r} resolves outside the inbox")
        return path

    def pending(self):
        """The mission file names waiting to be processed, oldest name first."""
        self.token.require("read_missions")
        directory = self._directory(MISSIONS_DIR)
        names = []
        for name in sorted(os.listdir(directory)):
            if name.startswith("."):
                continue
            if not name.endswith(".json"):
                raise missions.MissionRefused(
                    f"the inbox holds {name!r}, which is not a mission file; "
                    "refusing to guess which files are missions")
            self._mission_path(name)
            names.append(name)
        return names

    def read(self, filename):
        """Read one mission payload, by name, from the top level."""
        self.token.require("read_missions")
        payload = _read_json(self._mission_path(filename))
        if not isinstance(payload, dict):
            raise missions.MissionRefused(
                f"mission file {filename!r} is a "
                f"{type(payload).__name__}, not a mission mapping")
        return payload

    def _move(self, filename, directory_name):
        source = self._mission_path(filename)
        target = os.path.join(self._directory(directory_name), filename)
        os.replace(source, target)
        return target

    def archive(self, filename):
        """Retire a completed mission from the queue."""
        return self._move(filename, ARCHIVE_DIR)

    def park(self, filename):
        """Set a refused or failed mission aside; the queue continues."""
        return self._move(filename, PARKED_DIR)

    def write_receipt(self, record):
        """File one receipt atomically. Requires the write capability."""
        self.token.require("write_receipts")
        mission_id = record.get("mission_id")
        if not isinstance(mission_id, str) or not _ID.match(mission_id):
            raise missions.MissionRefused(
                f"a receipt needs a plain mission id, got {mission_id!r}")
        path = os.path.join(self._directory(RECEIPTS_DIR),
                            f"{mission_id}.json")
        _atomic_write(path, record)
        return path


class MissionClaimStore:
    """The local writer lease: claim, heartbeat, finish, once.

    This is not a GitHub lease and does not pretend to be one. Two executors
    that share a root share the lease; two that do not are two writers, and the
    only honest protection there is that the inbox is one directory. Stated
    because a claim store that promised more would be the exact kind of
    invisible assumption this package refuses.
    """

    def __init__(self, path):
        self.path = os.path.abspath(os.fspath(path))

    @contextmanager
    def _transaction(self):
        connection = None
        committed = False
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5)
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS mission_claims ("
                "mission_id TEXT PRIMARY KEY, "
                "epoch_issued_at REAL, "
                "owner TEXT NOT NULL, "
                "claimed_at REAL NOT NULL, "
                "heartbeat_at REAL NOT NULL, "
                "finished_at REAL, "
                "state TEXT NOT NULL CHECK(state IN "
                "('claimed', 'done', 'parked')))")
            yield connection
            connection.commit()
            committed = True
        except (OSError, sqlite3.Error):
            raise missions.MissionRefused(
                "the mission claim store is unavailable") from None
        finally:
            if connection is not None:
                if not committed:
                    connection.rollback()
                connection.close()

    def _row(self, connection, mission_id):
        return connection.execute(
            "SELECT epoch_issued_at, owner, heartbeat_at, state "
            "FROM mission_claims WHERE mission_id = ?",
            (mission_id,)).fetchone()

    def claim(self, mission_id, *, epoch_issued_at, owner,
              lease=DEFAULT_LEASE_SECONDS, clock=None):
        """``(True, "")`` when this executor now holds the mission."""
        now = (clock or time.time)()
        if not isinstance(mission_id, str) or not _ID.match(mission_id):
            return False, f"mission id {mission_id!r} is not a plain identifier"
        if not isinstance(owner, str) or not owner.strip():
            return False, "a claim needs a named owner"
        with self._transaction() as connection:
            row = self._row(connection, mission_id)
            if row is not None:
                epoch, holder, heartbeat_at, state = row
                if state == DONE:
                    return False, (f"mission {mission_id!r} is already done; "
                                   "a completed mission cannot execute twice")
                if state == PARKED:
                    return False, (f"mission {mission_id!r} is parked; it was "
                                   "refused or failed and is not retried here")
                if epoch != epoch_issued_at:
                    return False, (f"mission {mission_id!r} is claimed under a "
                                   "different epoch; the mission was refiled "
                                   "and this copy is stale")
                age = now - float(heartbeat_at)
                if holder != owner and age < lease:
                    return False, (f"mission {mission_id!r} is held by "
                                   f"{holder!r} with a heartbeat {age:.1f}s "
                                   f"old; refusing a second writer")
                connection.execute(
                    "UPDATE mission_claims SET owner = ?, heartbeat_at = ? "
                    "WHERE mission_id = ?", (owner, now, mission_id))
                return True, ""
            connection.execute(
                "INSERT INTO mission_claims (mission_id, epoch_issued_at, "
                "owner, claimed_at, heartbeat_at, state) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (mission_id, float(epoch_issued_at)
                 if isinstance(epoch_issued_at, (int, float)) else None,
                 owner, now, now, CLAIMED))
            return True, ""

    def heartbeat(self, mission_id, owner, *, clock=None):
        """Extend the lease. Refuses when this executor no longer holds it."""
        now = (clock or time.time)()
        with self._transaction() as connection:
            row = self._row(connection, mission_id)
            if row is None or row[3] != CLAIMED:
                return False, f"mission {mission_id!r} is not actively claimed"
            if row[1] != owner:
                return False, (f"mission {mission_id!r} is held by {row[1]!r}, "
                               f"not {owner!r}")
            connection.execute(
                "UPDATE mission_claims SET heartbeat_at = ? "
                "WHERE mission_id = ?", (now, mission_id))
            return True, ""

    def finish(self, mission_id, owner, *, state, clock=None):
        """Close one claim as ``done`` or ``parked``. Only the holder may."""
        if state not in (DONE, PARKED):
            return False, f"a claim cannot finish as {state!r}"
        now = (clock or time.time)()
        with self._transaction() as connection:
            row = self._row(connection, mission_id)
            if row is None:
                return False, f"mission {mission_id!r} was never claimed"
            if row[1] != owner:
                return False, (f"mission {mission_id!r} is held by {row[1]!r}, "
                               f"not {owner!r}")
            connection.execute(
                "UPDATE mission_claims SET state = ?, finished_at = ? "
                "WHERE mission_id = ?", (state, now, mission_id))
            return True, ""

    def state(self, mission_id):
        with self._transaction() as connection:
            row = self._row(connection, mission_id)
            return None if row is None else row[3]


def _flatten(record, prefix=""):
    fields = {}
    for key in sorted(record):
        value = record[key]
        if isinstance(value, dict):
            fields.update(_flatten(value, f"{prefix}{key}."))
        else:
            fields[f"{prefix}{key}"] = value
    return fields


def read_back(expected, observed):
    """``(score, mismatched_fields)``: what was parsed versus what is on disk.

    Field by field, flattened, because "the mission matches" is not a reviewable
    claim: an operator needs to know *which* field moved. A field present on
    one side and absent on the other counts as a mismatch, so a deleted key is
    not a silent pass.
    """
    if not isinstance(expected, dict) or not isinstance(observed, dict):
        raise missions.MissionRefused(
            "read-back needs two mappings; got "
            f"{type(expected).__name__} and {type(observed).__name__}")
    left, right = _flatten(expected), _flatten(observed)
    keys = sorted(set(left) | set(right))
    if not keys:
        return 100.0, []
    mismatches = [key for key in keys if left.get(key) != right.get(key)]
    score = (len(keys) - len(mismatches)) / len(keys) * 100.0
    return score, mismatches


class MissionExecutor:
    """One executor: poll, claim, read back, execute, file, continue."""

    def __init__(self, inbox, claims, *, allowlist, execute, owner,
                 vocabulary=None, clock=None, lease=DEFAULT_LEASE_SECONDS,
                 threshold=READ_BACK_THRESHOLD):
        self.inbox = inbox
        self.claims = claims
        if not callable(execute):
            raise missions.MissionRefused(
                "a mission executor needs a callable action tier")
        self.execute = execute
        self.allowlist = tuple(allowlist or ())
        self.owner = str(owner or "").strip()
        if not self.owner:
            raise missions.MissionRefused(
                "a mission executor needs a named owner for its claims")
        self.vocabulary = vocabulary or DEFAULT_VOCABULARY
        self.clock = clock or time.time
        self.lease = float(lease)
        self.threshold = float(threshold)

    def _receipt(self, mission, *, state, detail, evidence=None, started=None,
                 read_back_record=None):
        now = self.clock()
        return {
            "schema": RECEIPT_SCHEMA,
            "mission_id": mission.get("id") if isinstance(mission, dict) else None,
            "author": mission.get("author") if isinstance(mission, dict) else None,
            "action": mission.get("action") if isinstance(mission, dict) else None,
            "state": state,
            "detail": str(detail),
            "evidence": dict(evidence or {}),
            "owner": self.owner,
            "started_at": float(started if started is not None else now),
            "finished_at": float(now),
        }

    def _finish(self, mission_id, *, state, detail):
        ok, why = self.claims.finish(mission_id, self.owner, state=state,
                                     clock=self.clock)
        if not ok:
            raise missions.MissionRefused(
                f"the claim for {mission_id!r} could not be closed: {why}")

    def process_next(self):
        """Process the oldest mission, or return ``None`` when the queue is empty.

        Every refusal path files a receipt, parks the file and returns; none of
        them raises out of here, because one bad mission must not stop the
        queue.         The two exceptions are an unreadable inbox (the root is wrong,
        which is not a per-mission condition) and a claim that cannot be
        closed (the store is unavailable, which is not either). A token that
        cannot file receipts is refused up front for the same reason: executing
        first would leave the claim open and the action replayable (#683
        finding 25).
        """
        self.inbox.token.require("read_missions")
        self.inbox.token.require("write_receipts")
        pending = self.inbox.pending()
        if not pending:
            return None
        filename = pending[0]
        started = self.clock()
        try:
            payload = self.inbox.read(filename)
        except missions.MissionRefused as exc:
            # A malformed, oversized or non-mapping payload used to raise out
            # of process_next before the refusal handler, so the queue stuck
            # on the same file instead of parking it and moving on (#683
            # finding 26). The validated file name is the fallback identity.
            return self._refuse(filename, {}, filename[:-5], str(exc),
                                started=started)
        raw_id = payload.get("id")
        mission_id = raw_id if isinstance(raw_id, str) else filename[:-5]

        try:
            mission = missions.parse_mission(
                payload, allowlist=self.allowlist,
                vocabulary=self.vocabulary, now=self.clock())
        except missions.MissionRefused as exc:
            return self._refuse(filename, payload, mission_id, str(exc),
                                started=started)

        epoch = mission["epoch"].get("issued_at")
        held, why = self.claims.claim(mission["id"],
                                      epoch_issued_at=epoch, owner=self.owner,
                                      lease=self.lease, clock=self.clock)
        if not held:
            if "held by" in why:
                # Another live executor owns it. Leave the file alone; the
                # next poll asks again, and the other writer will retire it.
                return self._receipt(mission, state="waiting", detail=why,
                                     started=started)
            return self._refuse(filename, mission, mission["id"], why,
                                started=started, claimed=False)

        # Read back what is actually on disk now. The mission that executes
        # must be the mission that was parsed and reviewed, not whatever the
        # file contains after a refile.
        try:
            observed = self.inbox.read(filename)
            fresh = missions.parse_mission(
                observed, allowlist=self.allowlist,
                vocabulary=self.vocabulary, now=self.clock())
            score, mismatched = read_back(mission, fresh)
        except missions.MissionRefused as exc:
            return self._park(filename, mission, str(exc), started=started)

        if score < self.threshold:
            return self._park(
                filename, mission,
                f"read-back scored {score:.2f}/100, below the "
                f"{self.threshold:g} bar; mismatched fields: {mismatched}",
                started=started,
                read_back_record={"score": score, "mismatched": mismatched})

        ok, why = self.claims.heartbeat(mission["id"], self.owner,
                                        clock=self.clock)
        if not ok:
            return self._park(filename, mission,
                              f"the claim was lost before execution: {why}",
                              started=started)

        # A heartbeat before the action is not a lease for the action: an
        # action longer than the lease became stealable and a second executor
        # could run the same mission. Renew at a third of the lease for as long
        # as the action runs, and stop before any receipt is written (#683
        # finding 24). Short actions still take the single-heartbeat path.
        stop = threading.Event()
        lost = []
        renewer = threading.Thread(
            target=self._renew_claim,
            args=(mission["id"], stop, lost),
            name="mission-lease", daemon=True)
        renewer.start()
        try:
            evidence = self.execute(mission)
        except Exception as exc:  # a failed action parks; the queue moves on
            stop.set()
            renewer.join(timeout=max(1.0, self.lease))
            return self._park(filename, mission,
                              f"the action tier raised: {exc}",
                              started=started)
        stop.set()
        renewer.join(timeout=max(1.0, self.lease))
        if lost:
            # The claim moved while the action ran; the new holder owns the
            # mission now, so this executor files the observed loss instead of
            # claiming a done receipt it cannot close.
            reason = f"the claim was lost during execution: {lost[0]}"
            receipt = self._receipt(mission, state=PARKED, detail=reason,
                                    started=started)
            self.inbox.write_receipt(receipt)
            self.inbox.park(filename)
            return receipt

        receipt = self._receipt(
            mission, state=DONE,
            detail="mission executed and receipted",
            evidence=evidence if isinstance(evidence, dict) else
            {"result": evidence},
            started=started,
            read_back_record={"score": score, "mismatched": mismatched})
        self.inbox.write_receipt(receipt)
        self._finish(mission["id"], state=DONE, detail="executed")
        self.inbox.archive(filename)
        return receipt

    def _renew_claim(self, mission_id, stop, lost):
        """Heartbeat at a third of the lease until the action finishes."""
        interval = max(0.05, self.lease / 3.0)
        while not stop.wait(interval):
            try:
                held, why = self.claims.heartbeat(mission_id, self.owner,
                                                 clock=self.clock)
            except missions.MissionRefused as exc:
                lost.append(str(exc))
                return
            if not held:
                lost.append(why)
                return

    def _refuse(self, filename, payload, mission_id, reason, *, started,
                claimed=False):
        """Log, receipt and park a mission the parser refused."""
        missions.log_refusal(
            self.inbox.root, reason, mission_id=mission_id,
            author=payload.get("author") if isinstance(payload, dict) else None,
            clock=self.clock)
        receipt = self._receipt(
            {"id": mission_id,
             "author": payload.get("author") if isinstance(payload, dict)
             else None,
             "action": payload.get("action") if isinstance(payload, dict)
             else None},
            state=PARKED, detail=reason, started=started)
        self.inbox.write_receipt(receipt)
        if claimed:
            self._finish(mission_id, state=PARKED, detail=reason)
        self.inbox.park(filename)
        return receipt

    def _park(self, filename, mission, reason, *, started,
              read_back_record=None):
        """Publish a claim as parked, file its receipt, and move the file."""
        receipt = self._receipt(
            mission, state=PARKED, detail=reason, started=started,
            evidence={"read_back": read_back_record}
            if read_back_record else {})
        self.inbox.write_receipt(receipt)
        self._finish(mission["id"], state=PARKED, detail=reason)
        self.inbox.park(filename)
        return receipt

    def run(self, max_missions=10):
        """Drain up to ``max_missions``; a parked mission never stops the loop."""
        receipts = []
        for _ in range(max(0, int(max_missions))):
            outcome = self.process_next()
            if outcome is None:
                break
            receipts.append(outcome)
            if outcome.get("state") == "waiting":
                break
        return receipts
