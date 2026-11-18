"""#336: signed reversible compaction and canaries, over the real ledger.

Every test drives the real hash chain, the real sealed-segment files and the
real signing key path -- no mocks that restate the implementation. The fixture
below writes a genuine chained segment (correct hashes, real timestamps) and an
active tail that continues it, so a compaction here is the same operation
rotation performs, not a rehearsal on invented rows.
"""
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from harness import ledger_canary
from harness import ledger_compaction as compaction
from harness.errors import HarnessError
from harness.ledger import AutonomyLedger, _canon

OLD_TS = "2026-09-01T00:00:00+00:00"
RECENT_TS = datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_epoch():
    return datetime.now(timezone.utc).timestamp()


def _row(seq, event, prev, *, ts=OLD_TS, **fields):
    entry = {"seq": seq, "ts": ts, "event": event, "task_id": None,
             "prev_hash": prev}
    entry.update(fields)
    entry["hash"] = hashlib.sha256(_canon(entry).encode("utf-8")).hexdigest()
    return entry


def _write(path, rows):
    with open(path, "wb") as handle:
        for row in rows:
            handle.write((_canon(row) + "\n").encode("utf-8"))


class CompactionFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.path = os.path.join(self.dir, "ledger.jsonl")
        self.key_path = os.path.join(self.dir, "signing.key")
        self._env = mock.patch.dict(os.environ,
                                    {"HARNESS_LEDGER_SIGNING_KEY": self.key_path})
        self._env.start()
        self.addCleanup(self._env.stop)

    def seal(self, specs, *, tail_events=("offer",)):
        """Write one sealed segment (old rows) plus an active tail continuing it."""
        seq, prev = 0, None
        segment_rows, active_rows = [], []
        for spec in specs:
            seq += 1
            row = _row(seq, spec["event"], prev, **{k: v for k, v in spec.items()
                                                    if k != "event"})
            segment_rows.append(row)
            prev = row["hash"]
        for event in tail_events:
            seq += 1
            row = _row(seq, event, prev, ts=RECENT_TS, caller="tests/tail")
            active_rows.append(row)
            prev = row["hash"]
        segment = self.path + ".20260901T000000.000001"
        _write(segment, segment_rows)
        _write(self.path, active_rows)
        return segment, segment_rows

    def ledger(self):
        return AutonomyLedger(self.path)


class ProtectionTests(CompactionFixture):
    def test_force_prune_of_an_aged_jev_eval_is_refused_with_its_class(self):
        _segment, rows = self.seal([
            {"event": "jev_eval", "caller": "tests/fixture", "verdict": "pass"}])
        verdict = compaction.classify(rows[0], now=_now_epoch())
        self.assertEqual(verdict["disposition"], "keep")
        self.assertEqual(verdict["reason"], "protected_class:jev_eval")
        ledger = self.ledger()
        result = ledger.sweep_compaction([_segment])[0]
        self.assertFalse(result["compacted"])
        self.assertEqual(result["reason"], "no eligible rows")
        # The row is still resolvable by its original hash after evaluation.
        self.assertIn(rows[0]["hash"], [e["hash"] for e in ledger.entries()])

    def test_unknown_event_is_protected_by_default(self):
        _segment, rows = self.seal([
            {"event": "brand_new_event", "caller": "tests/fixture"}])
        verdict = compaction.classify(rows[0], now=_now_epoch())
        self.assertEqual(verdict["reason"], "unknown_event")

    def test_a_prospective_citation_pins_the_row_permanently(self):
        _segment, rows = self.seal([
            {"event": "offer", "caller": "tests/fixture", "task_id": "t1"}])
        ledger = self.ledger()
        ledger.pin_citation(rows[0]["seq"], rows[0]["hash"], source="gate:test")
        verdict = compaction.classify(
            rows[0], now=_now_epoch(), pins=ledger.citation_pins)
        self.assertEqual(verdict["reason"], "cited")
        self.assertFalse(ledger.sweep_compaction([_segment])[0]["compacted"])
        # A later loader recovers the pin from the citation row itself.
        self.assertEqual(AutonomyLedger(self.path).citation_pins,
                         {(rows[0]["seq"], rows[0]["hash"])})

    def test_a_pinned_but_otherwise_eligible_row_still_stays(self):
        _segment, rows = self.seal([
            {"event": "offer", "caller": "tests/fixture", "task_id": "t1"}])
        verdict = compaction.classify(rows[0], now=_now_epoch(),
                                      pins={(rows[0]["seq"], rows[0]["hash"])})
        self.assertEqual(verdict["disposition"], "keep")


class EligibilityTests(CompactionFixture):
    def test_documented_phantom_compacts_and_a_lookalike_does_not(self):
        _segment, rows = self.seal([
            {"event": "defer_midtask", "caller": "tests/fixture",
             "task_id": "phantom-1", "harness_test": True}])
        unproven = compaction.classify(rows[0], now=_now_epoch())
        self.assertEqual(unproven["reason"], "unproven_phantom")
        proven = compaction.classify(
            rows[0], now=_now_epoch(),
            manifests={(rows[0]["seq"], rows[0]["hash"])})
        self.assertEqual(proven["disposition"], "drop")
        self.assertEqual(proven["reason"], "documented_phantom")

    def test_a_replacement_naming_the_exact_row_supersedes_it(self):
        _segment, rows = self.seal([
            {"event": "brief_built", "caller": "cli", "task_id": "t1",
             "artifact": "brief.md"}])
        replacement = _row(9, "brief_built", rows[0]["hash"], ts=OLD_TS,
                           task_id="t1",
                           supersedes={"seq": rows[0]["seq"],
                                       "hash": rows[0]["hash"]})
        verdict = compaction.classify(rows[0], now=_now_epoch(),
                                      rows=[replacement])
        self.assertEqual(verdict["reason"], "superseded")
        self.assertEqual(verdict["supporting_seq"], 9)
        # A replacement's own timestamp is the qualifying evidence, so a row
        # cannot be compacted 30 days after the replacement merely appears.
        fresh = _row(10, "brief_built", rows[0]["hash"],
                     ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     task_id="t1",
                     supersedes={"seq": rows[0]["seq"],
                                 "hash": rows[0]["hash"]})
        self.assertEqual(
            compaction.classify(rows[0], now=_now_epoch(),
                                rows=[fresh])["reason"], "insufficient_age")

    def test_the_thirty_day_boundary_is_a_full_month(self):
        _segment, rows = self.seal([
            {"event": "offer", "caller": "tests/fixture", "task_id": "t1"}])
        row_ts = compaction._parse_ts(rows[0]["ts"])
        just_short = row_ts + compaction.ELIGIBLE_AGE_SECONDS - 60
        self.assertEqual(
            compaction.classify(rows[0], now=just_short)["reason"],
            "insufficient_age")
        exactly = row_ts + compaction.ELIGIBLE_AGE_SECONDS
        self.assertEqual(
            compaction.classify(rows[0], now=exactly)["disposition"], "drop")

    def test_successful_canary_compacts_and_a_failed_one_stays(self):
        _segment, rows = self.seal([
            {"event": "canary_probe", "canary": True, "ok": True,
             "probe": "ledger_writable"},
            {"event": "canary_probe", "canary": True, "ok": False,
             "probe": "routing_resolves"}])
        self.assertEqual(compaction.classify(rows[0], now=_now_epoch())["reason"],
                         "canary_success")
        self.assertEqual(compaction.classify(rows[1], now=_now_epoch())["reason"],
                         "canary_not_successful")

    def test_a_row_without_a_usable_timestamp_is_never_aged_out(self):
        _segment, rows = self.seal([
            {"event": "offer", "caller": "tests/fixture", "task_id": "t1",
             "ts": "not-a-timestamp"}])
        self.assertEqual(compaction.classify(rows[0], now=_now_epoch())["reason"],
                         "insufficient_age")

    def test_a_consent_row_with_no_qualifying_case_is_kept(self):
        _segment, rows = self.seal([
            {"event": "consent_accept", "caller": "tests/fixture"}])
        self.assertEqual(compaction.classify(rows[0], now=_now_epoch())["reason"],
                         "no_qualifying_case")

    def test_an_untrusted_offer_is_kept_until_it_has_a_case(self):
        _segment, rows = self.seal([
            {"event": "offer", "caller": "cli", "task_id": "t1"}])
        self.assertEqual(compaction.classify(rows[0], now=_now_epoch())["reason"],
                         "no_qualifying_case")

    def test_harness_test_flag_is_trusted_provenance(self):
        _segment, rows = self.seal([
            {"event": "brief_built", "caller": "cli", "task_id": "t1",
             "harness_test": True}])
        self.assertEqual(compaction.classify(rows[0], now=_now_epoch())["reason"],
                         "test_provenance")


class CompactionIntegrationTests(CompactionFixture):
    def test_mixed_segment_compacts_appends_and_verifies_end_to_end(self):
        segment, rows = self.seal([
            {"event": "jev_eval", "caller": "tests/fixture", "verdict": "pass"},
            {"event": "canary_probe", "canary": True, "ok": True,
             "probe": "routing_resolves"},
            {"event": "brief_built", "caller": "cli", "task_id": "t2"},
        ])
        ledger = self.ledger()
        ok, _bad = ledger.verify()
        self.assertTrue(ok)
        result = ledger.sweep_compaction([segment])[0]
        self.assertTrue(result["compacted"])
        self.assertEqual(result["kept_count"], 2)
        self.assertEqual(result["dropped_count"], 1)
        checkpoint = result["checkpoint"]
        self.assertEqual(checkpoint["entry_count"], 3)
        self.assertEqual(checkpoint["policy_version"], compaction.POLICY_VERSION)
        archive_path = os.path.join(self.dir, "ledger-archive",
                                    os.path.basename(checkpoint["archive_ref"]))
        with open(archive_path, "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(),
                             checkpoint["segment_sha256"])
        self.assertTrue(compaction.verify_checkpoint(
            checkpoint, compaction.load_or_create_signing_key()))
        self.assertIn(checkpoint["signature_algorithm"], ("hmac-sha256",))
        fresh = AutonomyLedger(self.path)
        ok, bad = fresh.verify()
        self.assertTrue(ok, bad)
        status = fresh.chain_status()
        self.assertTrue(status["ok"])
        self.assertTrue(status["checkpoint_covered"])
        self.assertEqual(status["pruned_reason"], "checkpoint")
        self.assertEqual(len(status["checkpoint_covered"]), 1)
        # A receipt after an omitted run still resolves by its original hash.
        kept_hashes = {entry["hash"] for entry in fresh.entries()}
        self.assertIn(rows[0]["hash"], kept_hashes)
        self.assertIn(rows[2]["hash"], kept_hashes)
        self.assertNotIn(rows[1]["hash"], kept_hashes)

    def test_tampering_with_a_retained_row_fails_verification(self):
        segment, _rows = self.seal([
            {"event": "offer", "caller": "tests/fixture", "task_id": "t1"},
            {"event": "jev_eval", "caller": "tests/fixture", "verdict": "pass"},
        ])
        ledger = self.ledger()
        self.assertTrue(ledger.sweep_compaction([segment])[0]["compacted"])
        with open(segment, "rb") as handle:
            lines = handle.read().splitlines()
        entry = json.loads(lines[0])
        entry["verdict"] = "FORGED"
        _write(segment, [entry])
        fresh = AutonomyLedger(self.path)
        ok, bad = fresh.verify()
        self.assertFalse(ok)
        self.assertEqual(bad, entry["seq"])

    def test_a_tampered_coverage_boundary_no_longer_crosses(self):
        segment, _rows = self.seal([
            {"event": "offer", "caller": "tests/fixture", "task_id": "t1"},
            {"event": "jev_eval", "caller": "tests/fixture", "verdict": "pass"},
        ])
        ledger = self.ledger()
        self.assertTrue(ledger.sweep_compaction([segment])[0]["compacted"])
        checkpoints = [e for e in ledger.entries()
                       if e["event"] == "compaction_checkpoint"]
        forged = dict(checkpoints[0])
        forged["coverage_runs"] = [dict(forged["coverage_runs"][0],
                                        terminal_hash="0" * 64)]
        ok, bad = AutonomyLedger(self.path).verify()
        self.assertTrue(ok, bad)  # signature check ignores the forged copy
        self.assertFalse(compaction.verify_checkpoint(
            forged, compaction.load_or_create_signing_key()))

    def test_an_interrupted_compaction_leaves_the_source_available(self):
        segment, rows = self.seal([
            {"event": "offer", "caller": "tests/fixture", "task_id": "t1"},
            {"event": "jev_eval", "caller": "tests/fixture", "verdict": "pass"},
        ])
        with open(segment, "rb") as handle:
            before = handle.read()

        def boom(_checkpoint):
            raise OSError("disk full")

        with self.assertRaises(OSError):
            compaction.compact_segment(
                segment, archive_dir=os.path.join(self.dir, "archive"),
                ledger_id="ledger.jsonl",
                evaluated_at=datetime.now(timezone.utc),
                previous_checkpoint_hash=None,
                key=compaction.load_or_create_signing_key(),
                append_checkpoint=boom, pins=set())
        # Failure before the switch: the full source is still there, and the
        # archive holds the exact bytes for a retry or a restore.
        with open(segment, "rb") as handle:
            self.assertEqual(handle.read(), before)
        archives = os.listdir(os.path.join(self.dir, "archive"))
        self.assertEqual(len(archives), 1)
        self.assertEqual(len(rows), 2)

    def test_undo_restores_the_exact_bytes_and_appends_a_receipt(self):
        segment, rows = self.seal([
            {"event": "offer", "caller": "tests/fixture", "task_id": "t1"},
            {"event": "jev_eval", "caller": "tests/fixture", "verdict": "pass"},
        ])
        with open(segment, "rb") as handle:
            original = handle.read()
        ledger = self.ledger()
        result = ledger.sweep_compaction([segment])[0]
        archive_path = os.path.join(self.dir, "ledger-archive",
                                    os.path.basename(result["archive_ref"]))
        restored = compaction.restore_segment(
            archive_path, segment, result["checkpoint"]["segment_sha256"])
        self.assertTrue(restored["restored"])
        with open(segment, "rb") as handle:
            self.assertEqual(handle.read(), original)
        receipt = ledger.append("restoration",
                                 segment=os.path.basename(segment),
                                 checkpoint_seq=result["checkpoint"]["seq"],
                                 segment_sha256=restored["segment_sha256"])
        self.assertEqual(receipt["event"], "restoration")
        reloaded = AutonomyLedger(self.path)
        self.assertIn(rows[0]["hash"],
                      [entry["hash"] for entry in reloaded.entries()])

    def test_a_restore_is_refused_when_the_archive_no_longer_matches(self):
        segment, _rows = self.seal([
            {"event": "offer", "caller": "tests/fixture", "task_id": "t1"}])
        ledger = self.ledger()
        result = ledger.sweep_compaction([segment])[0]
        archive_path = os.path.join(self.dir, "ledger-archive",
                                    os.path.basename(result["archive_ref"]))
        with open(archive_path, "ab") as handle:
            handle.write(b"tamper")
        with self.assertRaises(HarnessError):
            compaction.restore_segment(archive_path, segment,
                                       result["checkpoint"]["segment_sha256"])

    def test_an_empty_segment_is_refused(self):
        segment = self.path + ".20260901T000000.000002"
        _write(segment, [])
        ledger = self.ledger()
        result = ledger.sweep_compaction([segment])[0]
        self.assertFalse(result["compacted"])
        self.assertIn("empty segment", ledger.compaction_error)

    def test_a_missing_signing_key_fails_closed_on_the_gap(self):
        segment, _rows = self.seal([
            {"event": "jev_eval", "caller": "tests/fixture", "verdict": "pass"},
            {"event": "canary_probe", "canary": True, "ok": True,
             "probe": "routing_resolves"},
            {"event": "offer", "caller": "cli", "task_id": "t1"},
        ])
        ledger = self.ledger()
        self.assertTrue(ledger.sweep_compaction([segment])[0]["compacted"])
        os.unlink(self.key_path)
        ok, bad = AutonomyLedger(self.path).verify()
        self.assertFalse(ok)
        self.assertIsNotNone(bad)
        self.assertEqual(compaction.existing_signing_key(), b"")

    def test_tampering_with_a_signed_field_breaks_the_checkpoint(self):
        _segment, _rows = self.seal([
            {"event": "jev_eval", "caller": "tests/fixture", "verdict": "pass"},
            {"event": "canary_probe", "canary": True, "ok": True,
             "probe": "routing_resolves"},
            {"event": "offer", "caller": "cli", "task_id": "t1"},
        ])
        result = self.ledger().sweep_compaction([_segment])[0]
        key = compaction.load_or_create_signing_key()
        self.assertTrue(compaction.verify_checkpoint(result["checkpoint"], key))
        forged = dict(result["checkpoint"], dropped_count=0)
        self.assertFalse(compaction.verify_checkpoint(forged, key))

    def test_a_wrong_key_never_verifies_a_checkpoint(self):
        segment, _rows = self.seal([
            {"event": "offer", "caller": "tests/fixture", "task_id": "t1"},
            {"event": "jev_eval", "caller": "tests/fixture", "verdict": "pass"},
        ])
        result = self.ledger().sweep_compaction([segment])[0]
        checkpoint = result["checkpoint"]
        other = os.urandom(32)
        self.assertFalse(compaction.verify_checkpoint(checkpoint, other))
        forged = dict(checkpoint, signer_key_id=compaction.key_id(other))
        self.assertFalse(compaction.verify_checkpoint(forged, other))
        self.assertFalse(compaction.verify_checkpoint(None, other))

    def test_archive_read_back_failure_is_an_error(self):
        data = b"{}\n"
        real = compaction._sha256
        calls = {"n": 0}

        def flaky(payload):
            calls["n"] += 1
            return real(payload) if calls["n"] == 1 else "0" * 64

        with mock.patch.object(compaction, "_sha256", side_effect=flaky):
            with self.assertRaises(HarnessError):
                compaction.archive_segment(data, os.path.join(self.dir, "arch"),
                                           "seg")


class CanaryTests(CompactionFixture):
    def test_fresh_install_accrues_labelled_canaries_with_no_history(self):
        ledger = self.ledger()
        self.assertEqual(ledger.entries(), [])
        outcomes = ledger.run_canaries(trigger="startup")
        self.assertTrue(outcomes)
        rows = [entry for entry in ledger.entries()
                if entry["event"] == ledger_canary.CANARY_EVENT]
        self.assertEqual(len(rows), len(outcomes))
        self.assertTrue(all(row["canary"] is True for row in rows))
        self.assertTrue(all(outcome["read_back"] for outcome in outcomes))
        statuses = {row["probe"]: row["status"] for row in rows}
        self.assertEqual(statuses["routing_resolves"], "ok")
        self.assertEqual(statuses["jev_reachable"], "skipped")
        self.assertEqual(statuses["key_gates_green"], "ok")
        self.assertEqual(statuses["mcp_tools_respond"], "skipped")
        # No billed call was made: the ledger only holds canary rows.
        self.assertEqual({row["event"] for row in ledger.entries()},
                         {ledger_canary.CANARY_EVENT})

    def test_canary_rows_never_reach_the_shared_evidence_reader(self):
        ledger = self.ledger()
        ledger.run_canaries()
        ledger.append("model_result", model="m", ok=True, canary=True)
        ledger.append("model_result", model="m", ok=True)
        events = [entry["event"] for entry in ledger.evidence_rows()]
        self.assertEqual(events, ["model_result"])
        self.assertEqual(len(ledger.evidence_rows()), 1)

    def test_a_raising_probe_is_recorded_as_failed(self):
        def explode(_ledger):
            raise RuntimeError("probe blew up")

        ledger = self.ledger()
        outcomes = ledger.run_canaries(probes={"boom": explode})
        self.assertEqual(outcomes[0]["status"], "failed")
        self.assertIn("probe blew up", outcomes[0]["detail"])
        self.assertFalse(outcomes[0]["ok"])

    def test_an_unwritable_ledger_reports_through_local_diagnostics(self):
        ledger = self.ledger()

        def unwritable(*_args, **_kwargs):
            raise OSError("read-only filesystem")

        ledger.append = unwritable
        outcomes = ledger_canary.run_canaries(ledger)
        self.assertFalse(any(outcome["appended"] for outcome in outcomes))
        self.assertIn("read-only filesystem", ledger.canary_error)

    def test_mcp_health_runs_only_when_an_allowlisted_operation_is_supplied(self):
        ledger = self.ledger()
        skipped = ledger.run_canaries()
        self.assertEqual(skipped[-1]["status"], "skipped")
        ledger2 = AutonomyLedger(self.path)
        ran = ledger2.run_canaries(
            mcp_health=lambda _ledger: {"status": "ok", "detail": "tools/list"})
        self.assertEqual(ran[-1]["status"], "ok")

    def test_triggers_are_startup_daily_and_six_hour_staleness(self):
        ledger = self.ledger()
        first = ledger_canary.should_run_canaries(ledger)
        self.assertTrue(first["run"])
        self.assertIn("empty_ledger", first["reasons"])
        self.assertIn("never_ran", first["reasons"])
        ledger.append("offer", task_id="t1", model="m")
        now = datetime.now(timezone.utc).timestamp()
        self.assertFalse(ledger_canary.should_run_canaries(
            ledger, now=now, last_run_epoch=now)["run"])
        stale = ledger_canary.should_run_canaries(
            ledger, now=now + ledger_canary.STALE_SECONDS + 1,
            last_run_epoch=now)
        self.assertIn("stale", stale["reasons"])
        daily = ledger_canary.should_run_canaries(
            ledger, now=now + 86400 * 2, last_run_epoch=now)
        self.assertIn("daily", daily["reasons"])
        startup = ledger_canary.should_run_canaries(
            ledger, now=now, last_run_epoch=now, startup=True)
        self.assertTrue(startup["run"])

    def test_canary_summary_reports_ran_and_empty(self):
        ledger = self.ledger()
        self.assertFalse(ledger_canary.canary_summary(ledger)["ran"])
        ledger.run_canaries()
        summary = ledger_canary.canary_summary(ledger)
        self.assertTrue(summary["ran"])
        self.assertTrue(summary["probes"])
        self.assertIn("ok", summary["by_status"])

    def test_should_run_with_no_entries_and_no_clock_side_effects(self):
        ledger = self.ledger()
        self.assertTrue(ledger_canary.should_run_canaries(
            ledger, now=_now_epoch())["run"])


class RotationWiringTests(CompactionFixture):
    def test_rotation_evaluates_instead_of_deleting_and_keeps_protected_rows(self):
        import harness.ledger as ledger_mod
        old_max = ledger_mod.LEDGER_MAX_BYTES
        old_keep = ledger_mod.LEDGER_KEEP_ROTATIONS
        ledger_mod.LEDGER_MAX_BYTES = 200
        ledger_mod.LEDGER_KEEP_ROTATIONS = 0
        self.addCleanup(setattr, ledger_mod, "LEDGER_MAX_BYTES", old_max)
        self.addCleanup(setattr, ledger_mod, "LEDGER_KEEP_ROTATIONS", old_keep)
        ledger = self.ledger()
        for i in range(4):
            ledger.append("jev_eval", verdict="pass", index=i)
        # Size alone never retires a segment: every row here is protected.
        self.assertTrue(ledger._rotated_paths())
        for path in ledger._rotated_paths():
            self.assertTrue(os.path.exists(path))
        ok, bad = ledger.verify()
        self.assertTrue(ok, bad)
        status = ledger.chain_status()
        self.assertFalse(status["checkpoint_covered"])

    def test_size_only_eviction_is_gone(self):
        import harness.ledger as ledger_mod
        old_max = ledger_mod.LEDGER_MAX_BYTES
        old_keep = ledger_mod.LEDGER_KEEP_ROTATIONS
        ledger_mod.LEDGER_MAX_BYTES = 200
        ledger_mod.LEDGER_KEEP_ROTATIONS = 0
        self.addCleanup(setattr, ledger_mod, "LEDGER_MAX_BYTES", old_max)
        self.addCleanup(setattr, ledger_mod, "LEDGER_KEEP_ROTATIONS", old_keep)
        ledger = self.ledger()
        ledger.append("offer", task_id="t1", model="m")
        ledger.append("offer", task_id="t2", model="m")
        segments = list(ledger._rotated_paths())
        self.assertTrue(segments)
        # The rotator called the evaluator; with protected/unproven rows the
        # segment is still on disk and the chain still verifies.
        self.assertTrue(all(os.path.exists(path) for path in segments))
        self.assertTrue(ledger.verify()[0])



class DegradePathTests(CompactionFixture):
    """Every refusal path states its reason; none of them silently passes."""

    def test_rotation_degrades_when_the_active_file_cannot_be_sized_or_moved(self):
        import harness.ledger as ledger_mod
        ledger = self.ledger()
        ledger.append("offer", task_id="t1", model="m")
        with mock.patch.object(ledger_mod.os.path, "getsize",
                               side_effect=OSError("gone")):
            self.assertEqual(ledger._rotate_if_needed(), [])
        old_max = ledger_mod.LEDGER_MAX_BYTES
        ledger_mod.LEDGER_MAX_BYTES = 0
        self.addCleanup(setattr, ledger_mod, "LEDGER_MAX_BYTES", old_max)
        with mock.patch.object(ledger_mod.os, "replace",
                               side_effect=OSError("busy")):
            self.assertEqual(ledger._rotate_if_needed(), [])
        self.assertTrue(ledger.verify()[0])

    def test_naive_and_unparsable_timestamps_are_handled_everywhere(self):
        self.assertIsNone(ledger_canary._parse_ts("nope"))
        self.assertIsNone(compaction._parse_ts("nope"))
        self.assertIsNotNone(ledger_canary._parse_ts("2026-01-01T00:00:00"))
        self.assertIsNotNone(compaction._parse_ts("2026-01-01T00:00:00"))

    def test_routing_probe_reports_a_resolver_that_returns_no_window(self):
        with mock.patch("harness.dynamic_allocation.resolve_model_spec",
                        return_value=object()):
            result = ledger_canary.routing_resolves()
        self.assertEqual(result["status"], "failed")

    def test_key_gate_probe_reports_a_broken_chain(self):
        ledger = self.ledger()
        ledger.append("offer", task_id="t1", model="m")
        with open(self.path, "ab") as handle:
            handle.write(b'{"seq": 99, "hash": "deadbeef"}' + bytes([10]))
        broken = AutonomyLedger(self.path)
        result = ledger_canary.key_gates_green(broken)
        self.assertEqual(result["status"], "failed")

    def test_checkpoint_verification_rejects_each_missing_envelope_field(self):
        key = compaction.load_or_create_signing_key()
        _segment, rows = self.seal([
            {"event": "jev_eval", "caller": "tests/fixture", "verdict": "pass"},
            {"event": "canary_probe", "canary": True, "ok": True,
             "probe": "routing_resolves"},
        ])
        checkpoint = self.ledger().sweep_compaction([_segment])[0]["checkpoint"]
        wrong_alg = dict(checkpoint, signature_algorithm="none")
        self.assertFalse(compaction.verify_checkpoint(wrong_alg, key))
        unsigned = dict(checkpoint, signature="")
        self.assertFalse(compaction.verify_checkpoint(unsigned, key))
        self.assertEqual(compaction.gap_runs([wrong_alg], key), [])
        self.assertFalse(compaction.crosses_gap(0, None, {"seq": "x"}, []))

    def test_segment_rows_ignores_blank_lines(self):
        rows, raw = compaction.segment_rows(bytes([10, 10]))
        self.assertEqual(rows, [])
        self.assertEqual(raw, {})

    def test_a_failing_cleanup_does_not_mask_the_append_error(self):
        segment, _rows = self.seal([
            {"event": "jev_eval", "caller": "tests/fixture", "verdict": "pass"},
            {"event": "canary_probe", "canary": True, "ok": True,
             "probe": "routing_resolves"},
        ])

        def boom(_checkpoint):
            raise OSError("disk full")

        with mock.patch.object(compaction.os, "unlink",
                               side_effect=OSError("cannot unlink")):
            with self.assertRaises(OSError):
                compaction.compact_segment(
                    segment, archive_dir=os.path.join(self.dir, "arch"),
                    ledger_id="ledger.jsonl",
                    evaluated_at=datetime.now(timezone.utc),
                    previous_checkpoint_hash=None,
                    key=compaction.load_or_create_signing_key(),
                    append_checkpoint=boom, pins=set())


if __name__ == "__main__":
    unittest.main()
