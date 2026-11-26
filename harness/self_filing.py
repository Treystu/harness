"""RSI Build 3 - the self-filing transport (plan section 6).

The loop writes its own work packages and epoch receipts to the repo tracker
under its seat tag and the epoch SHA, using a configured tracker issue as the
bus (the plan's named fallback: one issue carrying package records as comments).
#483's mission transport lives in the driving lane; when it is the available
transport this module's shape is unchanged, only the poster differs.

Three properties are enforced here rather than trusted to the loop:

- ATTRIBUTION. Every body must carry ``seat:`` and ``epoch_sha:`` lines; a
  filing without them is refused before it is posted, because an unattributed
  filing cannot be traced to the epoch that produced it.
- APPEND-ONLY. The module has no edit, delete or close verb at all, and the
  transport refuses any operation outside create-issue / create-comment / read.
  The loop never rewrites another seat's filings.
- READ-BACK. A filing is filed only when the tracker returns exactly the body
  that was sent; a mismatch is an error, not a warning.

Closure follows plan section 11: the loop may close only an item it opened, and
only with a closure class it can actually produce. Operator-held items are named
and never closed by the loop. Filings are evidence: a filed package enters the
roadmap through the standing intake, never by the loop ordering its own work.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .epoch_workspace import validate_head_sha
from .errors import HarnessError
from .osal import run as _osal_run, write_text as _write_text

SEAT_TAG = "rsi-epoch"
DEFAULT_LEDGER = "tmp/rsi-epochs/self-filing-ledger.json"

PACKAGE_CLASSES = ("defect", "verification", "judgment", "research")

# Plan section 11: an item closes only as one of these.
CLOSURE_CLASSES = ("merged_fix", "measured_result", "disposition", "operator_hold")

# The only tracker operations this transport performs. Everything else -
# editing, deleting, closing, labelling another seat's item - is refused here.
ALLOWED_OPERATIONS = ("issue_create", "comment_create", "read")
REFUSED_OPERATIONS = ("issue_edit", "comment_edit", "issue_delete",
                      "comment_delete", "issue_close", "label_add")

Runner = Callable[[Sequence[str], Optional[str], Optional[str]], Any]


def _default_run(argv: Sequence[str], cwd: Optional[str] = None,
                 input_text: Optional[str] = None):
    return _osal_run(list(argv), cwd=cwd, input_text=input_text)


def _result_text(result: Any) -> str:
    text = getattr(result, "combined", None)
    if text is None:
        text = str(getattr(result, "stdout", "") or "") + str(
            getattr(result, "stderr", "") or "")
    return text.strip()


def _json(result: Any, what: str) -> Any:
    code = getattr(result, "returncode", 1)
    if code != 0:
        raise HarnessError(f"{what} failed (exit {code}): {_result_text(result)}")
    raw = getattr(result, "stdout", "") or ""
    try:
        return json.loads(raw)
    except ValueError:
        raise HarnessError(f"{what} returned no JSON: {raw.strip()[:200]!r}") from None


def seat_lines(seat: str, epoch_sha: str) -> str:
    return f"seat: {seat}\nepoch_sha: {epoch_sha}\n"


def assert_attributed(body: str, seat: str, epoch_sha: str) -> str:
    """Refuse a filing that cannot be traced to its seat and epoch."""
    if not seat:
        raise HarnessError("a filing needs a seat tag")
    if not epoch_sha:
        raise HarnessError("a filing needs the epoch SHA")
    require_line = f"seat: {seat}"
    if require_line not in body.splitlines():
        raise HarnessError(f"a filing must carry the line {require_line!r}")
    if f"epoch_sha: {epoch_sha}" not in body.splitlines():
        raise HarnessError(f"a filing must carry the line 'epoch_sha: {epoch_sha}'")
    return body


def _quoted(evidence: Sequence[str]) -> str:
    lines = [line for line in evidence if str(line).strip()]
    if not lines:
        raise HarnessError(
            "a package must quote the census evidence that produced it")
    return "\n".join("> " + str(line).strip() for line in lines)


def render_package(package: Mapping[str, Any], *, seat: str = SEAT_TAG,
                   epoch: str = "", epoch_sha: str = "") -> str:
    """Render one typed work package as a bus comment."""
    if not isinstance(package, Mapping):
        raise HarnessError("a package must be a mapping")
    epoch_sha = validate_head_sha(epoch_sha)
    for key in ("id", "title", "class", "bar", "evidence"):
        if key not in package:
            raise HarnessError(f"a package needs {key}")
    kind = str(package["class"]).strip()
    if kind not in PACKAGE_CLASSES:
        raise HarnessError(
            f"package class {kind!r} is not one of {', '.join(PACKAGE_CLASSES)}")
    title = str(package["title"]).strip()
    if not title:
        raise HarnessError("a package needs a title")
    body = [
        f"### PACKAGE {str(package['id']).strip()} - {kind}",
        "",
        seat_lines(seat, epoch_sha).rstrip(),
    ]
    if epoch:
        body.insert(3, f"epoch: {epoch}")
    body += [
        "",
        f"**Bar:** {str(package['bar']).strip()}",
        f"**Class:** {kind}",
        "",
        f"**Gap:** {title}",
        "",
        "**Census evidence (quoted):**",
        _quoted([str(item) for item in package["evidence"]]),
        "",
        "Filed as evidence: this package enters the roadmap through the standing",
        "intake, never by the loop ordering its own work (plan section 6).",
    ]
    return "\n".join(body) + "\n"


def render_receipt(receipt: Mapping[str, Any], *, seat: str = SEAT_TAG,
                   epoch: str = "") -> str:
    """Render one epoch receipt as a bus comment."""
    if not isinstance(receipt, Mapping):
        raise HarnessError("a receipt must be a mapping")
    for key in ("epoch_sha", "bars", "rail"):
        if key not in receipt:
            raise HarnessError(f"a receipt needs {key}")
    epoch_sha = validate_head_sha(str(receipt["epoch_sha"]))
    bars = receipt["bars"]
    if not isinstance(bars, Mapping):
        raise HarnessError("receipt.bars must be a mapping")
    total = int(bars.get("total", 0) or 0)
    passed = int(bars.get("passed", 0) or 0)
    if total < 0 or passed < 0 or passed > total:
        raise HarnessError(
            f"receipt.bars cannot be {passed} of {total}: bars are reported "
            "passed-against-full-total")
    body = [f"### RECEIPT {epoch or receipt.get('epoch', '')}".rstrip(), "",
            seat_lines(seat, epoch_sha).rstrip(), ""]
    body.append(f"- bars: {passed}/{total} (credit {bars.get('credit', 0)})")
    red = bars.get("red") or []
    body.append("- red: " + (", ".join(str(item) for item in red) or "none"))
    body.append(f"- rail: {str(receipt['rail']).strip() or 'unknown'}")
    for key in ("packages_opened", "packages_closed"):
        if key in receipt:
            body.append(f"- {key.replace('_', ' ')}: {receipt[key]}")
    if "spend_usd" in receipt:
        body.append(f"- spend: ${float(receipt['spend_usd']):.2f}")
    body.append("- escalations: " + (str(receipt.get("escalations") or "none")))
    return "\n".join(body) + "\n"


@dataclass
class Filing:
    """One posted tracker record, and whether the read-back matched."""

    kind: str
    key: str
    body: str
    url: str = ""
    number: int = 0
    comment_id: int = 0
    verified: bool = False

    def record(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "url": self.url,
            "number": self.number,
            "comment_id": self.comment_id,
            "verified": self.verified,
        }


class Transport:
    """The three operations the loop may perform, and nothing else."""

    def call(self, operation: str, **kwargs) -> Any:
        if operation in REFUSED_OPERATIONS:
            raise HarnessError(
                f"the self-filing transport is append-only: {operation} is refused")
        if operation not in ALLOWED_OPERATIONS:
            raise HarnessError(f"unknown transport operation {operation!r}")
        return self._perform(operation, **kwargs)

    def _perform(self, operation: str, **kwargs) -> Any:
        raise NotImplementedError


class GhTransport(Transport):
    """Files through the repo API with ``gh api --input -``.

    ``gh`` is used deliberately: it already holds the clone's scoped credential,
    so no token is read, printed or passed through this module.
    """

    def __init__(self, runner: Optional[Runner] = None):
        self._run = runner or _default_run

    def _api(self, method: str, path: str, payload: Optional[Mapping] = None) -> Any:
        argv = ["gh", "api", "-X", method, path]
        text = None
        if payload is not None:
            argv += ["--input", "-"]
            text = json.dumps(dict(payload))
        return _json(self._run(argv, None, text), f"gh api {method} {path}")

    def _perform(self, operation: str, **kwargs) -> Any:
        if operation == "issue_create":
            return self._api("POST", f"repos/{kwargs['repo']}/issues",
                             {"title": kwargs["title"], "body": kwargs["body"]})
        if operation == "comment_create":
            return self._api("POST", f"repos/{kwargs['repo']}/issues/"
                                     f"{kwargs['number']}/comments",
                             {"body": kwargs["body"]})
        if operation == "read":
            return self._api("GET", kwargs["path"])
        raise HarnessError(f"unknown transport operation {operation!r}")


def verify_readback(transport: Transport, repo: str, filing: Filing) -> Filing:
    """The tracker must return exactly the body that was sent."""
    if not filing.url and not filing.comment_id:
        raise HarnessError("there is nothing to read back: the filing has no target")
    if filing.comment_id:
        row = transport.call("read", path=f"repos/{repo}/issues/comments/"
                                          f"{filing.comment_id}")
    else:
        row = transport.call("read", path=f"repos/{repo}/issues/{filing.number}")
    if not isinstance(row, Mapping):
        raise HarnessError("read-back returned no record")
    posted = str(row.get("body", ""))
    if posted != filing.body:
        raise HarnessError(
            f"read-back mismatch for {filing.key}: the tracker returned a "
            "different body than was sent")
    filing.verified = True
    return filing


def file_package(transport: Transport, repo: str, package: Mapping[str, Any], *,
                 epoch: str, epoch_sha: str, seat: str = SEAT_TAG,
                 bus: Optional[int] = None) -> Filing:
    """File one package: an issue when no bus is configured, else a bus comment."""
    body = render_package(package, seat=seat, epoch=epoch, epoch_sha=epoch_sha)
    assert_attributed(body, seat, epoch_sha)
    if bus:
        row = transport.call("comment_create", repo=repo, number=int(bus), body=body)
        filing = Filing(kind="package", key=str(package["id"]), body=body,
                        comment_id=int(row.get("id") or 0),
                        url=str(row.get("html_url") or ""))
    else:
        title = f"[{seat}] {str(package['class'])} {package['id']}: " \
                f"{str(package['title']).strip()}"
        row = transport.call("issue_create", repo=repo, title=title, body=body)
        filing = Filing(kind="package", key=str(package["id"]), body=body,
                        number=int(row.get("number") or 0),
                        url=str(row.get("html_url") or ""))
    return verify_readback(transport, repo, filing)


def file_receipt(transport: Transport, repo: str, receipt: Mapping[str, Any], *,
                 epoch: str, bus: int, seat: str = SEAT_TAG) -> Filing:
    """Receipts ride the configured bus issue as comments."""
    body = render_receipt(receipt, seat=seat, epoch=epoch)
    assert_attributed(body, seat, str(receipt["epoch_sha"]))
    row = transport.call("comment_create", repo=repo, number=int(bus), body=body)
    filing = Filing(kind="receipt", key=epoch, body=body,
                    comment_id=int(row.get("id") or 0),
                    url=str(row.get("html_url") or ""))
    return verify_readback(transport, repo, filing)


class LoopLedger:
    """The items the loop opened. Closure is checked against this, not memory."""

    def __init__(self, path: str = DEFAULT_LEDGER):
        self.path = Path(path)
        self.items: List[Dict[str, Any]] = []
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                raise HarnessError(
                    f"the self-filing ledger {path} is not JSON") from None
            self.items = list(data.get("items") or [])

    def record(self, filing: Filing, *, epoch: str) -> Filing:
        entry = dict(filing.record(), epoch=epoch, seat=SEAT_TAG)
        self.items.append(entry)
        return filing

    def owns(self, key: str) -> bool:
        return any(str(item.get("key")) == str(key) for item in self.items)

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(self.path, json.dumps({"items": self.items}, indent=2) + "\n")
        return self.path


def can_close(ledger: LoopLedger, key: str, evidence_class: str) -> Dict[str, Any]:
    """Plan section 11: only an item the loop opened, with evidence it can give."""
    if evidence_class not in CLOSURE_CLASSES:
        return {"allowed": False,
                "reason": f"{evidence_class!r} is not a closure class"}
    if not ledger.owns(key):
        return {"allowed": False,
                "reason": "the loop did not open this item"}
    if evidence_class == "operator_hold":
        return {"allowed": False,
                "reason": "operator-held items are named, never closed by the loop"}
    return {"allowed": True, "reason": ""}


def file_test_epoch(transport: Transport, repo: str, *, epoch: str,
                    epoch_sha: str, bus: int, package: Mapping[str, Any],
                    receipt: Mapping[str, Any], ledger_path: str = DEFAULT_LEDGER,
                    seat: str = SEAT_TAG) -> Dict[str, Any]:
    """The Build 3 acceptance act: one package and one receipt, read back.

    Appending to the bus, verifying both filings and recording them in the loop
    ledger is the whole act; there is no edit, delete or close step to forget.
    """
    sha = validate_head_sha(epoch_sha)
    ledger = LoopLedger(ledger_path)
    package_filing = file_package(transport, repo, package, epoch=epoch,
                                  epoch_sha=sha, seat=seat, bus=bus)
    ledger.record(package_filing, epoch=epoch)
    receipt_filing = file_receipt(transport, repo, dict(receipt, epoch_sha=sha),
                                  epoch=epoch, bus=bus, seat=seat)
    ledger.record(receipt_filing, epoch=epoch)
    saved = ledger.save()
    return {
        "epoch": epoch,
        "epoch_sha": sha,
        "seat": seat,
        "bus": int(bus),
        "package": package_filing.record(),
        "receipt": receipt_filing.record(),
        "verified": bool(package_filing.verified and receipt_filing.verified),
        "ledger": str(saved),
    }
