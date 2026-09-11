import sys
import tempfile
import types
import unittest

import uptime_checker
from uptime_checker import (
    check_url,
    load_state,
    load_watchlist,
    log_transitions,
    notify,
    run_check_cycle,
    save_state,
)


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeRequestException(Exception):
    pass


def install_fake_requests(get_fn):
    """Dual-patches sys.modules and the module's own bound `requests`
    name (same technique used across this portfolio's other
    API-integration projects, needed because uptime_checker.py does
    `import requests` at load time)."""
    fake_requests = types.ModuleType("requests")
    fake_requests.get = get_fn
    fake_requests.RequestException = FakeRequestException
    sys.modules["requests"] = fake_requests
    uptime_checker.requests = fake_requests
    return fake_requests


class TestCheckUrl(unittest.TestCase):
    def setUp(self):
        self.original_requests = uptime_checker.requests

    def tearDown(self):
        sys.modules["requests"] = self.original_requests
        uptime_checker.requests = self.original_requests

    def test_2xx_response_is_reported_up(self):
        install_fake_requests(lambda url, timeout=5: FakeResponse(200))
        result = check_url("https://example.com")
        self.assertEqual(result["status"], "up")
        self.assertEqual(result["status_code"], 200)

    def test_5xx_response_is_reported_down(self):
        install_fake_requests(lambda url, timeout=5: FakeResponse(503))
        result = check_url("https://example.com")
        self.assertEqual(result["status"], "down")
        self.assertEqual(result["status_code"], 503)

    def test_connection_failure_is_reported_down_not_raised(self):
        def raise_connection_error(url, timeout=5):
            raise FakeRequestException("simulated connection failure")

        install_fake_requests(raise_connection_error)
        result = check_url("https://down-example.com")
        self.assertEqual(result["status"], "down")
        self.assertIsNone(result["status_code"])
        self.assertIn("simulated connection failure", result["error"])


class TestRunCheckCycle(unittest.TestCase):
    def setUp(self):
        self.original_requests = uptime_checker.requests

    def tearDown(self):
        sys.modules["requests"] = self.original_requests
        uptime_checker.requests = self.original_requests

    def test_detects_a_simulated_downed_url(self):
        """The project's Definition of Done: correctly detect and log a
        deliberately downed URL."""

        def get(url, timeout=5):
            if url == "https://down.example.com":
                raise FakeRequestException("connection refused")
            return FakeResponse(200)

        install_fake_requests(get)
        state = {"https://up.example.com": "up", "https://down.example.com": "up"}
        results, transitions, new_state = run_check_cycle(
            ["https://up.example.com", "https://down.example.com"], state
        )

        self.assertEqual(new_state["https://down.example.com"], "down")
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["url"], "https://down.example.com")
        self.assertEqual(transitions[0]["from_status"], "up")
        self.assertEqual(transitions[0]["to_status"], "down")

    def test_no_transition_recorded_when_status_is_unchanged(self):
        install_fake_requests(lambda url, timeout=5: FakeResponse(200))
        state = {"https://up.example.com": "up"}
        _results, transitions, new_state = run_check_cycle(["https://up.example.com"], state)
        self.assertEqual(transitions, [])
        self.assertEqual(new_state["https://up.example.com"], "up")

    def test_recovery_is_recorded_as_a_transition(self):
        install_fake_requests(lambda url, timeout=5: FakeResponse(200))
        state = {"https://up.example.com": "down"}
        _results, transitions, new_state = run_check_cycle(["https://up.example.com"], state)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["from_status"], "down")
        self.assertEqual(transitions[0]["to_status"], "up")

    def test_first_time_seeing_a_url_that_is_down_still_produces_a_transition(self):
        def raise_it(url, timeout=5):
            raise FakeRequestException("never seen before, already down")

        install_fake_requests(raise_it)
        _results, transitions, new_state = run_check_cycle(["https://new.example.com"], {})
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["from_status"], "unknown")
        self.assertEqual(transitions[0]["to_status"], "down")

    def test_a_url_down_across_multiple_cycles_logs_only_once(self):
        def raise_it(url, timeout=5):
            raise FakeRequestException("still down")

        install_fake_requests(raise_it)
        state = {}
        all_transitions = []
        for _ in range(3):
            _results, transitions, state = run_check_cycle(["https://flaky.example.com"], state)
            all_transitions.extend(transitions)
        self.assertEqual(len(all_transitions), 1)


class TestLoggingAndState(unittest.TestCase):
    def test_log_transitions_appends_readable_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = f"{tmp}/log.txt"
            transitions = [{
                "url": "https://down.example.com", "from_status": "up",
                "to_status": "down", "checked_at": "2026-01-01T00:00:00+00:00",
                "error": "timeout",
            }]
            log_transitions(log_path, transitions)
            with open(log_path) as f:
                content = f.read()
            self.assertIn("https://down.example.com", content)
            self.assertIn("up -> down", content)
            self.assertIn("timeout", content)

    def test_log_transitions_is_a_noop_for_an_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = f"{tmp}/log.txt"
            log_transitions(log_path, [])
            self.assertFalse(__import__("os").path.exists(log_path))

    def test_state_round_trips_through_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = f"{tmp}/state.json"
            save_state(state_path, {"https://a.com": "up", "https://b.com": "down"})
            loaded = load_state(state_path)
            self.assertEqual(loaded, {"https://a.com": "up", "https://b.com": "down"})

    def test_load_state_returns_empty_dict_when_file_does_not_exist(self):
        self.assertEqual(load_state("/nonexistent/path/state.json"), {})

    def test_load_watchlist_reads_url_list_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/watchlist.json"
            with open(path, "w") as f:
                f.write('{"urls": ["https://a.com", "https://b.com"]}')
            self.assertEqual(load_watchlist(path), ["https://a.com", "https://b.com"])


class TestNotify(unittest.TestCase):
    def test_down_transition_produces_an_alert_message(self):
        messages = []
        notify(
            {"url": "https://x.com", "to_status": "down", "error": "timeout"},
            sink=messages.append,
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("ALERT", messages[0])
        self.assertIn("https://x.com", messages[0])

    def test_up_transition_produces_a_recovery_message(self):
        messages = []
        notify({"url": "https://x.com", "to_status": "up", "error": None}, sink=messages.append)
        self.assertIn("RECOVERED", messages[0])


if __name__ == "__main__":
    unittest.main()
