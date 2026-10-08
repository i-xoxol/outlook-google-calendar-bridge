#!/usr/bin/env python3
"""Microsoft Graph device authentication with a private MSAL cache."""

import argparse
import fcntl
import json
import logging
import os
import stat
import sys
import tempfile
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

import msal
import requests

CLIENT_ID = ""
AUTHORITY = "https://login.microsoftonline.com/organizations"
SCOPES = ["User.Read", "Calendars.Read"]
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
MAX_CACHE_BYTES = 1024 * 1024


def configure(client_id: str, tenant: str = "organizations") -> None:
    global CLIENT_ID, AUTHORITY
    try:
        CLIENT_ID = str(uuid.UUID(client_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A Microsoft application ID from your own app registration is required") from None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", tenant):
        raise ValueError("Invalid Microsoft tenant")
    AUTHORITY = f"https://login.microsoftonline.com/{tenant}"


class SignInRequired(RuntimeError):
    """The identity provider requires an interactive sign-in."""


def _validate_private_file(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.resolve() != path.absolute():
        raise RuntimeError("Authentication cache must be a regular, non-symlink file")
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("Authentication cache must be owned by this user and private")
    if info.st_size > MAX_CACHE_BYTES:
        raise RuntimeError("Authentication cache exceeds the size limit")


def _private_parent(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.parent.stat()
    if path.parent.resolve() != path.parent.absolute():
        raise RuntimeError("Authentication cache directory must not use symlinks")
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise RuntimeError("Authentication cache directory has unsafe ownership or permissions")


def _read_cache(path: Path) -> dict:
    _validate_private_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise RuntimeError("Authentication cache is invalid") from None
    if not isinstance(data, dict):
        raise RuntimeError("Authentication cache is invalid")
    return data


@contextmanager
def _cache_lock(path: Path):
    _private_parent(path)
    lock = path.with_name("." + path.name + ".lock")
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError("Authentication cache lock is not private")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another authentication operation is running; retry next cycle") from None
        yield
    finally:
        os.close(fd)


def write_private(path: Path, text: str) -> None:
    _private_parent(path)
    if path.exists() or path.is_symlink():
        _validate_private_file(path)
    fd, temporary = tempfile.mkstemp(prefix=".auth-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _app_from_data(data: dict):
    if not CLIENT_ID:
        raise RuntimeError("Configure your own Microsoft client ID before authenticating")
    cache = msal.SerializableTokenCache()
    cache.deserialize(json.dumps(data))
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    return app, cache


def load_app(cache_path: Path) -> tuple[msal.PublicClientApplication, msal.SerializableTokenCache]:
    return _app_from_data(_read_cache(cache_path) if cache_path.exists() else {})


def save_cache(cache_path: Path, cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        write_private(cache_path, cache.serialize())


def _silent_result(app: msal.PublicClientApplication, *, force_refresh: bool = False):
    accounts = app.get_accounts()
    if len(accounts) != 1:
        raise SignInRequired("Exactly one Microsoft account must be cached; run login")
    try:
        return app.acquire_token_silent_with_error(SCOPES, account=accounts[0], force_refresh=force_refresh)
    except requests.RequestException:
        raise RuntimeError("Microsoft authentication is temporarily unavailable; retry next cycle") from None


def _require_token(result):
    if not result or "access_token" not in result:
        raise SignInRequired("Microsoft sign-in is required; run ms_auth.py login --cache <calendar cache>")
    return result


def acquire_silent(app: msal.PublicClientApplication) -> dict:
    return _require_token(_silent_result(app))


def _matching_identity(primary: dict, fallback: dict) -> dict:
    original = list(primary.get("Account", {}).values())
    other = list(fallback.get("Account", {}).values())
    if len(original) != 1 or len(other) != 1:
        raise RuntimeError("Automatic recovery requires one established account in both caches")
    account = original[0]
    for field in ("home_account_id", "environment", "realm", "username"):
        if not account.get(field) or str(account[field]).casefold() != str(other[0].get(field, "")).casefold():
            raise RuntimeError("Fallback authentication account or authority does not match")
    return account


def _rotate_refresh(primary: dict, fresh: dict, result: dict, account: dict) -> dict:
    repaired = json.loads(json.dumps(primary))
    def matches(value):
        return (value.get("home_account_id") == account["home_account_id"]
                and value.get("environment") == account["environment"]
                and value.get("client_id") == CLIENT_ID)
    old = [v for v in repaired.get("RefreshToken", {}).values() if matches(v)]
    new = [v for v in fresh.get("RefreshToken", {}).values()
           if matches(v) and v.get("secret") == result.get("refresh_token")]
    if not result.get("refresh_token") or len(old) != 1 or len(new) != 1:
        raise RuntimeError("Automatic recovery could not verify the application's refresh credential")
    if old[0].get("family_id") != new[0].get("family_id"):
        raise RuntimeError("Microsoft authentication application family does not match")
    old[0]["secret"] = new[0]["secret"]
    for field in ("cached_at", "last_modification_time"):
        if field in new[0]:
            old[0][field] = new[0][field]
    return repaired


def acquire_with_recovery(cache_path: Path, fallback_cache_path: Path | None = None) -> dict:
    """Refresh normally, or rotate from a verified same-account cache without modifying it."""
    with _cache_lock(cache_path):
        if not cache_path.exists():
            raise SignInRequired("No established calendar account is cached; run login")
        primary = _read_cache(cache_path)
        app, cache = _app_from_data(primary)
        result = _silent_result(app)
        if result and "access_token" in result:
            save_cache(cache_path, cache)
            return result
        if result and result.get("error") not in ("invalid_grant", "interaction_required"):
            raise RuntimeError("Microsoft authentication failed; automatic recovery is not applicable")
        if fallback_cache_path is None:
            return _require_token(result)
        if fallback_cache_path.absolute() == cache_path.absolute():
            raise RuntimeError("Fallback authentication cache must be a different file")
        if not fallback_cache_path.exists():
            raise SignInRequired("Fallback authentication is unavailable; sign in to Microsoft again")
        fallback = _read_cache(fallback_cache_path)
        account = _matching_identity(primary, fallback)
        if not any(v.get("client_id") == CLIENT_ID and v.get("home_account_id") == account["home_account_id"]
                   for v in fallback.get("RefreshToken", {}).values()):
            raise RuntimeError("Fallback authentication application does not match")
        fallback_app, fallback_cache = _app_from_data(fallback)
        fresh_result = _require_token(_silent_result(fallback_app, force_refresh=True))
        fresh_data = json.loads(fallback_cache.serialize())
        _matching_identity(primary, fresh_data)
        repaired = _rotate_refresh(primary, fresh_data, fresh_result, account)
        repaired_app, repaired_cache = _app_from_data(repaired)
        verified = _require_token(_silent_result(repaired_app, force_refresh=True))
        _matching_identity(primary, json.loads(repaired_cache.serialize()))
        write_private(cache_path, repaired_cache.serialize())
        logging.getLogger(__name__).warning("Microsoft calendar session recovered automatically from the configured same-account cache")
        return verified


def login(cache_path: Path) -> int:
    with _cache_lock(cache_path):
        return _login_locked(cache_path)


def _login_locked(cache_path: Path) -> int:
    app, cache = load_app(cache_path)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError("Microsoft device sign-in could not be started")
    print(flow["message"], flush=True)
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise SignInRequired("Microsoft device sign-in was not completed")
    save_cache(cache_path, cache)
    claims = result.get("id_token_claims", {})
    print(json.dumps({"authenticated": True, "account": claims.get("preferred_username"), "cache": str(cache_path)}))
    return 0


def verify(cache_path: Path, fallback_cache_path: Path | None = None) -> int:
    result = acquire_with_recovery(cache_path, fallback_cache_path)
    headers = {"Authorization": f"Bearer {result['access_token']}"}
    me = requests.get(f"{GRAPH_ROOT}/me?$select=displayName,userPrincipalName", headers=headers, timeout=30)
    me.raise_for_status()
    print(json.dumps({"authenticated": True, **me.json()}))
    return 0


def main() -> int:
    from settings import load_config
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["login", "verify"])
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--fallback-cache", type=Path)
    args = parser.parse_args()
    settings = load_config(args.config)
    configure(settings.client_id, settings.tenant)
    cache_path = args.cache or settings.ms_cache
    fallback_path = args.fallback_cache or settings.fallback_cache
    return login(cache_path) if args.command == "login" else verify(cache_path, fallback_path)


if __name__ == "__main__":
    sys.exit(main())
