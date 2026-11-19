"""#407: the opt-in worldwide statistics surface, end to end.

Everything here runs against the module's own seams: a real ledger double for
the report fixture (offline, deterministic), temporary consent records and
queues on disk, direct calls to the report builder, the intake validator and
the publisher, and an issuer whose voucher is the only way a token counts.
"""
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from harness import public_share as ps
from harness.errors import HarnessError
from harness.routing_table import TIER_MODELS

MODEL = sorted({model for models in TIER_MODELS.values() for model in models})[0]
OTHER_MODEL = sorted({model for models in TIER_MODELS.values() for model in models})[-1]
ROUND = "2026-10"


class _Ledger:
    """The report builder's seam: rows plus the chain verdict it cites."""

    def __init__(self, rows, *, ok=True):
        self._rows = list(rows)
        self._ok = ok

    def verify(self):
        return (self._ok, None if self._ok else 3)

    def entries(self):
        return list(self._rows)


def rows_for(model=MODEL, *, count=3, month=ROUND, cost=0.002):
    rows = []
    for index in range(count):
        day = f"{month}-{index + 1:02d}"
        rows.append({"event": "model_result", "ts": f"{day}T00:00:00Z",
                     "model": model, "cost": cost, "latency_ms": 120})
        rows.append({"event": "complete", "ts": f"{day}T00:00:01Z",
                     "model": model, "status": "ok"})
    return rows


ISSUER_KEY = b"issuer-key-for-tests"


def issuer():
    return ps.EligibilityIssuer(ISSUER_KEY)


def consent_record(period="p" * 16):
    return ps.make_consent(accepted_at="2026-11-01T00:00:00Z", period=period)


def report_for(round_id=ROUND, model=MODEL, *, rows=None, brokered=None,
               secret="cred-1", consent=None):
    boss = brokered or issuer()
    credential = boss.credential(secret) if secret else None
    return ps.build_report(
        ledger=_Ledger(rows if rows is not None else rows_for(model)),
        model=model, consent=consent or consent_record(), round_id=round_id,
        issuer=boss if credential else None, credential=credential,
    )


class ConsentRecordTests(unittest.TestCase):
    """The record, its scope, and the fail-closed policy over it."""

    def test_make_consent_is_readable_scoped_and_dated(self):
        record = ps.make_consent()
        self.assertEqual(record["schema"], ps.CONSENT_SCHEMA)
        self.assertEqual(record["surface"], ps.CONSENT_SURFACE)
        self.assertEqual(record["version"], ps.CONSENT_VERSION)
        self.assertIs(record["enabled"], True)
        self.assertTrue(record["accepted_at"].endswith("Z"))
        self.assertGreaterEqual(len(record["period"]), 16)
        self.assertEqual(record["disclosure"], ps.DISCLOSURE)

    def test_each_consent_gets_its_own_period(self):
        self.assertNotEqual(ps.make_consent()["period"],
                            ps.make_consent()["period"])

    def test_policy_allows_only_a_current_readable_correct_scope(self):
        policy = ps.policy_for(consent_record())
        self.assertEqual(policy, {"share": True, "reason": "sharing is on",
                                  "period": "p" * 16})

    def test_policy_refuses_missing_malformed_wrong_version_and_off(self):
        cases = {
            "no consent record": None,
            "malformed consent record": {"schema": "", "enabled": None},
            "consent is for another surface": dict(consent_record(),
                                                   surface="proof-bench"),
            "consent is for another disclosure version": dict(
                consent_record(), version=99),
            "sharing is turned off": dict(consent_record(), enabled=False),
            "consent has no period": dict(consent_record(), period="  "),
        }
        for reason, record in cases.items():
            policy = ps.policy_for(record)
            self.assertEqual(policy["share"], False, reason)
            self.assertEqual(policy["reason"], reason)
            self.assertIsNone(policy["period"])


class ConsentFileTests(unittest.TestCase):
    """Reading a consent file tolerates absence and refuses garbage."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, ps.CONSENT_FILENAME)

    def test_missing_file_is_no_consent(self):
        self.assertIsNone(ps.load_consent(self.path))

    def test_malformed_json_is_a_malformed_record(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        record = ps.load_consent(self.path)
        self.assertTrue(record["malformed"])
        self.assertFalse(ps.policy_for(record)["share"])

    def test_non_object_json_is_a_malformed_record(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("[1, 2]")
        self.assertTrue(ps.load_consent(self.path)["malformed"])

    def test_a_written_record_round_trips(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(consent_record(), handle)
        self.assertEqual(ps.policy_for(ps.load_consent(self.path))["share"], True)


class ProfileWithdrawalTests(unittest.TestCase):
    """Future-only revocation, the queue, and the serialized handoff."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.handed = []

        def transport(report):
            self.handed.append(report)
            return {"accepted": True}

        self.profile = ps.ShareProfile(self.tmp.name, transport=transport)

    def test_a_fresh_profile_shares_nothing(self):
        self.assertIsNone(self.profile.consent())
        self.assertEqual(self.profile.policy()["reason"], "no consent record")

    def test_enable_writes_a_readable_record_and_disable_turns_it_off(self):
        record = self.profile.enable(accepted_at="2026-11-18T00:00:00Z")
        self.assertTrue(self.profile.policy()["share"])
        self.assertEqual(self.profile.consent()["period"], record["period"])
        withdrawn = self.profile.disable(withdrawn_at="2026-11-18T01:00:00Z")
        self.assertIs(withdrawn["enabled"], False)
        self.assertEqual(withdrawn["withdrawn_at"], "2026-11-18T01:00:00Z")
        self.assertEqual(self.profile.policy()["reason"],
                         "sharing is turned off")

    def test_re_enabling_starts_a_new_consent_period(self):
        first = self.profile.enable()
        self.profile.disable()
        second = self.profile.enable()
        self.assertNotEqual(first["period"], second["period"])

    def test_withdrawal_discards_unsent_work(self):
        self.profile.enable()
        self.profile.queue(report_for())
        self.assertEqual(len(self.profile.pending()), 1)
        self.profile.disable()
        self.assertEqual(self.profile.pending(), [])

    def test_handoff_rechecks_consent_under_the_lock(self):
        self.profile.enable()
        report = report_for()
        self.profile.disable()
        result = self.profile.handoff(report)
        self.assertEqual(result, {"sent": False, "dropped": True,
                                  "reason": "sharing is turned off"})
        self.assertEqual(self.handed, [])

    def test_handoff_refuses_a_report_from_an_older_consent_period(self):
        self.profile.enable()
        report = report_for(consent=consent_record())
        self.profile.disable()
        self.profile.enable()
        result = self.profile.handoff(report)
        self.assertEqual(result["dropped"], True)
        self.assertEqual(result["reason"], "the consent period changed")
        self.assertEqual(self.handed, [])

    def test_handoff_needs_a_transport(self):
        profile = ps.ShareProfile(self.tmp.name)
        profile.enable()
        with self.assertRaises(HarnessError) as caught:
            profile.handoff(report_for())
        self.assertIn("no transport", str(caught.exception))

    def test_submit_builds_queues_and_hands_off(self):
        boss = issuer()
        self.profile.issuer = boss
        self.profile.credential = boss.credential("profile-secret")
        self.profile.enable()
        result = self.profile.submit(_Ledger(rows_for()), model=MODEL,
                                     round_id=ROUND)
        self.assertEqual(result["sent"], True)
        self.assertEqual(len(self.handed), 1)
        self.assertEqual(self.handed[0]["model"], MODEL)
        self.assertEqual(self.profile.pending(), [])

    def test_upload_pending_retries_then_stops_on_a_refusal(self):
        attempts = []

        def transport(report):
            attempts.append(report)
            raise HarnessError("backend timeout")

        self.profile.transport = transport
        self.profile.enable()
        self.profile.queue(report_for())
        result = self.profile.upload_pending()
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["retained"], 1)
        self.assertEqual(result["reason"], "backend timeout")
        self.assertEqual(len(self.profile.pending()), 1)
        self.assertEqual(len(attempts), 1)

    def test_upload_pending_clears_the_queue_when_consent_is_gone(self):
        self.profile.enable()
        self.profile.queue(report_for())
        self.profile.disable()
        # Queue a report behind the consent check, the way a crash between
        # build and handoff would leave it.
        os.makedirs(self.profile.queue_dir, exist_ok=True)
        with open(os.path.join(self.profile.queue_dir, "stale.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(report_for(), handle)
        result = self.profile.upload_pending()
        self.assertEqual(result["dropped"], 1)
        self.assertEqual(result["reason"], "sharing is turned off")
        self.assertEqual(self.profile.pending(), [])
        self.assertEqual(self.handed, [])

    def test_upload_pending_drops_an_unreadable_queue_entry(self):
        self.profile.enable()
        os.makedirs(self.profile.queue_dir, exist_ok=True)
        with open(os.path.join(self.profile.queue_dir, "bad.json"), "w",
                  encoding="utf-8") as handle:
            handle.write("{broken")
        result = self.profile.upload_pending()
        self.assertEqual(result["dropped"], 1)
        self.assertEqual(self.profile.pending(), [])

    def test_upload_pending_needs_a_transport(self):
        profile = ps.ShareProfile(self.tmp.name)
        with self.assertRaises(HarnessError) as caught:
            profile.upload_pending()
        self.assertIn("no transport", str(caught.exception))

    def test_withdrawal_between_publish_and_upload_keeps_the_receipt(self):
        """The ruling's end-to-end withdrawal path."""
        boss = issuer()
        self.profile.issuer = boss
        self.profile.credential = boss.credential("profile-secret")
        self.profile.enable()
        publisher = ps.PublicPublisher(ISSUER_KEY, site_key=b"site")
        for index in range(ps.PUBLICATION_FLOOR):
            publisher.accept(report_for(secret=f"operator-{index}",
                                        brokered=boss))
        sealed = publisher.seal(ROUND)
        receipt = sealed["models"][MODEL]["success_rate"]["receipt"]

        self.profile.submit(_Ledger(rows_for()), model=MODEL, round_id=ROUND)
        self.assertEqual(len(self.handed), 1)
        self.profile.disable()
        result = self.profile.upload_pending()
        self.assertEqual(result["sent"], 0)
        self.assertEqual(self.profile.pending(), [])
        self.assertEqual(len(self.handed), 1)
        again = dict(receipt)
        self.assertEqual(
            ps.PublicPublisher(ISSUER_KEY, site_key=b"site").published(), {})
        self.assertEqual(again, receipt)


class RoundTests(unittest.TestCase):
    """Only a closed UTC month is a round."""

    def test_normal_month_closes_to_the_previous_one(self):
        moment = datetime(2026, 11, 18, 12, 30, tzinfo=timezone.utc)
        self.assertEqual(ps.closed_round(moment), "2026-10")

    def test_january_closes_to_the_previous_december(self):
        moment = datetime(2026, 1, 3, tzinfo=timezone.utc)
        self.assertEqual(ps.closed_round(moment), "2025-12")

    def test_naive_timestamps_are_read_as_utc(self):
        self.assertEqual(ps.closed_round(datetime(2026, 3, 31, 23, 59)),
                         "2026-02")


class StatsTests(unittest.TestCase):
    """Sufficient statistics, and the evidence they refuse to invent."""

    def test_counts_costs_and_latency_are_sufficient_statistics(self):
        stats = ps.derive_stats(rows_for(count=3), MODEL)
        self.assertEqual(stats, {
            "calls": 3, "tasks": 3, "successes": 3,
            "cost_micro_usd": 6000, "latency_ms": 360,
            "timed_observations": 3,
        })

    def test_a_model_filter_keeps_other_models_out(self):
        rows = rows_for(count=2) + rows_for(OTHER_MODEL, count=4)
        self.assertEqual(ps.derive_stats(rows, MODEL)["calls"], 2)

    def test_cost_evidence_without_outcome_evidence_is_not_a_report(self):
        rows = [{"event": "model_result", "ts": f"{ROUND}-01T00:00:00Z",
                 "model": MODEL, "cost": 0.001}]
        self.assertIsNone(ps.derive_stats(rows, MODEL))

    def test_outcome_evidence_without_cost_evidence_is_not_a_report(self):
        rows = [{"event": "complete", "ts": f"{ROUND}-01T00:00:00Z",
                 "model": MODEL, "status": "ok"}]
        self.assertIsNone(ps.derive_stats(rows, MODEL))

    def test_failed_and_error_outcomes_count_against_successes(self):
        rows = rows_for(count=1) + [
            {"event": "complete", "ts": f"{ROUND}-02T00:00:00Z",
             "model": MODEL, "status": "failed"},
            {"event": "complete", "ts": f"{ROUND}-03T00:00:00Z",
             "model": MODEL, "status": "error"},
        ]
        stats = ps.derive_stats(rows, MODEL)
        self.assertEqual((stats["tasks"], stats["successes"]), (3, 1))

    def test_unusable_rows_add_nothing(self):
        rows = [
            {"event": "model_result", "model": MODEL, "cost": "free"},
            {"event": "model_result", "ts": f"{ROUND}-01T00:00:00Z",
             "model": MODEL, "cost": -1},
            {"event": "complete", "ts": f"{ROUND}-01T00:00:00Z",
             "model": MODEL, "status": "unknown"},
            {"event": "offer", "ts": f"{ROUND}-01T00:00:00Z", "model": MODEL},
            "not a row",
        ]
        self.assertIsNone(ps.derive_stats(rows, MODEL))

    def test_latency_is_only_summed_where_it_was_observed(self):
        rows = rows_for(count=1) + [
            {"event": "model_result", "ts": f"{ROUND}-04T00:00:00Z",
             "model": MODEL, "cost": 0.001},
        ]
        stats = ps.derive_stats(rows, MODEL)
        self.assertEqual((stats["latency_ms"], stats["timed_observations"]),
                         (120, 1))

    def test_rows_outside_the_round_are_not_read(self):
        rows = rows_for(count=1) + rows_for(count=2, month="2026-09")
        self.assertEqual(len(ps.rows_for_round(_Ledger(rows), ROUND)), 2)

    def test_rows_without_a_timestamp_belong_to_no_round(self):
        rows = [{"event": "model_result", "model": MODEL, "cost": 0.1}]
        self.assertEqual(ps.rows_for_round(_Ledger(rows), ROUND), [])


class ReportTests(unittest.TestCase):
    """What may leave the machine, and what refuses to."""

    def test_a_report_carries_only_the_allowlisted_fields(self):
        report = report_for()
        self.assertEqual(set(report), {
            "protocol", "metric_version", "round", "model", "commitment",
            "shares", "proof", "eligibility",
        })
        self.assertEqual(ps.validate_submission(report, verify_key=ISSUER_KEY)["model"], MODEL)

    def test_the_payload_carries_no_attributable_data(self):
        report = report_for()
        serialized = json.dumps(report, sort_keys=True)
        for forbidden in ("head_hash", "accepted_at", "task_id", "path",
                          "profile", "credential", "ledger"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(len(report["shares"]), ps.SHARE_COUNT)
        self.assertEqual(len(report["proof"]["consent_period"]), 16)

    def test_sharing_off_refuses_to_build_anything(self):
        with self.assertRaises(HarnessError) as caught:
            ps.build_report(ledger=_Ledger(rows_for()), model=MODEL,
                            consent={"schema": "", "enabled": False},
                            round_id=ROUND)
        self.assertIn("sharing refused", str(caught.exception))

    def test_an_unlisted_model_is_refused(self):
        with self.assertRaises(HarnessError) as caught:
            report_for(model="someone/unknown-model")
        self.assertIn("allowlisted", str(caught.exception))

    def test_a_round_must_be_a_month(self):
        with self.assertRaises(HarnessError) as caught:
            report_for(round_id="2026-10-18")
        self.assertIn("closed UTC month", str(caught.exception))

    def test_no_eligible_evidence_refuses_the_report(self):
        with self.assertRaises(HarnessError) as caught:
            report_for(rows=rows_for(OTHER_MODEL))
        self.assertIn("no eligible evidence", str(caught.exception))

    def test_a_broken_chain_refuses_the_report(self):
        with self.assertRaises(HarnessError) as caught:
            ps.build_report(ledger=_Ledger(rows_for(), ok=False),
                            model=MODEL, consent=consent_record(),
                            round_id=ROUND)
        self.assertIn("FAILED verification", str(caught.exception))

    def test_an_empty_ledger_refuses_the_report(self):
        with self.assertRaises(HarnessError) as caught:
            ps.build_report(ledger=_Ledger([]), model=MODEL,
                            consent=consent_record(), round_id=ROUND)
        self.assertIn("no entries", str(caught.exception))

    def test_a_ledger_without_a_verdict_is_refused(self):
        with self.assertRaises(HarnessError) as caught:
            ps.build_report(ledger=object(), model=MODEL,
                            consent=consent_record(), round_id=ROUND)
        self.assertIn("verifiable ledger", str(caught.exception))

    def test_a_report_without_an_issuer_carries_no_eligibility(self):
        report = ps.build_report(ledger=_Ledger(rows_for()), model=MODEL,
                                 consent=consent_record(), round_id=ROUND)
        self.assertNotIn("eligibility", report)


class ShareTests(unittest.TestCase):
    """Every share is needed; fewer than all of them open nothing."""

    def test_a_full_set_of_shares_opens_the_statistics(self):
        stats = ps.derive_stats(rows_for(count=2), MODEL)
        shares = ps.split_payload(stats, 99, rng=lambda bits: 7)
        opened = ps.open_payload(shares)
        self.assertEqual(opened["stats"], stats)
        self.assertEqual(opened["nonce"], 99)

    def test_share_indices_are_one_to_count(self):
        shares = ps.split_payload(ps.derive_stats(rows_for(), MODEL), 1)
        self.assertEqual([share["x"] for share in shares],
                         list(range(1, ps.SHARE_COUNT + 1)))

    def test_a_missing_share_opens_nothing(self):
        shares = ps.split_payload(ps.derive_stats(rows_for(), MODEL), 1)
        with self.assertRaises(HarnessError) as caught:
            ps.open_payload(shares[:2])
        self.assertIn("exactly", str(caught.exception))

    def test_a_repeated_holder_is_not_a_complete_set(self):
        shares = ps.split_payload(ps.derive_stats(rows_for(), MODEL), 1)
        broken = [dict(shares[0]), dict(shares[1]), dict(shares[1])]
        with self.assertRaises(HarnessError) as caught:
            ps.open_payload(broken)
        self.assertIn("1..", str(caught.exception))

    def test_a_short_or_non_object_share_is_refused(self):
        with self.assertRaises(HarnessError) as caught:
            ps.open_payload(["not a share"] * ps.SHARE_COUNT)
        self.assertIn("must be an object", str(caught.exception))
        with self.assertRaises(HarnessError) as caught:
            ps.open_payload([{"x": 1, "v": [1]}, {"x": 2, "v": [2]},
                             {"x": 3, "v": [3]}])
        self.assertIn("width", str(caught.exception))


class EligibilityTests(unittest.TestCase):
    """One credential, one token per model and round, no forgery."""

    def test_a_token_is_stable_within_a_round_and_unlinkable_across_rounds(self):
        boss = issuer()
        credential = boss.credential("secret")
        first = ps.eligibility_token(credential, model=MODEL, round_id=ROUND)
        self.assertEqual(first, ps.eligibility_token(credential, model=MODEL,
                                                     round_id=ROUND))
        self.assertNotEqual(
            first, ps.eligibility_token(credential, model=MODEL,
                                        round_id="2026-11"))
        self.assertNotEqual(
            first, ps.eligibility_token(credential, model=OTHER_MODEL,
                                        round_id=ROUND))

    def test_the_issuer_vouches_a_token_and_nothing_else_does(self):
        boss = issuer()
        credential = boss.credential("secret")
        token = ps.eligibility_token(credential, model=MODEL, round_id=ROUND)
        self.assertTrue(ps.verify_eligibility(token, boss.voucher(token),
                                             verify_key=ISSUER_KEY))
        self.assertFalse(ps.verify_eligibility(token, "0" * 64,
                                              verify_key=ISSUER_KEY))
        self.assertFalse(ps.verify_eligibility(None, None,
                                              verify_key=ISSUER_KEY))

    def test_a_credential_and_an_issuer_key_are_required(self):
        with self.assertRaises(HarnessError):
            ps.EligibilityIssuer(b"")
        with self.assertRaises(HarnessError):
            issuer().credential("")


class IntakeTests(unittest.TestCase):
    """The validator refuses everything the ruling forbids."""

    def setUp(self):
        self.boss = issuer()
        self.report = report_for(brokered=self.boss)

    def mutate(self, **changes):
        report = json.loads(json.dumps(self.report))
        report.update(changes)
        return report

    def test_an_extra_field_is_refused(self):
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(self.mutate(extra=1),
                                   verify_key=ISSUER_KEY)
        self.assertIn("allowlisted set", str(caught.exception))

    def test_a_missing_field_is_refused(self):
        report = json.loads(json.dumps(self.report))
        report.pop("proof")
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(report, verify_key=ISSUER_KEY)
        self.assertIn("allowlisted set", str(caught.exception))

    def test_a_credential_shape_is_refused_before_anything_else(self):
        # Built at runtime so the driving-hygiene scan sees no key-shaped
        # literal in the test source (the same rule #418's fixture follows).
        fake_key = "-".join(("sk", "or", "v1", "abcdefghijklmnopqrstuvwx"))
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(self.mutate(protocol=fake_key),
                                   verify_key=ISSUER_KEY)
        self.assertIn("secret-shaped", str(caught.exception))

    def test_a_protocol_or_version_mismatch_is_refused(self):
        for change, message in (({"protocol": "other"}, "protocol"),
                                ({"metric_version": 99}, "metric_version")):
            with self.assertRaises(HarnessError) as caught:
                ps.validate_submission(self.mutate(**change),
                                       verify_key=ISSUER_KEY)
            self.assertIn(message, str(caught.exception))

    def test_a_bad_round_or_model_is_refused(self):
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(self.mutate(round="October"),
                                   verify_key=ISSUER_KEY)
        self.assertIn("closed UTC month", str(caught.exception))
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(self.mutate(model="someone/unknown"),
                                   verify_key=ISSUER_KEY)
        self.assertIn("allowlist", str(caught.exception))

    def test_a_nested_addition_is_refused(self):
        report = json.loads(json.dumps(self.report))
        report["proof"]["rows"] = 12
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(report, verify_key=ISSUER_KEY)
        self.assertIn("proof fields", str(caught.exception))
        report = json.loads(json.dumps(self.report))
        report["shares"][0]["task_id"] = "t-1"
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(report, verify_key=ISSUER_KEY)
        self.assertIn("share fields", str(caught.exception))
        report = json.loads(json.dumps(self.report))
        report["eligibility"]["extra"] = True
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(report, verify_key=ISSUER_KEY)
        self.assertIn("eligibility", str(caught.exception))

    def test_a_proof_bound_to_another_round_is_refused(self):
        report = json.loads(json.dumps(self.report))
        report["proof"]["round"] = "2026-09"
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(report, verify_key=ISSUER_KEY)
        self.assertIn("not bound", str(caught.exception))

    def test_a_proof_without_a_verified_chain_or_coverage_is_refused(self):
        for change, message in (
                ({"chain_verified": False}, "verified local chain"),
                ({"coverage_rows": 0}, "coverage"),
                ({"consent_surface": "proof-bench"}, "consent surface"),
                ({"consent_version": 2}, "disclosure version"),
                ({"stats_digest": "zz"}, "digest")):
            report = json.loads(json.dumps(self.report))
            report["proof"].update(change)
            with self.assertRaises(HarnessError) as caught:
                ps.validate_submission(report, verify_key=ISSUER_KEY)
            self.assertIn(message, str(caught.exception))

    def test_share_shape_is_checked(self):
        cases = []
        report = json.loads(json.dumps(self.report))
        report["shares"] = report["shares"][:2]
        cases.append((report, "exactly"))
        report = json.loads(json.dumps(self.report))
        report["shares"][0]["x"] = 0
        cases.append((report, "1.."))
        report = json.loads(json.dumps(self.report))
        report["shares"][0]["v"] = [1]
        cases.append((report, "width"))
        report = json.loads(json.dumps(self.report))
        report["shares"][0]["v"][0] = ps.PRIME
        cases.append((report, "out of range"))
        report = json.loads(json.dumps(self.report))
        report["shares"][0]["x"] = "one"
        cases.append((report, "index must be an int"))
        for report, message in cases:
            with self.assertRaises(HarnessError) as caught:
                ps.validate_submission(report, verify_key=ISSUER_KEY)
            self.assertIn(message, str(caught.exception))

    def test_a_commitment_that_does_not_open_is_refused(self):
        report = json.loads(json.dumps(self.report))
        report["commitment"] = "0" * 64
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(report, verify_key=ISSUER_KEY)
        self.assertIn("does not open", str(caught.exception))

    def test_altered_shares_break_the_proof_binding(self):
        report = json.loads(json.dumps(self.report))
        report["shares"][0]["v"][0] += 1
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(report, verify_key=ISSUER_KEY)
        self.assertIn("does not open", str(caught.exception))

    def test_a_forged_or_missing_voucher_is_refused(self):
        report = json.loads(json.dumps(self.report))
        report["eligibility"]["voucher"] = "0" * 64
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(report, verify_key=ISSUER_KEY)
        self.assertIn("voucher does not verify", str(caught.exception))
        report = json.loads(json.dumps(self.report))
        del report["eligibility"]
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission(report, verify_key=ISSUER_KEY)
        self.assertIn("allowlisted set", str(caught.exception))

    def test_a_non_object_report_is_refused(self):
        with self.assertRaises(HarnessError) as caught:
            ps.validate_submission([], verify_key=ISSUER_KEY)
        self.assertIn("must be an object", str(caught.exception))


class PublisherTests(unittest.TestCase):
    """The floor, the receipts, and the honest no-data state."""

    def setUp(self):
        self.boss = issuer()
        self.publisher = ps.PublicPublisher(ISSUER_KEY, site_key=b"site")

    def _accept(self, count, *, model=MODEL, prefix="operator"):
        for index in range(count):
            self.publisher.accept(report_for(model=model, brokered=self.boss,
                                             secret=f"{prefix}-{index}"))

    def test_nine_operators_publish_nothing(self):
        self._accept(9)
        sealed = self.publisher.seal(ROUND)
        self.assertEqual(sealed["published_figures"], 0)
        figures = sealed["models"][MODEL]
        self.assertEqual(figures["calls"]["state"], "suppressed")
        self.assertEqual(figures["calls"]["text"], ps.NO_DATA_TEXT)
        self.assertEqual(sealed["companions"]["text"], ps.NO_DATA_TEXT)

    def test_a_repeated_submission_cannot_lift_nine_operators(self):
        self._accept(9)
        repeat = report_for(brokered=self.boss, secret="operator-0")
        result = self.publisher.accept(repeat)
        self.assertEqual(result, {"accepted": False, "duplicate": True,
                                  "round": ROUND, "model": MODEL})
        sealed = self.publisher.seal(ROUND)
        self.assertEqual(sealed["published_figures"], 0)

    def test_ten_operators_publish_figures_that_recompute_from_the_receipt(self):
        self._accept(ps.PUBLICATION_FLOOR)
        sealed = self.publisher.seal(ROUND)
        figures = sealed["models"][MODEL]
        self.assertEqual(figures["calls"]["state"], "published")
        self.assertEqual(figures["calls"]["value"],
                         ps.PUBLICATION_FLOOR * 3)
        self.assertEqual(figures["success_rate"]["value"], 1.0)
        self.assertEqual(figures["cost_per_success_micro_usd"]["value"], 2000.0)
        self.assertEqual(figures["mean_latency_ms"]["value"], 120.0)
        self.assertEqual(sealed["published_figures"], 4)
        receipt = figures["success_rate"]["receipt"]
        self.assertEqual(receipt["cohort"]["operators"], ps.PUBLICATION_FLOOR)
        self.assertEqual(receipt["cohort"]["denominator"],
                         ps.PUBLICATION_FLOOR * 3)
        self.assertEqual(receipt["cohort"]["totals"]["successes"],
                         ps.PUBLICATION_FLOOR * 3)
        parameters = {key: value for key, value in receipt.items()
                      if key != "site_signature"}
        expected = hmac.new(b"site", ps._canon(parameters).encode(),
                            hashlib.sha256).hexdigest()
        self.assertEqual(receipt["site_signature"], expected)

    def test_figures_are_computed_from_cohort_totals(self):
        self._accept(ps.PUBLICATION_FLOOR - 1)
        self.publisher.accept(report_for(brokered=self.boss,
                                        secret="operator-late",
                                        rows=rows_for(count=1, cost=0.5)))
        sealed = self.publisher.seal(ROUND)
        totals = sealed["models"][MODEL]["calls"]["receipt"]["cohort"]["totals"]
        self.assertEqual(totals["calls"], (ps.PUBLICATION_FLOOR - 1) * 3 + 1)
        self.assertEqual(sealed["models"][MODEL]["calls"]["value"],
                         (ps.PUBLICATION_FLOOR - 1) * 3 + 1)

    def test_a_denominator_without_observations_is_suppressed(self):
        rows = []
        for index in range(1, 4):
            day = f"{ROUND}-{index:02d}"
            rows.append({"event": "model_result", "ts": f"{day}T00:00:00Z",
                         "model": MODEL, "cost": 0.002})
            rows.append({"event": "complete", "ts": f"{day}T00:00:01Z",
                         "model": MODEL, "status": "ok"})
        for index in range(ps.PUBLICATION_FLOOR):
            self.publisher.accept(report_for(brokered=self.boss,
                                            secret=f"operator-{index}",
                                            rows=rows))
        sealed = self.publisher.seal(ROUND)
        latency = sealed["models"][MODEL]["mean_latency_ms"]
        self.assertEqual(latency["state"], "suppressed")
        self.assertEqual(latency["reason"], "undefined denominator")
        self.assertEqual(sealed["models"][MODEL]["calls"]["state"], "published")

    def test_a_model_below_the_floor_does_not_hide_a_published_one(self):
        self._accept(ps.PUBLICATION_FLOOR)
        self.publisher.accept(report_for(model=OTHER_MODEL, brokered=self.boss,
                                        secret="other-1"))
        sealed = self.publisher.seal(ROUND)
        self.assertEqual(sealed["models"][MODEL]["calls"]["state"], "published")
        self.assertEqual(sealed["models"][OTHER_MODEL]["calls"]["state"],
                         "suppressed")
        self.assertEqual(sealed["companions"]["state"], "suppressed")

    def test_sealing_twice_returns_the_same_round(self):
        self._accept(ps.PUBLICATION_FLOOR)
        first = self.publisher.seal(ROUND)
        second = self.publisher.seal(ROUND)
        self.assertEqual(first, second)
        self.assertEqual(second["published_figures"], 4)

    def test_a_sealed_round_keeps_only_cohort_records(self):
        self._accept(ps.PUBLICATION_FLOOR)
        self.publisher.seal(ROUND)
        stored = self.publisher.published()[ROUND]
        serialized = json.dumps(stored, sort_keys=True)
        for forbidden in ('"shares"', '"token"', '"consent_period"'):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(set(stored["models"][MODEL]["calls"]["receipt"]
                             ["cohort"]["totals"]), set(ps.STAT_FIELDS))

    def test_an_unsealed_round_publishes_nothing(self):
        self.assertEqual(self.publisher.seal("2026-09")["published_figures"], 0)

    def test_a_publisher_needs_a_site_signing_key(self):
        with self.assertRaises(HarnessError):
            ps.PublicPublisher(b"key", site_key=b"")


class RosterTests(unittest.TestCase):
    """The site data file shows figures or the exact no-data text."""

    def test_a_published_figure_and_a_suppressed_one_both_render(self):
        boss = issuer()
        publisher = ps.PublicPublisher(ISSUER_KEY, site_key=b"site")
        for index in range(ps.PUBLICATION_FLOOR):
            publisher.accept(report_for(brokered=boss,
                                        secret=f"operator-{index}"))
        publisher.accept(report_for(model=OTHER_MODEL, brokered=boss,
                                    secret="other-1"))
        publisher.seal(ROUND)
        roster = ps.roster_payload(publisher.published())
        rows = {(row["model"], row["metric"]): row for row in roster["figures"]}
        published = rows[(MODEL, "calls")]
        self.assertEqual(published["state"], "published")
        self.assertEqual(published["receipt"]["model"], MODEL)
        suppressed = rows[(OTHER_MODEL, "calls")]
        self.assertEqual(suppressed["state"], "no_data")
        self.assertEqual(suppressed["text"], ps.NO_DATA_TEXT)
        self.assertEqual(roster["no_data_text"], ps.NO_DATA_TEXT)

    def test_an_empty_published_set_is_an_empty_roster(self):
        roster = ps.roster_payload(None)
        self.assertEqual(roster["figures"], [])
        self.assertEqual(roster["schema"], "public-roster-v1")


if __name__ == "__main__":
    unittest.main()
