# Testing

[← Project overview](../README.md) · [First run](getting-started.md)

## Offline checks

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -v
python scripts/demo.py
python scripts/audit_release.py
```

The suite uses fake provider responses, temporary files, and a local loopback
HTTP callback. It does not authenticate against providers or write real calendars.
The audit uses Git's tracked file list; stage release files before running it.

Coverage includes event semantics, idempotent planning, unmanaged/foreign events,
write and pruning gates, all-day time-zone reconstruction, OAuth state/PKCE,
callback rejection, permission checks, atomic cache updates, same-account recovery,
provider identity changes, and failed-verification rollback.

The fictional demo plans one new copy, one update, and one obsolete managed copy.
It simulates applying that plan in memory, proves the second plan is empty, and
checks that a personal event is unchanged. The illustrated preview represents this
demo; it is not a screen from a real account.

GitHub Actions runs installation, tests, demo, release audit, and CLI help on
Python 3.11, 3.12, 3.13, and 3.14 under Linux.

## Manual acceptance with your own accounts

Use a dedicated test destination. Verify:

1. Preview causes no calendar writes.
2. A small controlled apply creates the correct timed copy and private visibility.
3. A one-day and a multi-day event retain dates in your source time zone.
4. Moving the source event updates its existing copy.
5. Repeating reconciliation settles to zero pending changes.
6. A personal Google event is not changed or removed.
7. Cancellation pruning is previewed separately and affects only a managed copy.
8. The timer has a future invocation; the previous one-shot reports success.

Do not expire or revoke production credentials just to test recovery. Unit tests
simulate expiry, both-session failure, and identity mismatches. Use isolated test
state for any live recovery exercise. Never place live credentials in test fixtures.
