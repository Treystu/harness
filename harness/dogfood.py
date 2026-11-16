"""#277 -- the structured dogfood round: four surfaces, one filed report.

Issue #277 exists because round 1 produced a single find and no record: no
mission report anywhere, and the GUI, MCP and website surfaces have no evidence
of ever being exercised. The acceptance it sets is a report that cannot be
written the way round 1 failed:

* all four surfaces present -- CLI, GUI, MCP, website -- with a per-surface
  record of what was exercised, what was found, and what was fixed or filed;
* **silence does not count**: every item carries a note, and "no findings" must
  be said explicitly rather than left blank;
* every defect is either fixed in the round or filed as its own issue with a
  severity, and the report closes with a one-line verdict per surface;
* a surface that was **not** exercised says so with its reason, and that reason
  is a blocker in the verdict rather than a clean line.

This module is the checklist engine and the renderer. It decides nothing about
the product; it makes an incomplete report impossible to file by accident, which
is the failure #277 is about.
"""
import json

#: The four surfaces the report must cover, in the issue's own order.
SURFACES = ("cli", "gui", "mcp", "website")

#: The checklist shape per surface, quoted from #277 in one line each.
CHECKLIST = {
    "cli": "every command incl. help text, error paths, exit codes on bad input",
    "gui": "launch, every pane, every primary interaction; dead controls and stale state",
    "mcp": "every tool/resource via a real MCP client; each description vs its behaviour",
    "website": "every page loads; content matches the current product (commands, flags, versions)",
}

#: What happened to one checklist item.
STATUSES = ("exercised", "finding", "not_exercised")

#: Severity bands for a filed defect.
SEVERITIES = ("low", "medium", "high")

#: The one phrase a clean surface must contain, so silence cannot pass for it.
NO_FINDINGS = "no findings"


class DogfoodError(ValueError):
    """A round pack that would file a report #277 says cannot be filed."""


def _checked_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise DogfoodError(f"{field} must be a non-empty string, got {value!r}")
    return value.strip()


def check_finding(finding):
    """One defect: what it is, how bad, and where it went.

    A finding with no disposition is the exact round-1 failure -- something was
    seen and nothing happened -- so "issue" or "fixed" is required, and an issue
    reference must be a number (the acceptance asks for issue numbers).
    """
    if not isinstance(finding, dict):
        raise DogfoodError(
            f"a finding must be a mapping, got {type(finding).__name__}")
    text = _checked_text(finding.get("text"), "finding text")
    severity = finding.get("severity")
    if severity not in SEVERITIES:
        raise DogfoodError(
            f"a finding's severity must be one of {list(SEVERITIES)}, got {severity!r}")
    has_issue = "issue" in finding and finding["issue"] is not None
    fixed = finding.get("fixed")
    if has_issue and fixed:
        raise DogfoodError(
            "a finding is either filed or fixed in the round, not both")
    if not has_issue and not fixed:
        raise DogfoodError(
            f"finding {text[:50]!r} has no disposition: file it as an issue with "
            "a severity note, or mark it fixed in this round")
    record = {"text": text, "severity": severity}
    if has_issue:
        issue = finding["issue"]
        if isinstance(issue, bool) or not isinstance(issue, int) or issue <= 0:
            raise DogfoodError(
                f"a filed finding needs an issue number, got {issue!r}")
        record["issue"] = issue
    else:
        record["fixed"] = _checked_text(fixed, "finding fixed")
    return record


def check_item(item):
    """One checklist item: its status, its note, and (if any) its finding."""
    if not isinstance(item, dict):
        raise DogfoodError(f"a checklist item must be a mapping, got {type(item).__name__}")
    name = _checked_text(item.get("item"), "item name")
    status = item.get("status")
    if status not in STATUSES:
        raise DogfoodError(
            f"item {name!r} status must be one of {list(STATUSES)}, got {status!r}")
    note = _checked_text(item.get("note"), f"item {name!r} note")
    record = {"item": name, "status": status, "note": note}
    if status == "finding":
        record["finding"] = check_finding(item.get("finding"))
    elif item.get("finding") is not None:
        raise DogfoodError(
            f"item {name!r} carries a finding but its status is {status!r}")
    if status == "not_exercised" and not record["note"]:
        raise DogfoodError(f"item {name!r} must say why it was not exercised")
    return record


def surface_verdict(surface, items):
    """``(verdict_line, blockers)`` for one surface, from its checked items.

    The acceptance allows exactly two clean outcomes -- "clean", or "issues
    filed (numbers)" -- and one explicit third: not exercised, with the reason.
    Anything else is a blocker, because a surface with no record is the round-1
    failure this issue exists to prevent.
    """
    if surface not in SURFACES:
        raise DogfoodError(f"{surface!r} is not one of {list(SURFACES)}")
    if not items:
        raise DogfoodError(f"surface {surface!r} has no checklist items")
    blocked = [i for i in items if i["status"] == "not_exercised"]
    findings = [i["finding"] for i in items if i["status"] == "finding"]
    exercised = [i for i in items if i["status"] == "exercised"]
    if blocked:
        reasons = "; ".join(f"{i['item']}: {i['note']}" for i in blocked)
        return (f"not exercised ({len(blocked)} of {len(items)} items) - {reasons}",
                [i["item"] for i in blocked])
    if findings:
        filed = sorted({f["issue"] for f in findings if "issue" in f})
        fixed = [f for f in findings if "fixed" in f]
        if filed:
            return (f"issues filed ({', '.join(f'#{n}' for n in filed)})", [])
        return (f"fixed in round ({len(fixed)} finding(s))", [])
    if not exercised:
        raise DogfoodError(
            f"surface {surface!r} recorded nothing exercised and no reason")
    return ("clean - " + NO_FINDINGS, [])


def validate_pack(pack):
    """Normalise one round pack, or refuse it by name.

    A pack is ``{"round": str, "surfaces": {surface: [items]}}``. Every surface
    is required; an empty surface, an item without a note, a finding without a
    disposition, or an unknown surface is a refusal -- not a warning.
    """
    if not isinstance(pack, dict):
        raise DogfoodError(f"a round pack must be a mapping, got {type(pack).__name__}")
    round_id = _checked_text(pack.get("round"), "round")
    surfaces = pack.get("surfaces")
    if not isinstance(surfaces, dict):
        raise DogfoodError("a round pack needs a surfaces mapping")
    unknown = sorted(set(surfaces) - set(SURFACES))
    if unknown:
        raise DogfoodError(
            f"a round pack covers exactly {list(SURFACES)}; unknown {unknown}")
    missing = [s for s in SURFACES if s not in surfaces]
    if missing:
        raise DogfoodError(
            f"a round pack must cover every surface; missing {missing} - a report "
            "that omits a surface is the round-1 failure this round exists to fix")
    normalised = {"round": round_id, "surfaces": {}}
    for surface in SURFACES:
        items = [check_item(item) for item in surfaces[surface]]
        verdict, blockers = surface_verdict(surface, items)
        normalised["surfaces"][surface] = {
            "items": items, "verdict": verdict, "blockers": blockers}
    return normalised


def render_report(pack):
    """Render the filed report: per-surface sections and a closing verdict table."""
    normalised = validate_pack(pack)
    lines = [
        "# Dogfood round report - {}".format(normalised["round"]),
        "",
        "Structured round per #277: one section per surface, every item recorded, "
        "silence not counted as a result.",
        "",
    ]
    for surface in SURFACES:
        section = normalised["surfaces"][surface]
        lines.append("## {}".format(surface.upper()))
        lines.append("")
        lines.append("Checklist: {}".format(CHECKLIST[surface]))
        lines.append("")
        for item in section["items"]:
            if item["status"] == "finding":
                finding = item["finding"]
                where = (f"issue #{finding['issue']}" if "issue" in finding
                         else "fixed in this round")
                lines.append("- **{}** - FINDING ({}, {}): {} [{}]".format(item["item"], finding["severity"], where,
                                finding["text"], item["note"]))
            elif item["status"] == "not_exercised":
                lines.append("- **{}** - NOT EXERCISED: {}".format(item["item"], item["note"]))
            else:
                lines.append("- **{}** - exercised: {}".format(item["item"], item["note"]))
        lines.append("")
        lines.append("Verdict: {}".format(section["verdict"]))
        lines.append("")
    lines.append("## Verdicts")
    lines.append("")
    lines.append("| surface | verdict |")
    lines.append("|---|---|")
    for surface in SURFACES:
        lines.append("| {} | {} |".format(surface, normalised["surfaces"][surface]["verdict"]))
    lines.append("")
    return "\n".join(lines)


def load_pack(path):
    """Read a pack from disk, refusing a file that is not a JSON object."""
    with open(path, encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except ValueError as exc:
            raise DogfoodError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise DogfoodError(f"{path} must contain a JSON object")
    return data
