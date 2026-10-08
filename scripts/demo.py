"""A repeatable demonstration using fictional events; no OAuth or network requests."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import calendar_bridge as bridge


def demo():
    def event(identifier, title, hour):
        return {"id": identifier, "subject": title, "start": {"dateTime": f"2026-11-03T{hour:02}:00:00Z", "timeZone": "UTC"},
                "end": {"dateTime": f"2026-11-03T{hour+1:02}:00:00Z", "timeZone": "UTC"},
                "isAllDay": False, "showAs": "busy", "sensitivity": "normal", "isReminderOn": False}
    source = [event("demo-review", "Design review", 9), event("demo-focus", "Focus session", 11),
              event("demo-planning", "Quarterly planning", 14)]
    destination = [bridge.to_google_event(event("demo-review", "Earlier review title", 9)),
                   bridge.to_google_event(source[2]), bridge.to_google_event(event("demo-obsolete", "Old appointment", 16)),
                   {"id": "personal-note", "summary": "Personal time", "start": {"dateTime": "2026-11-03T18:00:00Z"},
                    "end": {"dateTime": "2026-11-03T19:00:00Z"}}]
    for number, record in enumerate(destination):
        record.setdefault("id", f"demo-google-{number}")
    plan = bridge.plan_actions(source, destination)
    preview = bridge.execute_actions("unused-fictional-token", plan, True, 25, allow_deletes=True)
    print("FICTIONAL DEMO — no accounts, calendar writes, or network calls")
    print(json.dumps(preview, indent=2))
    applied = {item["id"]: item for item in destination}
    for action in plan:
        if action["action"] == "create":
            applied["demo-new"] = {"id": "demo-new", **action["event"]}
        elif action["action"] == "update":
            applied[action["googleId"]] = {"id": action["googleId"], **action["event"]}
        elif action["action"] == "delete":
            del applied[action["googleId"]]
    remaining = bridge.plan_actions(source, list(applied.values()))
    assert remaining == []
    assert applied["personal-note"]["summary"] == "Personal time"
    print("Second reconciliation: 0 changes. Personal event preserved.")
    return preview


if __name__ == "__main__":
    demo()
