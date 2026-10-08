"""Validated, deployment-neutral configuration. Python 3.11+ uses stdlib TOML."""
from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
import uuid


@dataclass(frozen=True)
class Settings:
    client_id: str
    tenant: str
    ms_cache: Path
    fallback_cache: Path | None
    google_client: Path
    google_token: Path
    google_calendar: str
    days_past: int
    days_future: int
    bridge_name: str
    title_suffix: str
    color_id: str
    copy_details: bool
    private_events: bool
    max_writes: int


def load_config(path: Path, *, require_client: bool = True) -> Settings:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    microsoft = data.get("microsoft", {})
    google = data.get("google", {})
    sync = data.get("sync", {})
    client = microsoft.get("client_id", "")
    if require_client:
        try:
            client = str(uuid.UUID(client))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Set microsoft.client_id to your own Entra application ID") from None
    tenant = microsoft.get("tenant", "organizations")
    if not isinstance(tenant, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", tenant):
        raise ValueError("Microsoft tenant must be a tenant ID, domain, or organizations/common/consumers")
    base = path.absolute().parent
    def file_path(value):
        if not isinstance(value, str) or not value:
            raise ValueError("Credential paths must be nonempty strings")
        item = Path(value).expanduser()
        return item if item.is_absolute() else base / item
    fallback = microsoft.get("fallback_cache", "")
    past = sync.get("days_past", 30)
    future = sync.get("days_future", 365)
    limit = sync.get("max_writes", 25)
    if any(type(value) is not int for value in (past, future, limit)) or not (0 <= past <= 3660 and 1 <= future <= 3660 and 1 <= limit <= 1000):
        raise ValueError("Invalid sync window or write limit")
    bridge = sync.get("bridge_name", "calendar-bridge")
    if not isinstance(bridge, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", bridge):
        raise ValueError("bridge_name must be a stable, short identifier")
    suffix = sync.get("title_suffix", " [Work]")
    color = str(sync.get("color_id", "6"))
    if not isinstance(suffix, str) or len(suffix) > 80 or color not in {str(n) for n in range(1, 12)}:
        raise ValueError("Invalid title suffix or Google event color")
    details = sync.get("copy_details", False)
    private = sync.get("private_events", True)
    if type(details) is not bool or type(private) is not bool:
        raise ValueError("Privacy settings must be booleans")
    calendar = google.get("calendar_id", "primary")
    if not isinstance(calendar, str) or not calendar:
        raise ValueError("Google destination calendar_id must be nonempty")
    return Settings(client, tenant, file_path(microsoft.get("cache", "private/msal_cache.json")),
                    file_path(fallback) if fallback else None,
                    file_path(google.get("client", "private/google-client.json")),
                    file_path(google.get("token", "private/google-token.json")), calendar,
                    past, future, bridge, suffix, color, details, private, limit)
