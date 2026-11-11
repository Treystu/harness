"""Hermetic tests for POST /api/driver/nl (#273 acceptance).

The plan/execute logic is tested through ``harness.driver_nl.handle`` with
injected fakes (no LLM, no driver, no network); the HTTP gate (auth, flag,
routing) is tested against a live ephemeral server with a patched planner.
"""
import http.client
import json
import os
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from harness import driver_nl
from harness.driver_nl import PlanStore, flag_on, handle, request_authorized
from harness.errors import HarnessError


def _planner_for(plan):
    def fake_planner(user_input):
        return [dict(s) for s in plan]
    return fake_planner


_LAUNCH = [{"action": "launch_app", "params": {"app_name": "notepad"}}]


class FakeDriver:
    """An executor double: scripted per-action outcomes."""

    def __init__(self, outcomes=None):
        self.outcomes = dict(outcomes or {})
        self.calls = []
        self.executor = self

    def resolve(self, name, params):
        return object(), dict(params)

    def execute(self, name, params, consent=None):
        self.calls.append((name, dict(params), consent))
        ok, detail = self.outcomes.get(name, (True, "done"))
        return SimpleNamespace(ok=ok, detail=detail)


class FlagTests(unittest.TestCase):

    def test_flag_defaults_off(self):
        env = {k: v for k, v in os.environ.items()
               if k != "HARNESS_NL_CONTROL"}
        self.assertFalse(flag_on(env))

    def test_flag_on_values(self):
        for value in ("1", "true", "YES", " on "):
            self.assertTrue(flag_on({"HARNESS_NL_CONTROL": value}))

    def test_flag_off_values(self):
        for value in ("0", "false", "no", "off", ""):
            self.assertFalse(flag_on({"HARNESS_NL_CONTROL": value}))


class AuthTests(unittest.TestCase):

    def test_host_authorized_passes_without_driver_token(self):
        self.assertTrue(request_authorized(
            None, host_authorized=True, driver_token=None))

    def test_driver_bearer_passes(self):
        self.assertTrue(request_authorized(
            "Bearer secret-token", host_authorized=False,
            driver_token="secret-token"))

    def test_driver_bearer_without_prefix_passes(self):
        self.assertTrue(request_authorized(
            "secret-token", host_authorized=False,
            driver_token="secret-token"))

    def test_wrong_driver_token_fails(self):
        self.assertFalse(request_authorized(
            "Bearer wrong", host_authorized=False,
            driver_token="secret-token"))

    def test_missing_header_and_token_fails(self):
        self.assertFalse(request_authorized(
            None, host_authorized=False, driver_token="secret-token"))
        self.assertFalse(request_authorized(
            "Bearer secret-token", host_authorized=False, driver_token=None))
        self.assertFalse(request_authorized(
            None, host_authorized=False, driver_token=None))


class PlanStoreTests(unittest.TestCase):

    def test_save_get_roundtrip(self):
        store = PlanStore()
        pid = store.save("open notepad", _LAUNCH)
        self.assertEqual(store.get(pid), ("open notepad", _LAUNCH))

    def test_unknown_id_is_none(self):
        self.assertIsNone(PlanStore().get("nlp_nope"))

    def test_expired_id_is_none(self):
        now = [1000.0]
        store = PlanStore(ttl=10.0, clock=lambda: now[0])
        pid = store.save("x", _LAUNCH)
        now[0] += 11.0
        self.assertIsNone(store.get(pid))

    def test_capacity_evicts_oldest(self):
        store = PlanStore(max_plans=2)
        first = store.save("a", _LAUNCH)
        store.save("b", _LAUNCH)
        store.save("c", _LAUNCH)
        self.assertIsNone(store.get(first))

    def test_cancel_unknown_is_false(self):
        self.assertFalse(PlanStore().cancel("nlp_nope"))

    def test_cancel_and_is_cancelled(self):
        store = PlanStore()
        pid = store.save("x", _LAUNCH)
        self.assertFalse(store.is_cancelled(pid))
        self.assertTrue(store.cancel(pid))
        self.assertTrue(store.is_cancelled(pid))

    def test_is_cancelled_unknown_is_false(self):
        self.assertFalse(PlanStore().is_cancelled("nlp_nope"))


class HandleGateTests(unittest.TestCase):

    def test_flag_off_is_404_even_authorized(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": ""},
                             clear=False):
            if "HARNESS_NL_CONTROL" in os.environ:
                del os.environ["HARNESS_NL_CONTROL"]
            status, payload = handle({}, authorized=True)
        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])

    def test_unauthorized_is_401(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, _payload = handle({}, authorized=False)
        self.assertEqual(status, 401)

    def test_non_object_body_is_400(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, _payload = handle([], authorized=True)
        self.assertEqual(status, 400)

    def test_cancel_unknown_plan_is_404(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, _payload = handle(
                {"cancel_plan": "nlp_nope"}, authorized=True,
                store=PlanStore())
        self.assertEqual(status, 404)

    def test_cancel_malformed_id_is_400(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, _payload = handle(
                {"cancel_plan": 42}, authorized=True, store=PlanStore())
        self.assertEqual(status, 400)

    def test_confirm_without_plan_id_is_400(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, _payload = handle(
                {"confirm": True}, authorized=True, store=PlanStore())
        self.assertEqual(status, 400)

    def test_confirm_unknown_plan_is_404(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, _payload = handle(
                {"confirm": True, "plan_id": "nlp_nope"}, authorized=True,
                store=PlanStore())
        self.assertEqual(status, 404)

    def test_plan_id_without_confirm_is_400(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, payload = handle(
                {"plan_id": "nlp_x"}, authorized=True, store=PlanStore())
        self.assertEqual(status, 400)
        self.assertIn("confirm:true", payload["error"])

    def test_empty_input_is_400(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, _payload = handle(
                {"input": "  "}, authorized=True, store=PlanStore(),
                planner=_planner_for(_LAUNCH))
        self.assertEqual(status, 400)

    def test_planner_failure_is_502(self):
        def boom(user_input):
            raise HarnessError("no key")
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, payload = handle(
                {"input": "open notepad"}, authorized=True,
                store=PlanStore(), planner=boom)
        self.assertEqual(status, 502)
        self.assertIn("no key", payload["error"])


class BuildDriverTests(unittest.TestCase):

    def test_build_driver_maps_launch_switch(self):
        seen = {}

        class FakeSettings:
            launch_app_enabled = False

            def with_overrides(self, **kw):
                seen.update(kw)
                return self

        fake_driver = object()
        with mock.patch("driver_core.config.load_settings",
                         return_value=FakeSettings()) as loader, \
                mock.patch("driver_core.driver.driver_from_settings",
                           return_value=fake_driver) as factory:
            with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
                self.assertIs(driver_nl.build_driver(), fake_driver)
        loader.assert_called_once_with()
        self.assertTrue(seen["launch_app_enabled"])
        factory.assert_called_once_with(unittest.mock.ANY)

    def test_build_driver_accepts_settings(self):
        class FakeSettings:
            launch_app_enabled = True

            def with_overrides(self, **kw):
                return self

        fake_driver = object()
        with mock.patch("driver_core.driver.driver_from_settings",
                         return_value=fake_driver):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertIs(driver_nl.build_driver(settings=FakeSettings()),
                              fake_driver)

    def test_emit_forwards_to_event_bus(self):
        with mock.patch("harness.events.emit") as bus:
            driver_nl.emit("driver_step_start", task_id="t", step=1)
        bus.assert_called_once_with("driver_step_start", task_id="t",
                                    step=1)


class PreviewTests(unittest.TestCase):

    def test_preview_returns_plan_with_class(self):
        store = PlanStore()
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, payload = handle(
                {"input": "open notepad"}, authorized=True, store=store,
                planner=_planner_for(_LAUNCH))
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "plan")
        self.assertTrue(payload["requires_confirm"])
        self.assertEqual(payload["plan"], [
            {"action": "launch_app", "params": {"app_name": "notepad"},
             "class": "mutating"}])
        self.assertEqual(store.get(payload["plan_id"])[1], _LAUNCH)


class ExecuteTests(unittest.TestCase):

    def _confirm(self, store, plan, driver, events):
        pid = store.save("open notepad", plan)
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            with mock.patch.object(driver_nl, "emit",
                                   side_effect=lambda t, **f: events.append(
                                       (t, f))):
                return handle({"confirm": True, "plan_id": pid},
                              authorized=True, store=store, driver=driver)

    def test_execute_runs_steps_with_events(self):
        store, driver, events = PlanStore(), FakeDriver(), []
        status, payload = self._confirm(store, _LAUNCH, driver, events)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["steps"][0]["ok"], True)
        kinds = [t for t, _f in events]
        self.assertEqual(
            kinds,
            ["driver_task_start", "driver_step_start",
             "driver_step_complete"])
        self.assertEqual(driver.calls[0][0], "launch_app")
        self.assertEqual(driver.calls[0][1], {"app_name": "notepad"})
        self.assertTrue(driver.calls[0][2].granted)

    def test_cancel_ok_returns_cancelled(self):
        store = PlanStore()
        pid = store.save("open notepad", _LAUNCH)
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, payload = handle({"cancel_plan": pid}, authorized=True,
                                      store=store)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True, "status": "cancelled",
                                   "plan_id": pid})

    def test_execute_stops_at_first_failure(self):
        plan = _LAUNCH + [{"action": "type_text",
                           "params": {"text": "hi"}}]
        driver = FakeDriver({"type_text": (False, "no backend")})
        store, events = PlanStore(), []
        status, payload = self._confirm(store, plan, driver, events)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "stopped")
        self.assertEqual(len(payload["steps"]), 2)
        self.assertFalse(payload["steps"][1]["ok"])

    def test_driver_error_becomes_step_failure(self):
        from driver_core.errors import ExecutorError

        class AngryDriver(FakeDriver):
            def execute(self, name, params, consent=None):
                raise ExecutorError("backend exploded")

        store, events = PlanStore(), []
        status, payload = self._confirm(store, _LAUNCH, AngryDriver(),
                                        events)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "stopped")
        self.assertFalse(payload["steps"][0]["ok"])
        self.assertIn("backend exploded", payload["steps"][0]["detail"])

    def test_cancelled_plan_runs_no_steps(self):
        store = PlanStore()
        pid = store.save("open notepad", _LAUNCH)
        store.cancel(pid)
        driver, events = FakeDriver(), []
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            with mock.patch.object(driver_nl, "emit",
                                   side_effect=lambda t, **f: events.append(
                                       (t, f))):
                status, payload = handle(
                    {"confirm": True, "plan_id": pid}, authorized=True,
                    store=store, driver=driver)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "cancelled")
        self.assertEqual(payload["steps"], [])
        self.assertEqual(driver.calls, [])


class BuildPlannerTests(unittest.TestCase):
    """The default planner wires the governed scout head to the plan seam.

    ``harness.nl_planner`` may be absent on this branch (it lands with
    #271), so the seam is injected through ``sys.modules`` either way."""

    def _planner(self, governed=None, ladder=("m1", "m2")):
        import sys
        import types
        nl = types.ModuleType("harness.nl_planner")
        nl.plan = lambda user_input, chat_fn: ("planned:", chat_fn("p"))
        fake_governed = governed or (lambda *a, **k: ("hi", 0.0))
        with mock.patch.dict(sys.modules, {"harness.nl_planner": nl}):
            with mock.patch("harness.session.governor_for",
                            return_value=("key", object())), \
                    mock.patch("harness.waist.resolve_scout_ladder",
                               return_value=list(ladder)), \
                    mock.patch("harness._http.HttpTransport"), \
                    mock.patch("harness.chat.governed_text",
                               side_effect=fake_governed):
                return driver_nl.build_planner()("open notepad")

    def test_first_ladder_model_wins(self):
        calls = []

        def governed(transport, api_key, gov, model, prompt, *a, **k):
            calls.append(model)
            return ("text-" + model, 0.0)

        self.assertEqual(self._planner(governed=governed)[1], "text-m1")
        self.assertEqual(calls, ["m1"])

    def test_ladder_falls_through_to_second_model(self):
        def governed(transport, api_key, gov, model, prompt, *a, **k):
            if model == "m1":
                raise HarnessError("429 limited")
            return ("text-m2", 0.0)

        self.assertEqual(self._planner(governed=governed)[1], "text-m2")

    def test_exhausted_ladder_raises_last_error(self):
        def governed(*a, **k):
            raise HarnessError("down")

        with self.assertRaisesRegex(HarnessError, "down"):
            self._planner(governed=governed)

    def test_empty_ladder_raises(self):
        with self.assertRaisesRegex(HarnessError, "ladder empty"):
            self._planner(ladder=())


class HttpGateTests(unittest.TestCase):
    """The route, auth, and flag through a live ephemeral server."""

    token = "nl-test-host-token"

    def setUp(self):
        from harness.server import make_server
        env = {k: v for k, v in os.environ.items()
               if k not in ("DRIVER_TOKEN", "HARNESS_NL_CONTROL")}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.httpd = make_server("127.0.0.1", 0, auth_token=self.token)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.addCleanup(self.httpd.shutdown)
        planner = mock.patch.object(
            driver_nl, "build_planner",
            return_value=_planner_for(_LAUNCH))
        planner.start()
        self.addCleanup(planner.stop)
        self.addCleanup(self._teardown)

    def _teardown(self):
        # Mirror ServerHarness: the event sink is module-global and capped;
        # a leaked sink per test starves later servers, and a live server
        # thread surfaces as an unclosed-socket ResourceWarning at GC.
        from harness import events as _events
        _events.remove_sink(self.httpd.ui._on_event)
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=60)

    def _post(self, body, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=120)
        try:
            hdrs = dict(headers or {})
            hdrs.setdefault("Host", "127.0.0.1")
            payload = json.dumps(body).encode() if body is not None else None
            if payload is not None:
                hdrs["Content-Type"] = "application/json"
            conn.request("POST", "/api/driver/nl", body=payload,
                         headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read()
            try:
                return resp.status, json.loads(raw or b"{}")
            except ValueError:
                return resp.status, {"raw": raw.decode("utf-8", "replace")}
        finally:
            conn.close()

    def test_unauthorized_is_401(self):
        status, _data = self._post({"input": "open notepad"})
        self.assertEqual(status, 401)

    def test_flag_off_is_404_with_host_token(self):
        status, _data = self._post(
            {"input": "open notepad"},
            {"X-Harness-Auth": self.token})
        self.assertEqual(status, 404)

    def test_preview_with_host_token(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            status, data = self._post(
                {"input": "open notepad"},
                {"X-Harness-Auth": self.token})
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "plan")
        self.assertTrue(data["requires_confirm"])

    def test_preview_with_driver_token(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1",
                                           "DRIVER_TOKEN": "driver-secret"}):
            status, data = self._post(
                {"input": "open notepad"},
                {"Authorization": "Bearer driver-secret"})
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "plan")

    def test_wrong_driver_token_is_401(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1",
                                           "DRIVER_TOKEN": "driver-secret"}):
            status, _data = self._post(
                {"input": "open notepad"},
                {"Authorization": "Bearer wrong"})
        self.assertEqual(status, 401)

    def test_malformed_json_is_400(self):
        with mock.patch.dict(os.environ, {"HARNESS_NL_CONTROL": "1"}):
            conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                              timeout=120)
            try:
                conn.request("POST", "/api/driver/nl", body=b"{oops",
                             headers={"Host": "127.0.0.1",
                                      "Content-Type": "application/json",
                                      "X-Harness-Auth": self.token})
                resp = conn.getresponse()
                self.assertEqual(resp.status, 400)
                resp.read()
            finally:
                conn.close()

    def test_foreign_host_is_403(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        try:
            conn.request("POST", "/api/driver/nl", body=b"{}",
                         headers={"Host": "example.com",
                                  "Content-Type": "application/json"})
            self.assertEqual(conn.getresponse().status, 403)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
