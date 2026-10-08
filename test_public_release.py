import copy
import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import calendar_bridge as bridge
import google_auth
import settings


def source_event(identifier="demo-source", title="Design review"):
    return {"id": identifier, "subject": title,
            "start": {"dateTime": "2026-11-03T09:00:00Z", "timeZone": "UTC"},
            "end": {"dateTime": "2026-11-03T10:00:00Z", "timeZone": "UTC"},
            "isAllDay": False, "showAs": "busy", "sensitivity": "normal", "isReminderOn": False,
            "body": {"contentType": "text", "content": "Confidential fictional detail"},
            "location": {"displayName": "Fictional room"},
            "onlineMeeting": {"joinUrl": "https://meeting.example/private"}}


class PublicSyncTests(unittest.TestCase):
    def test_minimal_private_copies_are_default(self):
        payload = bridge.to_google_event(source_event())
        self.assertEqual(payload["description"], "")
        self.assertEqual(payload["location"], "")
        self.assertEqual(payload["visibility"], "private")
        self.assertNotIn("attendees", payload)

    def test_removed_location_is_explicitly_cleared(self):
        item = source_event(); item["location"] = {}
        with patch.object(bridge, "COPY_DETAILS", True):
            self.assertEqual(bridge.to_google_event(item)["location"], "")

    def test_complete_plan_is_idempotent(self):
        source = source_event()
        stored = {"id": "demo-google", **bridge.to_google_event(source)}
        self.assertEqual(bridge.plan_actions([source], [stored]), [])

    def test_unrelated_metadata_does_not_cause_perpetual_updates(self):
        source = source_event()
        stored = {"id": "demo-google", **bridge.to_google_event(source)}
        stored["extendedProperties"]["private"]["another-application"] = "keep"
        self.assertEqual(bridge.plan_actions([source], [stored]), [])

    def test_foreign_and_personal_events_are_not_pruned(self):
        foreign = {"id": "foreign", **bridge.to_google_event(source_event())}
        foreign["extendedProperties"]["private"]["bridgeName"] = "other-instance"
        personal = {"id": "personal", "summary": "Personal time", "start": {"date": "2026-11-03"}, "end": {"date": "2026-11-04"}}
        self.assertEqual(bridge.plan_actions([], [foreign, personal]), [])

    def test_unmanaged_matching_copy_is_skipped_not_adopted(self):
        source = source_event(); item = bridge.to_google_event(source)
        item.pop("extendedProperties")
        plan = bridge.plan_actions([source], [item])
        self.assertEqual([p["action"] for p in plan], ["skip-existing"])

    def test_deletes_need_explicit_opt_in(self):
        with patch.object(bridge, "google_request") as network:
            result = bridge.execute_actions("fake", [{"action": "delete", "googleId": "fictional", "summary": "Demo"}], False, 10)
        network.assert_not_called()
        self.assertEqual(result["counts"]["delete-skipped"], 1)

    def test_preview_does_not_write_even_with_pruning_enabled(self):
        with patch.object(bridge, "google_request") as network:
            result = bridge.execute_actions("fake", [{"action": "delete", "googleId": "fictional", "summary": "Demo"}], True, 10, allow_deletes=True)
        network.assert_not_called()
        self.assertEqual(result["writes"], 0)
        self.assertEqual(result["plannedWrites"], 1)

    def test_write_cap_defers_remaining_operations(self):
        actions = [{"action": "create", "event": bridge.to_google_event(source_event(str(n)))} for n in range(3)]
        with patch.object(bridge, "google_request") as network:
            result = bridge.execute_actions("fake", actions, False, 1)
        self.assertEqual(network.call_count, 1)
        self.assertEqual(result["counts"]["deferred"], 2)

    def test_destination_id_is_url_encoded(self):
        with patch.object(bridge, "GOOGLE_CALENDAR_ID", "fictional/calendar@example.test"):
            with patch.object(bridge, "google_request") as network:
                bridge.execute_actions("fake", [{"action": "create", "event": bridge.to_google_event(source_event())}], False, 1)
        self.assertIn("fictional%2Fcalendar%40example.test", network.call_args.args[2])

    def test_all_day_date_is_preserved_east_of_utc(self):
        source = source_event(); source.update(isAllDay=True, originalStartTimeZone="India Standard Time", originalEndTimeZone="India Standard Time")
        source["start"]["dateTime"] = "2026-11-02T18:30:00Z"
        source["end"]["dateTime"] = "2026-11-03T18:30:00Z"
        payload = bridge.to_google_event(source)
        self.assertEqual(payload["start"], {"date": "2026-11-03"})
        self.assertEqual(payload["end"], {"date": "2026-11-04"})

    def test_all_day_date_is_preserved_west_of_utc(self):
        source = source_event(); source.update(isAllDay=True, originalStartTimeZone="Pacific Standard Time", originalEndTimeZone="Pacific Standard Time")
        source["start"]["dateTime"] = "2026-11-03T08:00:00Z"
        source["end"]["dateTime"] = "2026-11-04T08:00:00Z"
        self.assertEqual(bridge.to_google_event(source)["start"], {"date": "2026-11-03"})

    def test_unknown_all_day_zone_fails_before_writing(self):
        source = source_event(); source.update(isAllDay=True, originalStartTimeZone="tzone://Microsoft/Custom")
        with patch.object(bridge, "google_request") as network:
            with self.assertRaises(ValueError): bridge.plan_actions([source], [])
        network.assert_not_called()

    def test_unexpected_pagination_origin_is_rejected(self):
        response = Mock(); response.json.return_value = {"value": [], "@odata.nextLink": "https://untrusted.example/page"}
        with patch.object(bridge.requests, "get", return_value=response) as network:
            with self.assertRaises(ValueError):
                from datetime import datetime, timezone
                bridge.fetch_outlook("fake", datetime.now(timezone.utc), datetime.now(timezone.utc))
        self.assertEqual(network.call_count, 1)


class ConfigurationTests(unittest.TestCase):
    def config(self, replacement=""):
        root = Path(__file__).resolve().parent
        value = (root / "config.example.toml").read_text().replace('client_id = ""', 'client_id = "00000000-0000-4000-8000-000000000000"')
        return value + replacement

    def load(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"config.toml"; path.write_text(text)
            return settings.load_config(path)

    def test_example_has_safe_defaults_and_relative_paths(self):
        result = self.load(self.config())
        self.assertFalse(result.copy_details)
        self.assertTrue(result.private_events)
        self.assertIsNone(result.fallback_cache)
        self.assertTrue(result.ms_cache.is_absolute())
        self.assertEqual(result.max_writes, 25)

    def test_blank_client_requires_own_registration(self):
        with self.assertRaises(ValueError): self.load(self.config().replace("00000000-0000-4000-8000-000000000000", ""))

    def test_authority_path_injection_rejected(self):
        with self.assertRaises(ValueError): self.load(self.config().replace('tenant = "organizations"', 'tenant = "other/path"'))

    def test_invalid_bounds_and_privacy_types_rejected(self):
        for old, new in [('days_future = 365', 'days_future = 0'), ('max_writes = 25', 'max_writes = -1'), ('copy_details = false', 'copy_details = "yes"')]:
            with self.subTest(new=new), self.assertRaises(ValueError): self.load(self.config().replace(old, new))


class CallbackTests(unittest.TestCase):
    def callback(self, query, *, host=None):
        with google_auth.CallbackServer("expected-state") as server:
            worker = threading.Thread(target=server.handle_request); worker.start()
            headers = {"Host": host} if host else {}
            response = requests.get(server.redirect_uri + "?" + query, headers=headers, timeout=5)
            worker.join(timeout=5)
            return response, server.code, server.error

    def test_callback_is_loopback_only_and_does_not_echo_code(self):
        with redirect_stderr(io.StringIO()) as logged:
            response, code, error = self.callback("state=expected-state&code=fictional-code")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(code, "fictional-code")
        self.assertIsNone(error)
        self.assertNotIn("fictional-code", response.text + logged.getvalue())
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_wrong_state_does_not_consume_login(self):
        response, code, error = self.callback("state=wrong&code=fictional-code")
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(code); self.assertIsNone(error)

    def test_wrong_host_is_rejected(self):
        response, code, _ = self.callback("state=expected-state&code=fictional-code", host="untrusted.example")
        self.assertEqual(response.status_code, 403); self.assertIsNone(code)

    def test_denied_consent_with_valid_state_stops_waiting(self):
        response, code, error = self.callback("state=expected-state&error=access_denied")
        self.assertEqual(response.status_code, 400); self.assertIsNone(code); self.assertIsNotNone(error)

    def test_duplicate_state_and_unicode_state_are_rejected(self):
        for suffix in ["state=expected-state&state=other&code=x", "state=%E2%98%83&code=x"]:
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                google_auth.parse_redirect("http://127.0.0.1/?"+suffix, "expected-state")

    def test_exchange_includes_verifier_and_exact_redirect(self):
        response = Mock(); response.json.return_value = {"access_token": "fictional-access", "refresh_token": "fictional-refresh", "expires_in": 3600}
        with patch.object(google_auth.requests, "post", return_value=response) as network:
            result = google_auth.exchange_code("fictional-client", "fictional-secret", "fictional-code", "verifier", "http://127.0.0.1:1234/oauth/callback")
        sent = network.call_args.kwargs["data"]
        self.assertEqual(sent["code_verifier"], "verifier")
        self.assertEqual(sent["redirect_uri"], "http://127.0.0.1:1234/oauth/callback")
        self.assertEqual(result["scopes"], [google_auth.SCOPE])


if __name__ == "__main__":
    unittest.main()
