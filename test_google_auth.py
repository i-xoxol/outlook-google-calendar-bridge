import base64
import hashlib
import unittest
from urllib.parse import parse_qs, urlparse

import google_auth


class GoogleAuthTests(unittest.TestCase):
    def test_pkce_challenge_is_urlsafe_sha256_without_padding(self):
        verifier = "test-verifier-123"
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        self.assertEqual(google_auth.pkce_challenge(verifier), expected)

    def test_parse_redirect_extracts_code_and_matching_state(self):
        code = google_auth.parse_redirect(
            "http://localhost:1/?code=abc123&state=state456",
            expected_state="state456",
        )
        self.assertEqual(code, "abc123")

    def test_parse_redirect_rejects_wrong_state(self):
        with self.assertRaisesRegex(ValueError, "state mismatch"):
            google_auth.parse_redirect(
                "http://localhost:1/?code=abc123&state=wrong",
                expected_state="expected",
            )

    def test_authorization_url_requests_only_calendar_events(self):
        url = google_auth.authorization_url(
            client_id="client-id",
            state="state",
            verifier="verifier",
        )
        query = parse_qs(urlparse(url).query)
        self.assertEqual(
            query["scope"], ["https://www.googleapis.com/auth/calendar.events"]
        )
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["include_granted_scopes"], ["false"])


if __name__ == "__main__":
    unittest.main()
