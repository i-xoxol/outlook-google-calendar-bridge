# Security and privacy

[← Project overview](../README.md) · [Configuration](configuration.md)

## Data flow and permissions

Microsoft access is delegated `User.Read` plus `Calendars.Read`. The application
does not write to Outlook, request mailbox content, or administer a tenant. Google
uses `calendar.events` and directs event writes to the configured calendar.
Each operator supplies their own registered applications and authorizations.

Titles, times, availability, reminders, and ownership metadata move from Microsoft
to Google. Descriptions, locations, and meeting links are omitted unless
`copy_details` is enabled. Details can contain personal information and meeting
passcodes. Private Google visibility helps control sharing, but calendar editors
may still see event details. Check both destination sharing and organizational policy.

## Private state

OAuth credentials are plaintext local files protected by owner-only `0600` modes,
private directories, atomic replacement, and file locks. They are not encrypted
by this program. Use an encrypted disk and private backups when appropriate.
Symlinks, unexpected ownership, shared credential permissions, and oversized caches
are rejected. Keep every credential/configuration file outside source control.

Microsoft recovery checks account, username, tenant, authority, application, and
refresh-token family before a replacement is verified and saved. It never saves
the fallback file. No password collection, MFA bypass, or extension of provider
authorization policy is implemented. A newer valid session must actually exist.

Google browser sign-in uses random state, S256 PKCE, a loopback-only callback,
and no callback access logging. The callback server closes after the attempt.
Callback codes and bearer tokens are not printed.

## Writes and ownership

Preview is the default. Calendar writes require `--apply`, and pruning requires
`--allow-deletes`. Writes are capped. The CLI does not accept an externally supplied
execution plan. Only metadata-tagged mirrors are updated/pruned by its planner;
unmanaged matching events are skipped and personal events remain unmanaged.

Ownership tags are not cryptographic signatures. Anyone who can edit destination
metadata can interfere with them. This is a single-owner service; use a dedicated
destination without untrusted editors and a stable namespace.

## Logs and public releases

Normal sync output reports counts. `--show-details` intentionally reveals names
in your own terminal. Interactive Microsoft login/verification displays identity
information so you can confirm the account. Redact output before sharing it.

This release contains only source, documentation, and fictional fixtures. The
release audit checks tracked files for runtime state, likely tokens/private keys,
and deployment-specific paths. Automated scanning is a supplement to reviewing
the entire public file set and fresh Git history.

## Threat model and limits

Trusted: the host owner, configured OAuth applications, Microsoft/Google, and
local source code. Not provided: multi-user isolation, encrypted credential
storage, a hosted tenant boundary, an external approval service, or transactional
rollback across providers. A process with the same OS identity can access private
state; file modes do not sandbox that identity. Revoked grants require reauthorization.
