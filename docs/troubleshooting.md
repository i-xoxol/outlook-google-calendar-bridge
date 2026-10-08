# Troubleshooting

[← Project overview](../README.md) · [Setup](getting-started.md) · [Deployment](deployment.md)

| Symptom | What to check |
|---|---|
| `sign-in-required` | Renew Microsoft authorization with `python ms_auth.py login --config config.toml`; rerun the preview. |
| Microsoft consent/device flow denied | Confirm your own app ID, supported account type, delegated scopes, and public-client setting. Organizational policy may require IT approval. |
| Automatic fallback rejected | Confirm the exact same account, tenant, authority, application, and token family. Office/browser caches for a different app are not interchangeable. |
| Google `invalid_grant` | Repeat `python google_auth.py login --config config.toml`; check consent-screen publishing status, revoked access, and provider token policy. |
| Google callback never arrives | The browser and helper must be on the same machine. Use workstation authentication before transferring private files to a headless server. |
| Credential/configuration error | Check file existence, TOML types, private file mode `0600`, owner, directory permissions, and absence of symlinks. |
| A write cap leaves `deferred` actions | Run another preview/cycle, or raise the cap deliberately. |
| Obsolete copies remain | Pruning is disabled by default. Preview with `--allow-deletes` before applying it. |
| A matching event is skipped | A same-title/same-time unmanaged event exists. It is deliberately not adopted or edited. |
| All-day event has unsupported zone | A legacy custom Outlook zone is present. Use a standard supported zone in the source event and preview again. |
| One-shot service says `inactive (dead)` | Normal after success. Check `Result=success`, timer activity, and its next run. |
| HTTP 403/404 from Google | Check the intended Google account, Calendar ID, Calendar API enablement, scopes, and edit access. |
| New namespace/destination creates duplicates | Stop the timer and plan a migration; existing copies belong to the previous namespace/destination. |

```bash
systemctl --user show calendar-bridge.service -p Result -p ExecMainStatus
systemctl --user list-timers calendar-bridge.timer
journalctl --user -u calendar-bridge.service -n 40 --no-pager
```

Authorization recovery cannot bypass a required fresh sign-in, MFA, or revoked
consent. The next timer invocation retries ordinary transient failures. Stop
scheduling while investigating a persistent configuration error.

When reporting a bug, include the release, Python/OS versions, operation mode,
counts, and a minimal fictional example. Omit account IDs, real names/descriptions,
meeting URLs, provider codes, token caches, and credential files.
