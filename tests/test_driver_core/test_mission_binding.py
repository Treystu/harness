"""#483 B4: the mission envelope, its epoch, and the single-use approval binding.

Three of the issue's acceptance lines are provable without a desktop, and each
has its own class here:

* **replay probe** -- a spent approval cannot execute twice;
* **stale-mission probe** -- an expired epoch refuses;
* **author probe** -- a mission from a non-allowlisted author is refused *and
  logged*.

Two more are pinned because the security model is worthless without them: a
mission can only name an action the declared vocabulary carries (GitHub text is
data), and an approval is bound to the exact action, target and screenshot
fingerprint it was issued for rather than to "a click".
"""
import json
import os
import tempfile
import unittest

from driver_core import mission as ms
from driver_core.actions import DEFAULT_VOCABULARY

ALLOWED = ("treystu", "oversight")


def _epoch(**kwargs):
    return ms.mission_epoch(clock=lambda: 1000.0, **kwargs)


def _mission(**overrides):
    payload = {"id": "m-1", "author": "Treystu", "action": "click",
               "params": {"target": "Notes"}, "epoch": _epoch()}
    payload.update(overrides)
    return payload


class AuthorAllowlistTests(unittest.TestCase):
    def test_a_declared_author_is_allowed(self):
        ok, why = ms.author_allowed("Treystu", ALLOWED)
        self.assertTrue(ok, why)

    def test_case_and_whitespace_do_not_smuggle_an_author_in(self):
        self.assertTrue(ms.author_allowed("  OVERsight ", ALLOWED)[0])

    def test_an_undeclared_author_is_refused_by_name(self):
        ok, why = ms.author_allowed("drive-by", ALLOWED)
        self.assertFalse(ok)
        self.assertIn("drive-by", why)
        self.assertIn("not on the mission allowlist", why)

    def test_an_empty_allowlist_is_default_deny_not_default_allow(self):
        ok, why = ms.author_allowed("Treystu", ())
        self.assertFalse(ok)
        self.assertIn("no mission authors are allowlisted", why)

    def test_a_blank_author_is_refused(self):
        for author in ("", "   ", None, 7):
            self.assertFalse(ms.author_allowed(author, ALLOWED)[0])


class EpochTests(unittest.TestCase):
    def test_a_fresh_epoch_passes(self):
        ok, why = ms.check_epoch(_epoch(), now=1001.0)
        self.assertTrue(ok, why)

    def test_an_expired_epoch_refuses_and_names_its_age(self):
        # The stale-mission probe: 900 s window, read 10 s past it.
        ok, why = ms.check_epoch(_epoch(), now=1910.0)
        self.assertFalse(ok)
        self.assertIn("expired", why)
        self.assertIn("10.000", why)

    def test_a_missing_or_undated_epoch_refuses(self):
        for epoch in (None, {}, {"issued_at": 1000.0}, {"expires_at": "later"}):
            ok, why = ms.check_epoch(epoch, now=1000.0)
            self.assertFalse(ok)
            self.assertIn("epoch", why)

    def test_an_epoch_from_the_future_is_a_clock_disagreement(self):
        ok, why = ms.check_epoch({"issued_at": 1010.0, "expires_at": 1900.0},
                                 now=1000.0)
        self.assertFalse(ok)
        self.assertIn("disagree about the clock", why)

    def test_an_impossible_ttl_is_refused_at_issue(self):
        with self.assertRaises(ms.MissionRefused):
            ms.mission_epoch(ttl=-1)


class ApprovalBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ms.ApprovalStore(self.tmp.name)

    def _issue(self, **overrides):
        kwargs = {"action": "click", "target": "Notes",
                  "fingerprint": "ab" * 32, "expires_at": 2000.0}
        kwargs.update(overrides)
        self.store.issue("a-1", **kwargs)

    def test_a_bound_approval_validates_for_its_exact_grant(self):
        self._issue()
        guard, why = self.store.validate(
            "a-1", action="click", target="Notes", fingerprint="ab" * 32,
            now=1500.0)
        self.assertIsNotNone(guard, why)
        self.assertEqual(why, "")

    def test_a_different_target_does_not_travel(self):
        self._issue()
        guard, why = self.store.validate(
            "a-1", action="click", target="Notes elsewhere",
            fingerprint="ab" * 32, now=1500.0)
        self.assertIsNone(guard)
        self.assertIn("different target", why)

    def test_a_different_fingerprint_does_not_travel(self):
        self._issue()
        guard, why = self.store.validate(
            "a-1", action="click", target="Notes", fingerprint="cd" * 32,
            now=1500.0)
        self.assertIsNone(guard)
        self.assertIn("different fingerprint", why)

    def test_a_different_action_does_not_travel(self):
        self._issue()
        guard, why = self.store.validate(
            "a-1", action="launch_app", target="Notes", fingerprint="ab" * 32,
            now=1500.0)
        self.assertIsNone(guard)
        self.assertIn("different action", why)

    def test_an_expired_approval_refuses(self):
        self._issue()
        guard, why = self.store.validate(
            "a-1", action="click", target="Notes", fingerprint="ab" * 32,
            now=2000.5)
        self.assertIsNone(guard)
        self.assertIn("expired", why)
        self.assertIn("0.500", why)

    def test_an_unknown_approval_refuses(self):
        guard, why = self.store.validate(
            "never-issued", action="click", target="Notes",
            fingerprint="ab" * 32, now=1500.0)
        self.assertIsNone(guard)
        self.assertIn("unknown approval", why)

    def test_a_spent_approval_cannot_execute_twice(self):
        # The replay probe, end to end: validate -> spend -> validate again.
        self._issue()
        guard, why = self.store.validate(
            "a-1", action="click", target="Notes", fingerprint="ab" * 32,
            now=1500.0)
        self.assertIsNotNone(guard, why)
        self.store.spend(guard)
        again, why = self.store.validate(
            "a-1", action="click", target="Notes", fingerprint="ab" * 32,
            now=1501.0)
        self.assertIsNone(again)
        self.assertIn("already been spent", why)

    def test_a_failed_execution_returns_the_approval_to_available(self):
        # The grant bought an attempt, not a success: the ledger releases it
        # so a reader that failed did not silently consume the owner's yes.
        self._issue()
        guard, _ = self.store.validate(
            "a-1", action="click", target="Notes", fingerprint="ab" * 32,
            now=1500.0)
        self.store.spend(guard, succeeded=False)
        guard, why = self.store.validate(
            "a-1", action="click", target="Notes", fingerprint="ab" * 32,
            now=1502.0)
        self.assertIsNotNone(guard, why)

    def test_an_approval_id_is_a_plain_identifier(self):
        for bad in ("../escape", "a/b", "", "../../etc/passwd"):
            with self.assertRaises(ms.MissionRefused):
                self.store.issue(bad, action="click", target="Notes",
                                 fingerprint="ab" * 32, expires_at=2000.0)

    def test_the_record_on_disk_is_the_binding(self):
        self._issue()
        record = self.store.read("a-1")
        self.assertEqual(record["schema"], ms.APPROVAL_SCHEMA)
        self.assertEqual(record["action"], "click")
        self.assertEqual(record["fingerprint"], "ab" * 32)


class ParseMissionTests(unittest.TestCase):
    def test_a_valid_mutating_mission_normalises(self):
        parsed = ms.parse_mission(_mission(), allowlist=ALLOWED, now=1001.0)
        self.assertEqual(parsed["schema"], ms.MISSION_SCHEMA)
        self.assertEqual(parsed["action"], "click")
        self.assertEqual(parsed["author"], "treystu")
        self.assertEqual(parsed["params"], {"target": "Notes"})

    def test_an_undeclared_action_is_refused_by_the_vocabulary(self):
        with self.assertRaises(ms.MissionRefused) as ctx:
            ms.parse_mission(_mission(action="open_terminal"), allowlist=ALLOWED,
                             now=1001.0)
        self.assertIn("open_terminal", str(ctx.exception))

    def test_an_undeclared_parameter_is_refused(self):
        with self.assertRaises(ms.MissionRefused) as ctx:
            ms.parse_mission(_mission(params={"target": "Notes", "path": "/x"}),
                             allowlist=ALLOWED, now=1001.0)
        self.assertIn("undeclared parameter", str(ctx.exception))

    def test_an_undeclared_mission_field_is_refused(self):
        with self.assertRaises(ms.MissionRefused) as ctx:
            ms.parse_mission(_mission(command="rm -rf /"), allowlist=ALLOWED,
                             now=1001.0)
        self.assertIn("unknown field", str(ctx.exception))

    def test_a_missing_required_field_is_named(self):
        payload = _mission()
        payload.pop("epoch")
        with self.assertRaises(ms.MissionRefused) as ctx:
            ms.parse_mission(payload, allowlist=ALLOWED, now=1001.0)
        self.assertIn("epoch", str(ctx.exception))

    def test_an_unlisted_author_is_refused_before_the_action_is_resolved(self):
        # The action name is deliberately undeclared too: the author check must
        # answer first, so a hostile payload learns nothing about the vocabulary.
        payload = _mission(author="drive-by", action="no-such-action")
        with self.assertRaises(ms.MissionRefused) as ctx:
            ms.parse_mission(payload, allowlist=ALLOWED, now=1001.0)
        message = str(ctx.exception)
        self.assertIn("drive-by", message)
        self.assertNotIn("no-such-action", message)

    def test_a_stale_mission_is_refused_before_the_action_is_resolved(self):
        payload = _mission(action="no-such-action")
        with self.assertRaises(ms.MissionRefused) as ctx:
            ms.parse_mission(payload, allowlist=ALLOWED, now=5000.0)
        self.assertIn("expired", str(ctx.exception))
        self.assertNotIn("no-such-action", str(ctx.exception))

    def test_an_irreversible_mission_must_carry_its_approval_material(self):
        payload = _mission(action="submit_irreversible",
                           params={"target": "Send"})
        with self.assertRaises(ms.MissionRefused) as ctx:
            ms.parse_mission(payload, allowlist=ALLOWED, now=1001.0)
        self.assertIn("irreversible", str(ctx.exception))
        self.assertIn("approval", str(ctx.exception))

    def test_an_irreversible_mission_with_its_material_parses(self):
        payload = _mission(action="submit_irreversible",
                           params={"target": "Send"}, approval="a-1",
                           fingerprint="ab" * 32, target="Send")
        parsed = ms.parse_mission(payload, allowlist=ALLOWED, now=1001.0)
        self.assertEqual(parsed["action"], "submit_irreversible")
        self.assertEqual(parsed["approval"], "a-1")

    def test_the_vocabulary_is_the_boundary(self):
        # Whatever the tier declares is the whole set a mission can name.
        self.assertIn("click", DEFAULT_VOCABULARY.names())
        self.assertNotIn("open_terminal", DEFAULT_VOCABULARY.names())


class RefusalLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_a_refusal_is_logged_without_the_payload(self):
        record = ms.log_refusal(self.tmp.name, "author 'x' is not allowlisted",
                                mission_id="m-9", author="x",
                                clock=lambda: 1234.0)
        path = os.path.join(self.tmp.name, "missions.log.jsonl")
        with open(path, encoding="utf-8") as handle:
            written = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["event"], "mission_refused")
        self.assertEqual(written[0]["mission_id"], "m-9")
        self.assertEqual(written[0]["ts"], 1234.0)
        self.assertIn("not allowlisted", written[0]["reason"])
        self.assertNotIn("params", written[0])
        self.assertEqual(record["schema"], "mission-log@1")

    def test_the_refusal_path_is_what_a_parser_uses(self):
        # A refused mission leaves a log line, which is the acceptance's
        # "refused and logged" rather than "refused quietly".
        payload = _mission(author="drive-by")
        with self.assertRaises(ms.MissionRefused) as ctx:
            ms.parse_mission(payload, allowlist=ALLOWED, now=1001.0)
        ms.log_refusal(self.tmp.name, str(ctx.exception),
                       mission_id=payload["id"], author=payload["author"])
        with open(os.path.join(self.tmp.name, "missions.log.jsonl"),
                  encoding="utf-8") as handle:
            self.assertIn("drive-by", handle.read())


if __name__ == "__main__":
    unittest.main()
