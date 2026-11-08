"""Normalize a GitHub Actions job log into the Rust `tracing` shape that
Harness `log-judgment` parses, with NO model spend (pure code).

Input line shape (tab separated):
    <job>\\t<step>\\t<ISO-8601 ts>Z <message...>

Output line shape (what harness/log_items._TRACING_LINE accepts):
    <ISO-8601 ts>Z  <LEVEL>  ci::<step-slug>: <message>

Levels are derived from the message text ONLY as a mechanical mapping of
GitHub Actions/Gradle conventions; every rule is listed so the mapping is
auditable. Nothing here decides severity on its own -- the operator pack's
score question does that via Jev.
"""
import re
import sys

TS = re.compile(r"(\d{4}-\d{2}-\d{2}T[0-9:.]+Z?)")

# Ordered rules: first match wins. Auditable, no model.
RULES = [
    ("ERROR", re.compile(r"^\s*[\w. ]*(Test|test)\b.*\bFAILED\b")),
    ("ERROR", re.compile(r"\bBUILD FAILED\b")),
    ("ERROR", re.compile(r"\bExecution failed for task\b")),
    ("ERROR", re.compile(r"\bTests? FAILED\b|\bFAILED\b")),
    ("ERROR", re.compile(r"\bAssertionError\b|\bVerification failed\b")),
    ("ERROR", re.compile(r"\berror:|\bERROR\]|severity: error")),
    ("ERROR", re.compile(r"\bBUILD FAILURE\b")),
    ("WARN", re.compile(r"\bwarning:|\bWARNING\]|\bWARN\b")),
    ("WARN", re.compile(r"\bdeprecated\b|\bdeprecat")),
]

SLUG = re.compile(r"[^A-Za-z0-9]+")


def slug(text):
    return SLUG.sub("_", text).strip("_").lower() or "step"


def level_for(message):
    for level, pattern in RULES:
        if pattern.search(message):
            return level
    return "INFO"


def main(src, dst, min_level="WARN"):
    out = []
    kept = dropped = 0
    with open(src, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            # strip the GH Actions job/step columns
            parts = line.split("\t", 2)
            if len(parts) == 3 and TS.search(parts[2]):
                step, rest = parts[1], parts[2]
            else:
                step, rest = "step", line
            match = TS.search(rest)
            if match is None:
                continue
            ts = match.group(1)
            if not ts.endswith("Z"):
                ts += "Z"
            message = rest[match.end():].strip()
            if not message:
                continue
            level = level_for(message)
            if min_level == "WARN" and level == "INFO":
                dropped += 1
                continue
            out.append("%s  %s  ci::%s: %s" % (ts, level, slug(step), message))
            kept += 1
    with open(dst, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(out) + "\n")
    sys.stderr.write("[normalize] kept=%d dropped_info=%d -> %s\n"
                     % (kept, dropped, dst))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2],
         sys.argv[3] if len(sys.argv) > 3 else "WARN")
