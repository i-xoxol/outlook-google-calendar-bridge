# Design notes

[← Project overview](../README.md)

## Decisions

- **One-way sync:** source authority stays clear and avoids resolving edits made
  independently in two calendars.
- **Complete snapshots:** simple, inspectable reconciliation; an incomplete fetch
  fails before writes. It costs more reads than a delta/webhook design.
- **Metadata ownership:** enables updates/pruning without treating every personal
  event as bridge state. It is a convention within a trusted owner-controlled calendar.
- **Preview and bounded writes:** small first-run changes are easy to validate.
- **Optional recovery:** a genuinely newer same-account authorization can recover a
  stale cache, while tenant policy and MFA remain authoritative.
- **Private, minimal copies:** details are an opt-in because useful meeting bodies
  can also contain sensitive material.
- **User-level scheduling:** keeps deployment small and avoids an always-listening server.

## Practical limits

Snapshots and remote writes are not one transaction. Network ambiguity or API
eventual consistency can cause intermediate states; retrying from a complete
snapshot usually converges. There is no exactly-once or automatic rollback claim.

Recurring occurrences are separate Google events. The deduplication heuristic can
skip genuinely distinct appointments with identical titles and times. Namespace
and destination changes need a migration rather than silently taking over copies.

## Possible extensions

Useful next steps include delta synchronization with durable checkpoints,
conditional/etag updates, explicit migration tooling, health notifications without
event content, and additional source calendars. A multi-user hosted version would
need a different authorization, encryption, isolation, and operations model.

The public edition is a clean, generalized release. Its tests and fictional demo
are reproducible without access to the author's private service.
