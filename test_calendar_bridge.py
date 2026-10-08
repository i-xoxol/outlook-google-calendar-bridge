import unittest
from unittest.mock import patch

import calendar_bridge


class CalendarBridgeTests(unittest.TestCase):
    def setUp(self):
        self.details = patch.object(calendar_bridge, "COPY_DETAILS", True)
        self.details.start()
        self.addCleanup(self.details.stop)
    def test_html_body_is_converted_to_readable_text(self):
        self.assertEqual(
            calendar_bridge.html_to_text("<p>Hello<br>world &amp; team</p>"),
            "Hello\nworld & team",
        )

    def test_timed_event_copies_details_but_never_attendees(self):
        source = {
            "id": "outlook-id",
            "iCalUId": "ical-id",
            "subject": "Project review",
            "body": {"contentType": "html", "content": "<p>Agenda</p>"},
            "start": {"dateTime": "2026-08-25T14:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-08-25T15:00:00.0000000", "timeZone": "UTC"},
            "isAllDay": False,
            "location": {"displayName": "Demo room"},
            "onlineMeeting": {"joinUrl": "https://teams.example/join"},
            "showAs": "busy",
            "sensitivity": "private",
            "isReminderOn": True,
            "reminderMinutesBeforeStart": 15,
            "attendees": [{"emailAddress": {"address": "never@example.com"}}],
        }
        result = calendar_bridge.to_google_event(source)
        self.assertEqual(result["summary"], "Project review [Work]")
        self.assertEqual(result["colorId"], "6")
        self.assertEqual(result["location"], "Demo room")
        self.assertIn("Agenda", result["description"])
        self.assertIn("https://teams.example/join", result["description"])
        self.assertEqual(result["visibility"], "private")
        self.assertNotIn("attendees", result)
        self.assertEqual(result["extendedProperties"]["private"]["outlookEventId"], "outlook-id")

    def test_all_day_event_uses_exclusive_date_range(self):
        source = {
            "id": "all-day",
            "subject": "Holiday",
            "body": {"contentType": "text", "content": ""},
            "start": {"dateTime": "2026-09-01T00:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-09-02T00:00:00.0000000", "timeZone": "UTC"},
            "isAllDay": True,
            "location": {},
            "showAs": "free",
            "sensitivity": "normal",
            "isReminderOn": False,
        }
        result = calendar_bridge.to_google_event(source)
        self.assertEqual(result["start"], {"date": "2026-09-01"})
        self.assertEqual(result["end"], {"date": "2026-09-02"})
        self.assertEqual(result["transparency"], "transparent")

    def test_signature_compares_title_and_time(self):
        event = {
            "summary": "Class",
            "start": {"dateTime": "2026-08-25T14:00:00Z"},
            "end": {"dateTime": "2026-08-25T15:00:00Z"},
        }
        self.assertEqual(
            calendar_bridge.signature(event),
            ("Class", "2026-08-25T14:00:00+00:00", "2026-08-25T15:00:00+00:00"),
        )

    def test_google_timezone_and_omitted_defaults_compare_equal(self):
        desired = {
            "summary": "Class",
            "description": "Agenda",
            "colorId": "6",
            "start": {"dateTime": "2026-08-25T14:00:00+00:00"},
            "end": {"dateTime": "2026-08-25T15:00:00+00:00"},
            "transparency": "opaque",
            "visibility": "default",
            "reminders": {"useDefault": False, "overrides": []},
            "extendedProperties": {"private": {"bridgeName": "calendar-bridge"}},
        }
        stored = {
            "summary": "Class",
            "description": "Agenda",
            "colorId": "6",
            "start": {"dateTime": "2026-08-25T10:00:00-04:00", "timeZone": "America/New_York"},
            "end": {"dateTime": "2026-08-25T11:00:00-04:00", "timeZone": "America/New_York"},
            "reminders": {"useDefault": False},
            "extendedProperties": {"private": {"bridgeName": "calendar-bridge"}},
        }
        self.assertEqual(
            calendar_bridge.relevant_google_fields(desired),
            calendar_bridge.relevant_google_fields(stored),
        )


if __name__ == "__main__":
    unittest.main()
