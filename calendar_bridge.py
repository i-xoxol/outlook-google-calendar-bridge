#!/usr/bin/env python3
"""One-way Outlook-to-Google calendar reconciler."""

import argparse
import html
import json
import os
import re
import stat
import sys
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from tzlocal.windows_tz import win_tz

import requests

import ms_auth

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GOOGLE_ROOT = "https://www.googleapis.com/calendar/v3"
BRIDGE_NAME = "calendar-bridge"
TITLE_SUFFIX = " [Work]"
GOOGLE_COLOR_ID = "6"  # Tangerine / orange
GOOGLE_CALENDAR_ID = "primary"
COPY_DETAILS = False
PRIVATE_EVENTS = True
GRAPH_FIELDS = [
    "id",
    "iCalUId",
    "subject",
    "body",
    "start",
    "end",
    "isAllDay",
    "isCancelled",
    "location",
    "onlineMeeting",
    "onlineMeetingUrl",
    "webLink",
    "showAs",
    "sensitivity",
    "isReminderOn",
    "reminderMinutesBeforeStart",
    "lastModifiedDateTime",
    "type",
    "seriesMasterId",
    "originalStartTimeZone",
    "originalEndTimeZone",
]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value or "")
    text = html.unescape("".join(parser.parts)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def normalized_datetime(value: str) -> str:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def signature(event: dict) -> tuple[str, str, str]:
    start = event.get("start", {})
    end = event.get("end", {})
    start_value = start.get("date") or normalized_datetime(start.get("dateTime", ""))
    end_value = end.get("date") or normalized_datetime(end.get("dateTime", ""))
    return (event.get("summary", "").strip(), start_value, end_value)


def _body_text(source: dict) -> str:
    body = source.get("body") or {}
    content = body.get("content") or ""
    if body.get("contentType", "").lower() == "html":
        content = html_to_text(content)
    content = content.strip()
    join_url = ((source.get("onlineMeeting") or {}).get("joinUrl") or source.get("onlineMeetingUrl") or "").strip()
    if join_url and join_url not in content:
        content = f"{content}\n\nOnline meeting: {join_url}".strip()
    web_link = (source.get("webLink") or "").strip()
    if web_link and web_link not in content:
        content = f"{content}\n\nOutlook event: {web_link}".strip()
    return content


def all_day_date(source: dict, boundary: str) -> str:
    point = source[boundary]
    original = source.get("originalStartTimeZone" if boundary == "start" else "originalEndTimeZone")
    zone = original or point.get("timeZone", "UTC")
    try:
        original_zone = ZoneInfo(win_tz.get(zone, zone))
        response_zone = ZoneInfo(win_tz.get(point.get("timeZone", "UTC"), point.get("timeZone", "UTC")))
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("An all-day event uses an unsupported time zone; no changes were applied") from None
    instant = datetime.fromisoformat(point["dateTime"].replace("Z", "+00:00"))
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=response_zone)
    return instant.astimezone(original_zone).date().isoformat()


def to_google_event(source: dict) -> dict:
    subject = source.get("subject") or "(No title)"
    event: dict = {
        "summary": f"{subject}{TITLE_SUFFIX}",
        "description": _body_text(source) if COPY_DETAILS else "",
        "colorId": GOOGLE_COLOR_ID,
        "transparency": "transparent" if source.get("showAs") == "free" else "opaque",
        "visibility": "private" if PRIVATE_EVENTS or source.get("sensitivity") in {"personal", "private", "confidential"} else "default",
        "extendedProperties": {
            "private": {
                "bridgeName": BRIDGE_NAME,
                "outlookEventId": source["id"],
                "outlookICalUID": source.get("iCalUId") or "",
                "outlookLastModified": source.get("lastModifiedDateTime") or "",
            }
        },
    }
    location = (source.get("location") or {}).get("displayName")
    event["location"] = location if location and COPY_DETAILS else ""
    if source.get("isAllDay"):
        event["start"] = {"date": all_day_date(source, "start")}
        event["end"] = {"date": all_day_date(source, "end")}
    else:
        event["start"] = {"dateTime": normalized_datetime(source["start"]["dateTime"])}
        event["end"] = {"dateTime": normalized_datetime(source["end"]["dateTime"])}
    if source.get("isReminderOn") and source.get("reminderMinutesBeforeStart") is not None:
        event["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": int(source["reminderMinutesBeforeStart"])}],
        }
    else:
        event["reminders"] = {"useDefault": False, "overrides": []}
    return event


def write_private_json(path: Path, value: dict) -> None:
    ms_auth.write_private(path, json.dumps(value, indent=2) + "\n")


def microsoft_token(cache_path: Path, fallback_cache_path: Path | None = None) -> str:
    result = ms_auth.acquire_with_recovery(cache_path, fallback_cache_path)
    return result["access_token"]


def google_token(token_path: Path) -> str:
    token = ms_auth._read_cache(token_path)
    if token.get("token_uri") != "https://oauth2.googleapis.com/token":
        raise ValueError("Unsupported Google token endpoint")
    response = requests.post(
        token["token_uri"],
        data={
            "client_id": token["client_id"],
            "client_secret": token["client_secret"],
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    response.raise_for_status()
    refreshed = response.json()
    token["token"] = refreshed["access_token"]
    if refreshed.get("refresh_token"):
        token["refresh_token"] = refreshed["refresh_token"]
    token["expiry"] = (datetime.now(timezone.utc) + timedelta(seconds=refreshed["expires_in"])).isoformat().replace("+00:00", "Z")
    write_private_json(token_path, token)
    return token["token"]


def fetch_outlook(token: str, start: datetime, end: datetime) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.timezone="UTC", outlook.body-content-type="html", IdType="ImmutableId"',
    }
    params = {
        "startDateTime": start.isoformat().replace("+00:00", "Z"),
        "endDateTime": end.isoformat().replace("+00:00", "Z"),
        "$select": ",".join(field for field in GRAPH_FIELDS if COPY_DETAILS or field not in {"body", "location", "onlineMeeting", "onlineMeetingUrl", "webLink"}),
        "$top": "250",
    }
    url = f"{GRAPH_ROOT}/me/calendarView"
    events: list[dict] = []
    while url:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com" or not parsed.path.startswith("/v1.0/"):
            raise ValueError("Unexpected Microsoft pagination URL")
        response = requests.get(url, headers=headers, params=params if not events else None, timeout=30)
        response.raise_for_status()
        page = response.json()
        events.extend(page.get("value", []))
        url = page.get("@odata.nextLink")
        params = None
    return [event for event in events if not event.get("isCancelled")]


def google_request(method: str, token: str, path: str, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    response = requests.request(method, f"{GOOGLE_ROOT}{path}", headers=headers, timeout=30, **kwargs)
    response.raise_for_status()
    return response


def fetch_google(token: str, start: datetime, end: datetime) -> list[dict]:
    params = {
        "timeMin": start.isoformat().replace("+00:00", "Z"),
        "timeMax": end.isoformat().replace("+00:00", "Z"),
        "singleEvents": "true",
        "showDeleted": "false",
        "maxResults": "2500",
    }
    events: list[dict] = []
    page_token = None
    while True:
        if page_token:
            params["pageToken"] = page_token
        page = google_request("GET", token, f"/calendars/{quote(GOOGLE_CALENDAR_ID, safe='')}/events", params=params).json()
        events.extend(page.get("items", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            return events


def relevant_google_fields(event: dict) -> dict:
    start = event.get("start", {})
    end = event.get("end", {})
    canonical_start = {"date": start["date"]} if "date" in start else {"dateTime": normalized_datetime(start["dateTime"])}
    canonical_end = {"date": end["date"]} if "date" in end else {"dateTime": normalized_datetime(end["dateTime"])}
    reminders = event.get("reminders") or {"useDefault": False}
    canonical_reminders = {"useDefault": reminders.get("useDefault", False)}
    if not canonical_reminders["useDefault"]:
        canonical_reminders["overrides"] = reminders.get("overrides", [])
    return {
        "summary": event.get("summary", ""),
        "description": event.get("description", ""),
        "colorId": event.get("colorId"),
        "location": event.get("location", ""),
        "start": canonical_start,
        "end": canonical_end,
        "transparency": event.get("transparency", "opaque"),
        "visibility": event.get("visibility", "default"),
        "reminders": canonical_reminders,
        "extendedProperties": {"private": {key: value for key, value in
            (event.get("extendedProperties", {}).get("private", {})).items()
            if key in {"bridgeName", "outlookEventId", "outlookICalUID", "outlookLastModified"}}},
    }


def plan_actions(outlook_events: list[dict], google_events: list[dict]) -> list[dict]:
    managed: dict[str, dict] = {}
    unmanaged_signatures = set()
    for event in google_events:
        private = ((event.get("extendedProperties") or {}).get("private") or {})
        if private.get("bridgeName") == BRIDGE_NAME and private.get("outlookEventId"):
            managed[private["outlookEventId"]] = event
        else:
            try:
                unmanaged_signatures.add(signature(event))
            except (KeyError, ValueError):
                pass

    actions: list[dict] = []
    source_ids = set()
    for source in outlook_events:
        source_ids.add(source["id"])
        desired = to_google_event(source)
        existing = managed.get(source["id"])
        if existing:
            if relevant_google_fields(existing) != relevant_google_fields(desired):
                actions.append({"action": "update", "googleId": existing["id"], "event": desired})
            continue
        if signature(desired) in unmanaged_signatures:
            actions.append({"action": "skip-existing", "event": desired})
        else:
            actions.append({"action": "create", "event": desired})

    for outlook_id, existing in managed.items():
        if outlook_id not in source_ids:
            actions.append({"action": "delete", "googleId": existing["id"], "summary": existing.get("summary", "")})
    return actions


def execute_actions(token: str, actions: list[dict], dry_run: bool, max_writes: int | None, *, allow_deletes: bool = False) -> dict:
    counts = {"create": 0, "update": 0, "delete": 0, "skip-existing": 0, "delete-skipped": 0, "deferred": 0}
    writes = 0
    executed: list[dict] = []
    for action in actions:
        kind = action["action"]
        if kind == "delete" and not allow_deletes:
            counts["delete-skipped"] += 1
            continue
        if kind == "skip-existing":
            counts[kind] += 1
            executed.append({"action": kind, "summary": action["event"]["summary"]})
            continue
        if max_writes is not None and writes >= max_writes:
            counts["deferred"] += 1
            continue
        summary = (action.get("event") or {}).get("summary") or action.get("summary", "")
        if not dry_run:
            if kind == "create":
                google_request("POST", token, f"/calendars/{quote(GOOGLE_CALENDAR_ID, safe='')}/events", json=action["event"])
            elif kind == "update":
                google_request("PATCH", token, f"/calendars/{quote(GOOGLE_CALENDAR_ID, safe='')}/events/{quote(action['googleId'], safe='')}", json=action["event"])
            elif kind == "delete":
                google_request("DELETE", token, f"/calendars/{quote(GOOGLE_CALENDAR_ID, safe='')}/events/{quote(action['googleId'], safe='')}")
        writes += 1
        counts[kind] += 1
        executed.append({"action": kind, "summary": summary})
    return {"dryRun": dry_run, "counts": counts, "actions": executed,
            "plannedWrites": writes, "writes": 0 if dry_run else writes}


def main() -> int:
    from settings import load_config
    global BRIDGE_NAME, TITLE_SUFFIX, GOOGLE_COLOR_ID, GOOGLE_CALENDAR_ID, COPY_DETAILS, PRIVATE_EVENTS
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--ms-cache", type=Path)
    parser.add_argument("--ms-fallback-cache", type=Path, help="Optional private cache for the same Microsoft account and application")
    parser.add_argument("--google-token", type=Path)
    parser.add_argument("--days-past", type=int)
    parser.add_argument("--days-future", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Perform writes; otherwise only preview")
    parser.add_argument("--allow-deletes", action="store_true", help="Allow pruning bridge-managed copies")
    parser.add_argument("--show-details", action="store_true", help="Include event names in local output")
    parser.add_argument("--max-writes", type=int)
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("Choose --apply or --dry-run")
    settings = load_config(args.config)
    ms_auth.configure(settings.client_id, settings.tenant)
    args.ms_cache = args.ms_cache or settings.ms_cache
    args.ms_fallback_cache = args.ms_fallback_cache or settings.fallback_cache
    args.google_token = args.google_token or settings.google_token
    args.days_past = settings.days_past if args.days_past is None else args.days_past
    args.days_future = settings.days_future if args.days_future is None else args.days_future
    args.max_writes = settings.max_writes if args.max_writes is None else args.max_writes
    if not (0 <= args.days_past <= 3660 and 1 <= args.days_future <= 3660 and 1 <= args.max_writes <= 1000):
        parser.error("Invalid window or write limit")
    BRIDGE_NAME, TITLE_SUFFIX, GOOGLE_COLOR_ID = settings.bridge_name, settings.title_suffix, settings.color_id
    GOOGLE_CALENDAR_ID, COPY_DETAILS, PRIVATE_EVENTS = settings.google_calendar, settings.copy_details, settings.private_events
    args.dry_run = not args.apply

    # One writer per state directory, including manual invocations alongside the timer.
    with ms_auth._cache_lock(args.ms_cache.with_name("calendar-sync")):
        return run_sync(args)


def run_sync(args) -> int:

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=args.days_past)
    end = now + timedelta(days=args.days_future)
    ms_token = microsoft_token(args.ms_cache, args.ms_fallback_cache)
    g_token = google_token(args.google_token)
    outlook = fetch_outlook(ms_token, start, end)
    google = fetch_google(g_token, start, end)
    actions = plan_actions(outlook, google)
    result = execute_actions(g_token, actions, args.dry_run, args.max_writes, allow_deletes=args.allow_deletes)
    result.update({"outlookEvents": len(outlook), "googleEventsScanned": len(google), "windowStart": start.isoformat(), "windowEnd": end.isoformat()})
    if not args.show_details:
        result.pop("actions", None)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ms_auth.SignInRequired:
        print(json.dumps({"status": "sign-in-required", "message": "Renew the affected authorization using the setup guide"}), file=sys.stderr)
        sys.exit(2)
    except requests.HTTPError as error:
        print(json.dumps({"status": "provider-error", "httpStatus": error.response.status_code if error.response is not None else None}), file=sys.stderr)
        sys.exit(1)
    except (ValueError, RuntimeError, OSError):
        print(json.dumps({"status": "configuration-or-state-error", "message": "Check private file permissions and the troubleshooting guide"}), file=sys.stderr)
        sys.exit(1)
