import os
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import ms_auth


class MicrosoftAuthTests(unittest.TestCase):
    def test_write_private_creates_owner_only_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            ms_auth.write_private(path, "secret")
            self.assertEqual(path.read_text(), "secret")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_requested_scopes_are_read_only_calendar_scopes(self):
        self.assertEqual(ms_auth.SCOPES, ["User.Read", "Calendars.Read"])

    def test_atomic_save_failure_preserves_previous_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            ms_auth.write_private(path, "previous")
            with patch.object(ms_auth.os, "replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    ms_auth.write_private(path, "replacement")
            self.assertEqual(path.read_text(), "previous")
            self.assertEqual(list(Path(directory).glob(".auth-*")), [])

    def test_save_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            link = Path(directory) / "cache.json"
            ms_auth.write_private(target, "original")
            link.symlink_to(target)
            with self.assertRaises(RuntimeError):
                ms_auth.write_private(link, "replacement")
            self.assertEqual(target.read_text(), "original")


def cache_fixture(secret="old-refresh"):
    return {
        "Account": {"account": {"home_account_id": "user.tenant", "environment": "login.windows.net",
                                  "realm": "tenant", "username": "owner@example.test"}},
        "RefreshToken": {"refresh": {"home_account_id": "user.tenant", "environment": "login.windows.net",
                                     "client_id": ms_auth.CLIENT_ID, "family_id": "1",
                                     "target": "User.Read Calendars.Read", "secret": secret}},
        "AppMetadata": {"app": {"client_id": ms_auth.CLIENT_ID}},
    }


class FakeCache:
    def __init__(self, data, changed=False):
        self.data = data
        self.has_state_changed = changed

    def serialize(self):
        return json.dumps(self.data)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        client = patch.object(ms_auth, "CLIENT_ID", "00000000-0000-4000-8000-000000000000")
        client.start()
        self.addCleanup(client.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.primary = Path(self.directory.name) / "calendar.json"
        self.fallback = Path(self.directory.name) / "outlook.json"
        ms_auth.write_private(self.primary, json.dumps(cache_fixture()))
        ms_auth.write_private(self.fallback, json.dumps(cache_fixture("fallback-refresh")))
        self.original_primary = self.primary.read_bytes()
        self.original_fallback = self.fallback.read_bytes()
        self.calls = []
        self.apps = []

    def factory(self, results):
        responses = iter(results)
        def make(data):
            index = len(self.calls)
            self.calls.append(data)
            stored = json.loads(json.dumps(data))
            if index == 1:
                stored["RefreshToken"]["refresh"]["secret"] = "new-refresh"
            app = Mock()
            self.apps.append(app)
            app.get_accounts.return_value = list(data.get("Account", {}).values())
            response = next(responses)
            if isinstance(response, Exception):
                app.acquire_token_silent_with_error.side_effect = response
            else:
                app.acquire_token_silent_with_error.return_value = response
            return app, FakeCache(stored)
        return make

    def recover(self):
        results = [{"error": "invalid_grant", "error_description": "old secret must not appear in logs"},
                   {"access_token": "fallback-access", "refresh_token": "new-refresh"},
                   {"access_token": "verified-access"}]
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory(results)):
            with self.assertLogs("ms_auth", level="WARNING") as captured:
                result = ms_auth.acquire_with_recovery(self.primary, self.fallback)
        return result, captured

    def test_expired_session_recovers_and_preserves_mail_cache(self):
        result, captured = self.recover()
        self.assertEqual(result["access_token"], "verified-access")
        saved = json.loads(self.primary.read_text())
        self.assertEqual(saved["RefreshToken"]["refresh"]["secret"], "new-refresh")
        self.assertEqual(saved["RefreshToken"]["refresh"]["target"], "User.Read Calendars.Read")
        self.assertEqual(self.fallback.read_bytes(), self.original_fallback)
        self.assertEqual(stat.S_IMODE(self.primary.stat().st_mode), 0o600)
        self.assertEqual(saved["Account"], cache_fixture()["Account"])
        self.assertNotIn("secret", " ".join(captured.output))
        self.assertEqual(len(self.calls), 3)
        for index, app in enumerate(self.apps):
            self.assertEqual(app.acquire_token_silent_with_error.call_args.args, (ms_auth.SCOPES,))
            self.assertEqual(app.acquire_token_silent_with_error.call_args.kwargs["force_refresh"], index > 0)

    def test_valid_session_does_not_open_fallback(self):
        self.fallback.unlink()
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory([{"access_token": "valid"}])):
            result = ms_auth.acquire_with_recovery(self.primary, self.fallback)
        self.assertEqual(result["access_token"], "valid")
        self.assertEqual(len(self.calls), 1)

    def assert_rejected_fallback(self, data):
        ms_auth.write_private(self.fallback, json.dumps(data))
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory([{"error": "invalid_grant"}])):
            with self.assertRaises(RuntimeError):
                ms_auth.acquire_with_recovery(self.primary, self.fallback)
        self.assertEqual(self.primary.read_bytes(), self.original_primary)
        self.assertEqual(len(self.calls), 1)

    def test_wrong_account_rejected_before_fallback_request(self):
        data = cache_fixture(); data["Account"]["account"]["home_account_id"] = "other.tenant"
        self.assert_rejected_fallback(data)

    def test_wrong_tenant_rejected_before_fallback_request(self):
        data = cache_fixture(); data["Account"]["account"]["realm"] = "other-tenant"
        self.assert_rejected_fallback(data)

    def test_wrong_authority_rejected_before_fallback_request(self):
        data = cache_fixture(); data["Account"]["account"]["environment"] = "other-authority"
        self.assert_rejected_fallback(data)

    def test_wrong_application_rejected_before_fallback_request(self):
        data = cache_fixture(); data["RefreshToken"]["refresh"]["client_id"] = "other-app"
        self.assert_rejected_fallback(data)

    def test_ambiguous_accounts_rejected(self):
        data = cache_fixture(); data["Account"]["other"] = dict(data["Account"]["account"])
        self.assert_rejected_fallback(data)

    def test_shared_fallback_file_rejected(self):
        self.fallback.chmod(0o644)
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory([None])):
            with self.assertRaises(RuntimeError):
                ms_auth.acquire_with_recovery(self.primary, self.fallback)
        self.assertEqual(self.primary.read_bytes(), self.original_primary)

    def test_fallback_symlink_rejected(self):
        link = Path(self.directory.name) / "linked.json"
        link.symlink_to(self.fallback)
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory([None])):
            with self.assertRaises(RuntimeError):
                ms_auth.acquire_with_recovery(self.primary, link)
        self.assertEqual(self.primary.read_bytes(), self.original_primary)

    def test_same_cache_cannot_be_used_as_fallback(self):
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory([None])):
            with self.assertRaisesRegex(RuntimeError, "different file"):
                ms_auth.acquire_with_recovery(self.primary, self.primary)

    def test_different_refresh_family_rejected(self):
        data = cache_fixture(); data["RefreshToken"]["refresh"]["family_id"] = "different"
        ms_auth.write_private(self.fallback, json.dumps(data))
        results = [None, {"access_token": "fallback", "refresh_token": "new-refresh"}]
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory(results)):
            with self.assertRaisesRegex(RuntimeError, "family"):
                ms_auth.acquire_with_recovery(self.primary, self.fallback)
        self.assertEqual(self.primary.read_bytes(), self.original_primary)

    def test_identity_changed_by_provider_is_rejected(self):
        results = [None, {"access_token": "fallback", "refresh_token": "new-refresh"}]
        factory = self.factory(results)
        def changed(data):
            app, cache = factory(data)
            if len(self.calls) == 2:
                cache.data["Account"]["account"]["home_account_id"] = "different.tenant"
            return app, cache
        with patch.object(ms_auth, "_app_from_data", side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                ms_auth.acquire_with_recovery(self.primary, self.fallback)
        self.assertEqual(self.primary.read_bytes(), self.original_primary)

    def test_both_expired_require_sign_in_without_overwriting_cache(self):
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory([None, {"error": "invalid_grant"}])):
            with self.assertRaises(ms_auth.SignInRequired):
                ms_auth.acquire_with_recovery(self.primary, self.fallback)
        self.assertEqual(self.primary.read_bytes(), self.original_primary)
        self.assertEqual(self.fallback.read_bytes(), self.original_fallback)

    def test_unverified_replacement_is_not_saved(self):
        results = [None, {"access_token": "fallback", "refresh_token": "new-refresh"}, None]
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory(results)):
            with self.assertRaises(ms_auth.SignInRequired):
                ms_auth.acquire_with_recovery(self.primary, self.fallback)
        self.assertEqual(self.primary.read_bytes(), self.original_primary)

    def test_unrelated_failure_does_not_try_fallback(self):
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory([{"error": "invalid_client"}])):
            with self.assertRaises(RuntimeError):
                ms_auth.acquire_with_recovery(self.primary, self.fallback)
        self.assertEqual(len(self.calls), 1)

    def test_network_error_is_sanitized_and_cache_unchanged(self):
        error = ms_auth.requests.ConnectionError("a confidential detail")
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory([error])):
            with self.assertRaisesRegex(RuntimeError, "temporarily unavailable") as captured:
                ms_auth.acquire_with_recovery(self.primary, self.fallback)
        self.assertNotIn("confidential", str(captured.exception))
        self.assertEqual(self.primary.read_bytes(), self.original_primary)

    def test_concurrent_writer_is_rejected_without_waiting(self):
        with ms_auth._cache_lock(self.primary):
            with self.assertRaisesRegex(RuntimeError, "Another authentication operation"):
                ms_auth.acquire_with_recovery(self.primary, self.fallback)

    def test_no_established_identity_requires_sign_in(self):
        ms_auth.write_private(self.primary, "{}")
        with patch.object(ms_auth, "_app_from_data", side_effect=self.factory([None])):
            with self.assertRaises(ms_auth.SignInRequired):
                ms_auth.acquire_with_recovery(self.primary, self.fallback)


if __name__ == "__main__":
    unittest.main()
