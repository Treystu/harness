"""#418: a request that was running when the process died is recoverable.

The defect: after a restart the desktop API reported healthy with
`run_count=0` while the durable checkpoint still said `running`, so a
long-running request had no visible handle, state, or result to reconnect to.
The seam is the durable state itself -- the per-session lifecycle checkpoint
written by `LifecycleCoordinator` under `<history>/chat_checkpoints/` -- so the
tests below write that state through the real coordinator (or, for the kill
test, let a real child process die mid-request) and then start a **fresh
server** over it. Nothing here mocks the recovery decision.
"""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from harness.lifecycle import LifecycleCoordinator
from harness.run_recovery import (
    RECOVERY_RETENTION_SECONDS,
    classify,
    redact,
    recovery_summary,
)
from harness.server import make_server

PROMPT = "Summarise the last three releases of the sibling project."


def _request(port, path, token=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {"Host": "127.0.0.1"}
        if token:
            headers["X-Harness-Auth"] = token
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            payload = {"raw": body.decode("utf-8", "replace")}
        return resp.status, payload
    finally:
        conn.close()


class _ServerOverDurableState(unittest.TestCase):
    """A fresh server (new process state) over an existing history directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.history = self.root / "chat_history"
        self.history.mkdir(parents=True)
        self.token = "recovery-token"

    def _begin(self, session_id="sess-418", prompt=PROMPT, *, lane="chat",
               stage="answer_generation", status=None):
        coordinator = LifecycleCoordinator(history_dir=self.history)
        state = coordinator.begin(lane, session_id, prompt, stage=stage)
        if status is not None:
            state["status"] = status
            if status in ("complete", "failed", "deferred"):
                state["stage"] = "terminal"
            coordinator.save(state)
        return state

    def _server(self):
        httpd = make_server("127.0.0.1", 0, auth_token=self.token,
                            history_dir=self.history)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def stop():
            httpd.shutdown()
            httpd.server_close()
            thread.join(2)
            httpd.ui.uninstall_event_sink()

        self.addCleanup(stop)
        return httpd, httpd.server_address[1]


class RestartVisibilityTests(_ServerOverDurableState):
    def test_a_request_that_was_running_is_listed_after_the_restart(self):
        self._begin()
        httpd, port = self._server()
        status, payload = _request(port, "/api/runs", self.token)
        self.assertEqual(status, 200)
        recovered = [run for run in payload.get("runs", [])
                     if run.get("recovered")]
        self.assertEqual(len(recovered), 1, payload)
        run = recovered[0]
        self.assertEqual(run["state"], "interrupted")
        self.assertEqual(run["checkpoint_status"], "running")
        self.assertEqual(run["prompt"], PROMPT)
        self.assertTrue(run["resumable"])
        self.assertEqual(run["session_id"], "sess-418")
        # Nothing was replayed: a restart must never duplicate provider calls
        # or spend, so no live run exists after discovery.
        self.assertEqual(httpd.ui.runs, {})

    def test_status_separates_live_runs_from_recovered_requests(self):
        self._begin()
        _httpd, port = self._server()
        status, payload = _request(port, "/api/status", self.token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["run_count"], 0)
        self.assertEqual(payload["recovered_count"], 1)
        self.assertEqual(payload["recovered"][0]["state"], "interrupted")

    def test_completed_failed_and_unreadable_checkpoints_are_classified(self):
        self._begin("done", "A finished request.", status="complete")
        self._begin("failed", "A request that failed.", status="failed")
        broken = self.history / "chat_checkpoints" / ("a" * 64 + ".json")
        broken.write_text("{not json", encoding="utf-8")
        _httpd, port = self._server()
        _status, payload = _request(port, "/api/runs", self.token)
        by_session = {run["session_id"]: run
                      for run in payload.get("recovered", [])}
        self.assertEqual(by_session["done"]["state"], "completed")
        self.assertFalse(by_session["done"]["resumable"])
        self.assertEqual(by_session["failed"]["state"], "failed")
        self.assertIn("unknown", [run["state"]
                                  for run in payload.get("recovered", [])])

    def test_a_checkpoint_past_retention_is_stale_not_running(self):
        state = self._begin()
        coordinator = LifecycleCoordinator(history_dir=self.history)
        path = coordinator._path(state["session_id"])
        old = time.time() - 30 * 86400
        os.utime(path, (old, old))
        _httpd, port = self._server()
        _status, payload = _request(port, "/api/runs", self.token)
        run = payload["recovered"][0]
        self.assertEqual(run["state"], "stale")
        self.assertFalse(run["resumable"])
        self.assertGreater(run["age_seconds"], 20 * 86400)

    def test_the_preserved_prompt_is_redacted(self):
        self._begin("secret", "Use sk-abcdef0123456789abcdef to call the API.")
        _httpd, port = self._server()
        _status, payload = _request(port, "/api/runs", self.token)
        prompt = payload["recovered"][0]["prompt"]
        self.assertNotIn("sk-abcdef0123456789abcdef", prompt)
        self.assertIn("[redacted]", prompt)

    def test_a_recovered_result_is_readable_and_events_do_not_invent_history(self):
        self._begin()
        _httpd, port = self._server()
        _status, listing = _request(port, "/api/runs", self.token)
        run_id = listing["recovered"][0]["id"]
        status, result = _request(port, f"/api/runs/{run_id}/result", self.token)
        self.assertEqual(status, 200)
        self.assertEqual(result["prompt"], PROMPT)
        self.assertEqual(result["stage"], "answer_generation")
        status, events = _request(port, f"/api/runs/{run_id}/events", self.token)
        self.assertEqual(status, 200)
        self.assertEqual(events["events"], [])

    def test_a_real_process_dying_mid_request_leaves_a_recoverable_record(self):
        script = (
            "import sys\n"
            "from harness.lifecycle import LifecycleCoordinator\n"
            "c = LifecycleCoordinator(history_dir=sys.argv[1])\n"
            "c.begin('chat', 'killed-418', 'A request the process dies under.',"
            " stage='answer_generation')\n"
            "sys.stdout.write('running\\n'); sys.stdout.flush()\n"
            "import os; os._exit(9)\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", script, str(self.history)],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 9)
        _httpd, port = self._server()
        _status, payload = _request(port, "/api/runs", self.token)
        run = payload["recovered"][0]
        self.assertEqual(run["session_id"], "killed-418")
        self.assertEqual(run["state"], "interrupted")
        self.assertIn("no live owner", run["reason"])


class ClassificationUnitTests(unittest.TestCase):
    """The classifier's own contract: honest states, no guessing."""

    def test_a_running_checkpoint_without_an_owner_is_interrupted(self):
        verdict = classify({"status": "running", "stage": "answer_review"},
                           age_seconds=10)
        self.assertEqual(verdict["state"], "interrupted")
        self.assertTrue(verdict["resumable"])
        self.assertIn("no live owner", verdict["reason"])

    def test_a_refused_candidate_is_preserved_but_not_resumable(self):
        verdict = classify({
            "status": "running", "stage": "route",
            "data": {"refused": True},
        }, age_seconds=10)
        self.assertEqual(verdict["state"], "interrupted")
        self.assertFalse(verdict["resumable"])
        self.assertIn("consent", verdict["reason"])

    def test_terminal_statuses_are_not_resumable(self):
        for status, expected in (("complete", "completed"),
                                 ("failed", "failed"),
                                 ("error", "failed")):
            with self.subTest(status=status):
                verdict = classify({"status": status}, age_seconds=1)
                self.assertEqual(verdict["state"], expected)
                self.assertFalse(verdict["resumable"])

    def test_an_unrecognised_status_is_unknown(self):
        self.assertEqual(classify({"status": "phaseshift"},
                                  age_seconds=1)["state"], "unknown")
        self.assertEqual(classify({"status": ""}, age_seconds=1)["state"],
                         "unknown")

    def test_an_unreadable_checkpoint_is_unknown_not_running(self):
        verdict = classify(None, age_seconds=1)
        self.assertEqual(verdict["state"], "unknown")
        self.assertIn("could not be read", verdict["reason"])

    def test_retention_turns_an_interrupted_record_stale(self):
        verdict = classify({"status": "running", "stage": "answer_review"},
                           age_seconds=RECOVERY_RETENTION_SECONDS + 1)
        self.assertEqual(verdict["state"], "stale")
        self.assertFalse(verdict["resumable"])

    def test_redaction_removes_every_credential_shape(self):
        text = ("key sk-abcdef1234567890 and Bearer abcdefghijklmnop and "
                "token=supersecret and " + "a" * 40)
        cleaned = redact(text)
        for secret in ("sk-abcdef1234567890", "abcdefghijklmnop",
                       "supersecret", "a" * 40):
            self.assertNotIn(secret, cleaned)
        self.assertIn("[redacted]", cleaned)
        self.assertEqual(redact(None), "")

    def test_the_summary_counts_states_rather_than_claiming_success(self):
        summary = recovery_summary([
            {"state": "interrupted"}, {"state": "interrupted"},
            {"state": "completed"},
        ])
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["by_state"]["interrupted"], 2)
        self.assertEqual(summary["retention_days"],
                         RECOVERY_RETENTION_SECONDS // 86400)

    def test_a_legacy_chat_checkpoint_prompt_is_read(self):
        from harness.run_recovery import _prompt_of
        self.assertEqual(_prompt_of({"prompt": "legacy prompt"}), "legacy prompt")
        self.assertEqual(_prompt_of({"data": {"question": "from data"}}),
                         "from data")
        self.assertEqual(_prompt_of({}), "")

    def test_a_refused_review_decision_is_not_resumable(self):
        verdict = classify({
            "status": "deferred", "stage": "review",
            "review": {"decision": "refused"},
        }, age_seconds=5)
        self.assertFalse(verdict["resumable"])


if __name__ == "__main__":
    unittest.main()
