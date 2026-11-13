"""Stand-up keyed live smoke (HAR-SAMS, 2026-11-13).

One live jev-decide probe through the repo's own resolver:
load_settings() -> resolve_jev_key() -> JevPolicy.evaluate_triage().
Prints presence + verdict only; never prints key material.
"""
import sys

sys.path.insert(0, "C:/Users/SCM/Documents/GitHub/Harness")

from harness.config import load_settings
from harness.jev_policy import policy_for
from harness.session import jev_face_governor

settings = load_settings()
governor = jev_face_governor(settings)
print("GOVERNOR: " + ("keyed-shared" if governor is not None else "none-unkeyed"))
policy = policy_for(settings, governor=governor)
print("KEYED: " + str(policy.keyed))
result, _structural = policy.evaluate_triage(
    "Stand-up smoke probe: route a one-line documentation question.",
    target_files=[],
)
print("VERDICT: " + str(result.verdict))
print("FALLBACK: " + str(result.is_fallback))
print("MODEL: " + str(result.model))
print("ANSWERS: " + str(result.answers))
print("REASONS: " + str(list(result.reasons or [])[:2]))
