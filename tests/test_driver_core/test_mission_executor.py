"""#483 B3: the executor's guarantees, proved where a desktop cannot refuse them.

Three acceptance lines are executable here -- the replay probe, the stale
mission probe, and the non-allowlisted author probe -- plus the properties the
executor exists to hold: the inbox reads only what it declared, the token is
scoped and never printed, read-back gates execution, and one bad mission does
not stop the queue.
"""
import json
import os
import tempfile
import unittest

from driver_core import mission as ms
from driver_core import mission_executor as mx

REPO = "Treystu/private-ledger"
ALLOWED = ("treystu", "oversight")
NOW = 1000.0


def _clock():
    return NOW


def _epoch():
    return ms.mission_epoch(clock=_clock)


def _payload(mission_id="m-1", **overrides):
    body = {"id": mission_id, "author": "Treystu", "action": "click",
            "params": {"target": {"window": "Notes",
                                  "rect": [1, 2, 30, 40],
                                  "space": "client-logical",
                                  "schema": "target@2"}},
            "epoch": _epoch()}
    body.update(overrides)
    return body


class InboxCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="mission-test-")
        self.root = self._tmp.name
        os.makedirs(os.path.join(self.root, mx.MISSIONS_DIR), exist_ok=True)
        self.manifest(repo=REPO, private=True)
        self.token = mx.MissionToken(
            "secret-token-value", capabilities=mx.CAPABILITIES, repo=REPO)

    def tearDown(self):
        self._tmp.cleanup()

    def manifest(self, *, repo=REPO, private=True, schema=mx.INBOX_SCHEMA):
        record = {"schema": schema, "repo": repo, "private": private}
        with open(os.path.join(self.root, mx.MANIFEST_FILE), "w",
                  encoding="utf-8") as handle:
            json.dump(record, handle)

    def inbox(self, **kwargs):
        return mx.MissionInbox(self.root, token=kwargs.pop("token",
                                                          self.token))

    def put(self, payload, name=None):
        name = name or (payload["id"] + ".json")
        path = os.path.join(self.root, mx.MISSIONS_DIR, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def executor(self, *, execute=None, inbox=None, owner="exec-1",
                 allowlist=ALLOWED, threshold=mx.READ_BACK_THRESHOLD):
        inbox = inbox or self.inbox()
        claims = mx.MissionClaimStore(os.path.join(self.root, "claims.sqlite3"))
        self.executed = []

        def default_execute(mission):
            self.executed.append(mission["id"])
            return {"ok": True}

        return mx.MissionExecutor(
            inbox, claims, allowlist=allowlist,
            execute=execute or default_execute, owner=owner,
            clock=_clock, threshold=threshold)


class ManifestTests(InboxCase):
    def test_a_root_with_no_manifest_is_refused(self):
        os.remove(os.path.join(self.root, mx.MANIFEST_FILE))
        with self.assertRaises(ms.MissionRefused) as caught:
            self.inbox()
        self.assertIn("nobody declared", str(caught.exception))

    def test_a_public_root_is_refused(self):
        self.manifest(private=False)
        with self.assertRaises(ms.MissionRefused) as caught:
            self.inbox()
        self.assertIn("not declared private", str(caught.exception))

    def test_another_repository_root_is_refused(self):
        self.manifest(repo="Treystu/harness")
        with self.assertRaises(ms.MissionRefused) as caught:
            self.inbox()
        self.assertIn("Treystu/harness", str(caught.exception))
        self.assertIn(REPO, str(caught.exception))

    def test_an_unknown_schema_is_refused(self):
        self.manifest(schema="mission-inbox@9")
        with self.assertRaises(ms.MissionRefused) as caught:
            self.inbox()
        self.assertIn("mission-inbox@9", str(caught.exception))


class TokenTests(unittest.TestCase):
    def test_a_secret_never_appears_in_the_representation(self):
        token = mx.MissionToken("super-secret", capabilities=("read_missions",),
                                repo=REPO)
        self.assertNotIn("super-secret", repr(token))
        self.assertNotIn("super-secret", str(token))
        self.assertIn("fp=", repr(token))

    def test_an_unscoped_capability_refuses_by_name(self):
        token = mx.MissionToken("s", capabilities=("read_missions",), repo=REPO)
        with self.assertRaises(ms.MissionRefused) as caught:
            token.require("write_receipts")
        self.assertIn("not scoped for 'write_receipts'", str(caught.exception))

    def test_an_unknown_capability_is_refused_at_construction(self):
        with self.assertRaises(ms.MissionRefused) as caught:
            mx.MissionToken("s", capabilities=("admin",), repo=REPO)
        self.assertIn("unknown capabilit", str(caught.exception))

    def test_the_fingerprint_is_stable_and_short(self):
        first = mx.MissionToken("s", capabilities=(), repo=REPO)
        second = mx.MissionToken("s", capabilities=(), repo=REPO)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(len(first.fingerprint), 16)


class InboxDisciplineTests(InboxCase):
    def test_pending_is_sorted_and_ignores_dotfiles(self):
        self.put(_payload("b"))
        self.put(_payload("a"))
        open(os.path.join(self.root, mx.MISSIONS_DIR, ".DS_Store"),
             "w").close()
        self.assertEqual(self.inbox().pending(), ["a.json", "b.json"])

    def test_a_non_json_file_stops_the_poll_by_name(self):
        self.put(_payload("a"))
        with open(os.path.join(self.root, mx.MISSIONS_DIR, "notes.txt"),
                  "w") as handle:
            handle.write("hello")
        with self.assertRaises(ms.MissionRefused) as caught:
            self.inbox().pending()
        self.assertIn("notes.txt", str(caught.exception))
        self.assertIn("not a mission file", str(caught.exception))

    def test_a_symlinked_mission_is_refused(self):
        outside = os.path.join(self.root, "outside.json")
        with open(outside, "w", encoding="utf-8") as handle:
            json.dump(_payload("linked"), handle)
        link = os.path.join(self.root, mx.MISSIONS_DIR, "linked.json")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable on this host")
        with self.assertRaises(ms.MissionRefused) as caught:
            self.inbox().pending()
        self.assertIn("symlink", str(caught.exception))

    def test_an_oversized_mission_is_refused(self):
        path = os.path.join(self.root, mx.MISSIONS_DIR, "big.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{" + " " * (mx.MAX_MISSION_BYTES + 10) + "}")
        with self.assertRaises(ms.MissionRefused) as caught:
            self.inbox().read("big.json")
        self.assertIn("bytes", str(caught.exception))

    def test_a_read_only_token_cannot_poll(self):
        token = mx.MissionToken("s", capabilities=("write_receipts",), repo=REPO)
        with self.assertRaises(ms.MissionRefused) as caught:
            mx.MissionInbox(self.root, token=token).pending()
        self.assertIn("read_missions", str(caught.exception))


class ReadBackTests(unittest.TestCase):
    def test_identical_records_score_one_hundred(self):
        score, mismatched = mx.read_back({"a": 1, "b": {"c": 2}},
                                         {"a": 1, "b": {"c": 2}})
        self.assertEqual(score, 100.0)
        self.assertEqual(mismatched, [])

    def test_one_changed_field_is_named(self):
        score, mismatched = mx.read_back({"a": 1, "b": 2}, {"a": 1, "b": 3})
        self.assertEqual(mismatched, ["b"])
        self.assertEqual(score, 50.0)

    def test_a_deleted_field_is_a_mismatch_not_a_pass(self):
        score, mismatched = mx.read_back({"a": 1, "b": 2}, {"a": 1})
        self.assertEqual(mismatched, ["b"])
        self.assertEqual(score, 50.0)

    def test_a_nested_field_is_compared_by_path(self):
        score, mismatched = mx.read_back(
            {"params": {"target": "Notes"}},
            {"params": {"target": "Elsewhere"}})
        self.assertEqual(mismatched, ["params.target"])


class ClaimTests(InboxCase):
    def store(self):
        return mx.MissionClaimStore(os.path.join(self.root, "claims.sqlite3"))

    def test_a_first_claim_is_granted(self):
        self.assertEqual(self.store().claim("m-1", epoch_issued_at=NOW,
                                            owner="a", clock=_clock),
                         (True, ""))

    def test_a_second_writer_is_refused_while_the_heartbeat_is_fresh(self):
        store = self.store()
        store.claim("m-1", epoch_issued_at=NOW, owner="a", clock=_clock)
        ok, why = store.claim("m-1", epoch_issued_at=NOW, owner="b",
                              clock=_clock)
        self.assertFalse(ok)
        self.assertIn("held by 'a'", why)

    def test_a_silent_claim_can_be_taken_over(self):
        store = self.store()
        store.claim("m-1", epoch_issued_at=NOW, owner="a", clock=_clock)
        ok, why = store.claim("m-1", epoch_issued_at=NOW, owner="b",
                              clock=lambda: NOW + 120.0)
        self.assertTrue(ok, why)

    def test_a_refiled_epoch_is_a_different_claim(self):
        store = self.store()
        store.claim("m-1", epoch_issued_at=NOW, owner="a", clock=_clock)
        ok, why = store.claim("m-1", epoch_issued_at=NOW + 1, owner="a",
                              clock=lambda: NOW + 120.0)
        self.assertFalse(ok)
        self.assertIn("different epoch", why)

    def test_a_done_mission_cannot_be_claimed_again(self):
        store = self.store()
        store.claim("m-1", epoch_issued_at=NOW, owner="a", clock=_clock)
        store.finish("m-1", "a", state=mx.DONE, clock=_clock)
        ok, why = store.claim("m-1", epoch_issued_at=NOW, owner="a",
                              clock=lambda: NOW + 500.0)
        self.assertFalse(ok)
        self.assertIn("already done", why)

    def test_only_the_holder_may_heartbeat_or_finish(self):
        store = self.store()
        store.claim("m-1", epoch_issued_at=NOW, owner="a", clock=_clock)
        self.assertFalse(store.heartbeat("m-1", "b", clock=_clock)[0])
        self.assertFalse(store.finish("m-1", "b", state=mx.DONE,
                                      clock=_clock)[0])


class ExecutorTests(InboxCase):
    def test_a_token_that_cannot_receipt_never_executes(self):
        # #683 finding 25: without the write capability the claim would stay
        # open after the action ran, so a second poll could replay it.
        self.put(_payload())
        read_only = mx.MissionToken(
            "secret-token-value", capabilities=("read_missions",), repo=REPO)
        executor = self.executor(inbox=self.inbox(token=read_only))
        with self.assertRaises(mx.missions.MissionRefused) as caught:
            executor.process_next()
        self.assertIn("write_receipts", str(caught.exception))
        self.assertEqual(self.executed, [])
        self.assertEqual(self.inbox().pending(), ["m-1.json"])

    def test_a_valid_mission_executes_once_and_is_receipted(self):
        self.put(_payload())
        executor = self.executor()
        receipt = executor.run()
        self.assertEqual(len(receipt), 1)
        self.assertEqual(receipt[0]["state"], mx.DONE)
        self.assertEqual(receipt[0]["schema"], mx.RECEIPT_SCHEMA)
        self.assertEqual(self.executed, ["m-1"])
        self.assertEqual(executor.inbox.pending(), [])
        receipt_path = os.path.join(self.root, mx.RECEIPTS_DIR, "m-1.json")
        with open(receipt_path, encoding="utf-8") as handle:
            filed = json.load(handle)
        self.assertEqual(filed["state"], mx.DONE)
        self.assertEqual(filed["evidence"], {"ok": True})

    def test_replaying_a_spent_mission_cannot_execute_twice(self):
        self.put(_payload())
        executor = self.executor()
        executor.run()
        self.put(_payload())
        receipt = executor.run()
        self.assertEqual(receipt[0]["state"], mx.PARKED)
        self.assertIn("already done", receipt[0]["detail"])
        self.assertEqual(self.executed, ["m-1"])

    def test_an_unlisted_author_is_refused_and_logged(self):
        self.put(_payload(author="stranger"))
        receipt = self.executor().run()
        self.assertEqual(receipt[0]["state"], mx.PARKED)
        self.assertIn("not on the mission allowlist", receipt[0]["detail"])
        self.assertEqual(self.executed, [])
        log = os.path.join(self.root, "missions.log.jsonl")
        self.assertTrue(os.path.isfile(log))
        with open(log, encoding="utf-8") as handle:
            record = json.loads(handle.readline())
        self.assertEqual(record["event"], "mission_refused")
        self.assertIn("stranger", record["reason"])

    def test_an_expired_epoch_refuses(self):
        self.put(_payload(epoch={"issued_at": NOW - 5000.0,
                                 "expires_at": NOW - 4900.0}))
        receipt = self.executor().run()
        self.assertEqual(receipt[0]["state"], mx.PARKED)
        self.assertIn("expired", receipt[0]["detail"])
        self.assertEqual(self.executed, [])

    def test_a_tampered_file_is_caught_by_read_back_before_execution(self):
        self.put(_payload())
        inbox = self.inbox()
        original = inbox.read
        reads = {"count": 0}

        def reading(filename):
            reads["count"] += 1
            payload = original(filename)
            if reads["count"] == 2:
                payload = dict(payload)
                payload["params"] = {"target": "Elsewhere"}
            return payload

        inbox.read = reading
        executor = self.executor(inbox=inbox)
        receipt = executor.run()
        self.assertEqual(receipt[0]["state"], mx.PARKED)
        self.assertIn("read-back scored", receipt[0]["detail"])
        mismatched = receipt[0]["evidence"]["read_back"]["mismatched"]
        self.assertIn("params.target", mismatched)
        self.assertLess(receipt[0]["evidence"]["read_back"]["score"], 95)
        self.assertEqual(self.executed, [])

    def test_one_bad_mission_does_not_stop_the_queue(self):
        self.put(_payload("a", author="stranger"))
        self.put(_payload("b"))
        receipts = self.executor().run()
        self.assertEqual([r["mission_id"] for r in receipts], ["a", "b"])
        self.assertEqual([r["state"] for r in receipts], [mx.PARKED, mx.DONE])
        self.assertEqual(self.executed, ["b"])

    def test_a_failing_action_parks_and_continues(self):
        self.put(_payload("a"))
        self.put(_payload("b"))

        def execute(mission):
            if mission["id"] == "a":
                raise RuntimeError("display gone")
            return {"ok": True}

        receipts = self.executor(execute=execute).run()
        self.assertEqual(receipts[0]["state"], mx.PARKED)
        self.assertIn("display gone", receipts[0]["detail"])
        self.assertEqual(receipts[1]["state"], mx.DONE)

    def test_a_mission_held_by_another_executor_waits(self):
        self.put(_payload())
        store = mx.MissionClaimStore(os.path.join(self.root, "claims.sqlite3"))
        store.claim("m-1", epoch_issued_at=NOW, owner="other", clock=_clock)
        receipt = self.executor().run()
        self.assertEqual(receipt[0]["state"], "waiting")
        self.assertIn("held by 'other'", receipt[0]["detail"])
        self.assertEqual(self.executed, [])
        # Still in the queue for the holder to retire.
        self.assertEqual(self.executor().inbox.pending(), ["m-1.json"])

    def test_an_empty_queue_returns_nothing(self):
        self.assertEqual(self.executor().run(), [])

    def test_an_irreversible_mission_without_approval_is_parked(self):
        self.put(_payload(action="submit_irreversible", params={},
                          target="Send"))
        receipt = self.executor().run()
        self.assertEqual(receipt[0]["state"], mx.PARKED)
        self.assertIn("missing required parameter", receipt[0]["detail"])
        self.assertEqual(self.executed, [])


if __name__ == "__main__":
    unittest.main()
