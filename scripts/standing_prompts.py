"""Standing continuation prompts, read from the pinned runtime home (G13).

The owner's order of 2026-11-27 (registry landed at `Treystu/slow-lane-ledger`
`0360997e`, `dispatch/laptop-driver/standing-prompts/`) makes registration the
discretion mechanism: the driver continues ONLY a lane with a registered
prompt, delivers that text verbatim after the identity check, and parks NAMED
(`no-prompt-registered`) rather than improvising when the lane has no file.

This module is the reader. It resolves a lane to its file under the *pinned*
runtime home - never the ledger and never the dev tree - so a continuation is
attributable to the exact bytes that were delivered: the returned ``sha256`` is
the evidence a verdict carries. Pinning the registry into the home is
``scripts.driver_runtime_home``'s job; a home without one refuses here by name
instead of falling back to a bare "continue in full".
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

#: Directory under the pinned home that carries the registry snapshot.
REGISTRY_DIR = "registry"
#: Directory inside the snapshot, mirroring the ledger's layout.
PROMPTS_DIR = "standing-prompts"

_SLUG = re.compile(r"[^a-z0-9]+")


class PromptMissing(RuntimeError):
    """The lane has no usable registered prompt; ``reason`` is the park name."""

    def __init__(self, lane: str, reason: str, detail: str = ""):
        self.lane = lane
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: lane {lane!r}" + (f" ({detail})" if detail else ""))


def lane_slug(lane: str) -> str:
    """The registry file stem for a lane name: "Lane 1" -> "lane-1".

    The README's rule is that a lane's file *is* its registration, so the name
    the dispatch carries has to map to a file name deterministically. Runs of
    anything that is not a letter or digit collapse to one hyphen; a name with
    no letters or digits has no file and is refused.
    """
    slug = _SLUG.sub("-", str(lane or "").strip().casefold()).strip("-")
    if not slug:
        raise PromptMissing(str(lane or ""), "no-prompt-registered",
                            "the lane name carries no usable file stem")
    return slug


def registry_root(runtime_root: Path) -> Path:
    return Path(runtime_root) / REGISTRY_DIR / PROMPTS_DIR


def registered(runtime_root: Path) -> list[str]:
    """The file stems present in the pinned home, sorted; empty when unpinned."""
    root = registry_root(runtime_root)
    if not root.is_dir():
        return []
    return sorted(path.stem for path in root.glob("*.md") if path.is_file())


def resolve(runtime_root: Path, lane: str) -> dict:
    """The registered prompt for ``lane`` from the pinned home, or ``PromptMissing``.

    Returns ``{"lane", "slug", "file", "path", "text", "sha256"}``. Every
    refusal is named by cause so the watch can park with a reason instead of a
    boolean: a missing home, a missing file, unreadable bytes, an empty text.
    """
    root = registry_root(runtime_root)
    if not root.is_dir():
        raise PromptMissing(str(lane), "no-prompt-registered",
                            f"the pinned home carries no {REGISTRY_DIR}/{PROMPTS_DIR}")
    slug = lane_slug(lane)
    path = root / f"{slug}.md"
    if not path.is_file():
        raise PromptMissing(str(lane), "no-prompt-registered",
                            f"{slug}.md is not registered")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise PromptMissing(str(lane), "unreadable-prompt", f"{slug}.md: {error}") from error
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PromptMissing(str(lane), "unreadable-prompt",
                            f"{slug}.md is not UTF-8: {error}") from error
    if not text.strip():
        raise PromptMissing(str(lane), "empty-prompt", f"{slug}.md is blank")
    return {
        "lane": str(lane),
        "slug": slug,
        "file": f"{slug}.md",
        "path": str(path),
        "text": text,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
