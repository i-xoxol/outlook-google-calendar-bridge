#!/usr/bin/env python3
"""Desktop Google OAuth with PKCE and a temporary loopback-only callback."""
import argparse
import base64
import hashlib
import hmac
import json
import secrets
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
import ms_auth
from settings import load_config

SCOPE = "https://www.googleapis.com/auth/calendar.events"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_REDIRECT = "http://127.0.0.1:8765/oauth/callback"


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def authorization_url(client_id: str, state: str, verifier: str, redirect_uri: str = DEFAULT_REDIRECT) -> str:
    return AUTH_URI + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "false", "state": state,
        "code_challenge": pkce_challenge(verifier), "code_challenge_method": "S256",
    })


def parse_redirect(redirected_url: str, expected_state: str) -> str:
    query = parse_qs(urlparse(redirected_url).query)
    received = query.get("state", [""])[0]
    if len(query.get("state", [])) != 1 or not expected_state or not hmac.compare_digest(received.encode(), expected_state.encode()):
        raise ValueError("OAuth state mismatch")
    if "error" in query:
        raise ValueError("Google authorization was not granted")
    if len(query.get("code", [])) != 1:
        raise ValueError("Authorization callback must contain exactly one code")
    code = query.get("code", [None])[0]
    if not code:
        raise ValueError("Authorization callback contains no code")
    return code


class CallbackServer(HTTPServer):
    def __init__(self, state: str, port: int = 0):
        self.expected_state = state
        self.code = None
        self.error = None
        self.timeout = 1
        super().__init__(("127.0.0.1", port), CallbackHandler)

    @property
    def redirect_uri(self):
        return f"http://127.0.0.1:{self.server_port}/oauth/callback"


class CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        # Callback URLs contain a short-lived authorization code; never log them.
        pass

    def do_GET(self):
        if urlparse(self.path).path != "/oauth/callback":
            self.send_error(404)
            return
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_error(403)
            return
        try:
            code = parse_redirect(self.server.redirect_uri + "?" + urlparse(self.path).query,
                                  self.server.expected_state)
        except ValueError:
            query = parse_qs(urlparse(self.path).query)
            values = query.get("state", [])
            if len(values) == 1 and hmac.compare_digest(values[0].encode(), self.server.expected_state.encode()) and "error" in query:
                self.server.error = "Google authorization was not granted"
            self.send_error(400, "Authorization callback rejected")
            return
        if self.server.code is not None:
            self.send_error(409, "Authorization callback already used")
            return
        self.server.code = code
        body = b"<!doctype html><title>Calendar Bridge</title><h1>Authorization received</h1><p>Return to the terminal to confirm completion. You can close this tab.</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)


def client_values(path: Path):
    data = ms_auth._read_cache(path)
    client = data.get("installed")
    if not isinstance(client, dict) or not client.get("client_id") or not client.get("client_secret"):
        raise ValueError("Download the JSON credentials for a Google Desktop app")
    return client["client_id"], client["client_secret"]


def exchange_code(client_id, client_secret, code, verifier, redirect_uri):
    response = requests.post(TOKEN_URI, data={
        "client_id": client_id, "client_secret": client_secret, "code": code,
        "code_verifier": verifier, "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=30)
    response.raise_for_status()
    result = response.json()
    if not result.get("refresh_token") or not result.get("access_token"):
        raise RuntimeError("Google returned no renewable authorization; check consent settings")
    return {
        "token": result["access_token"], "refresh_token": result["refresh_token"],
        "client_id": client_id, "client_secret": client_secret, "token_uri": TOKEN_URI,
        "scopes": [SCOPE], "type": "authorized_user",
        "expiry": (datetime.now(timezone.utc) + timedelta(seconds=result["expires_in"])).isoformat(),
    }


def login(client_path: Path, token_path: Path, *, open_browser=True, timeout=300):
    client_id, client_secret = client_values(client_path)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    with CallbackServer(state) as server:
        url = authorization_url(client_id, state, verifier, server.redirect_uri)
        print("Open this Google authorization URL on THIS machine:\n" + url, flush=True)
        if open_browser:
            webbrowser.open(url)
        deadline = time.monotonic() + timeout
        while server.code is None and server.error is None and time.monotonic() < deadline:
            server.handle_request()
        if server.error:
            raise RuntimeError(server.error)
        if server.code is None:
            raise RuntimeError("Google sign-in timed out; retry the login command")
        token = exchange_code(client_id, client_secret, server.code, verifier, server.redirect_uri)
    ms_auth.write_private(token_path, json.dumps(token, indent=2) + "\n")
    print("Google Calendar authorization saved in a private local file. No token is displayed.")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["login"])
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    settings = load_config(args.config, require_client=False)
    return login(settings.google_client, settings.google_token, open_browser=not args.no_browser)


if __name__ == "__main__":
    sys.exit(main())
