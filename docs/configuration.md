# Configuration

[← Project overview](../README.md) · [Getting started](getting-started.md)

Copy `config.example.toml` to the ignored `config.toml`. Relative credential paths
are interpreted relative to the configuration file, not the working directory.
The program does not read a `.env` file. Configuration is per process and per owner.

| Setting | Default | Purpose |
|---|---|---|
| `microsoft.client_id` | blank, required | Your own Entra public-client application UUID |
| `microsoft.tenant` | `organizations` | Tenant UUID/domain or supported account audience |
| `microsoft.cache` | `private/msal_cache.json` | The bridge's owner-only Microsoft cache |
| `microsoft.fallback_cache` | blank | Optional same-account/application cache; never modified |
| `google.client` | `private/google-client.json` | Downloaded Desktop app credentials |
| `google.token` | `private/google-token.json` | Owner-only Google OAuth state |
| `google.calendar_id` | `primary` | Destination calendar you control |
| `sync.days_past` | `30` | Past lookback in days |
| `sync.days_future` | `365` | Future horizon in days |
| `sync.bridge_name` | `calendar-bridge` | Stable ownership namespace; unique per instance |
| `sync.title_suffix` | ` [Work]` | Label appended to mirrored titles |
| `sync.color_id` | `6` | Google event color ID, from 1 through 11 |
| `sync.copy_details` | `false` | Opt in to descriptions, locations, and meeting links |
| `sync.private_events` | `true` | Mark all mirrored copies private |
| `sync.max_writes` | `25` | Maximum calendar writes per run |

`--apply` and `--allow-deletes` are deliberately CLI switches, not hidden config
defaults. The checked-in timer uses `--apply` but omits pruning.

## CLI overrides

```bash
python calendar_bridge.py --config config.toml --days-past 1 --days-future 14 --max-writes 10
python calendar_bridge.py --help
```

`--ms-cache`, `--ms-fallback-cache`, and `--google-token` override corresponding
paths. `--dry-run` explicitly selects preview; preview is also the default.
`--show-details` includes event names in local output. Authentication refresh can
still update credential files during preview.

## Optional recovery cache

The fallback must be a private, regular file owned by the running user, with the
same home account, username, tenant, authority, client ID, and refresh-token family.
An unrelated Office/browser application's cache will not qualify.

One way to create a newer authorization for the same configured application is:

```bash
python ms_auth.py login --config config.toml --cache private/secondary-msal-cache.json
```

Then set `microsoft.fallback_cache = "private/secondary-msal-cache.json"`.
Recovery is useful when another legitimate process maintains that newer session.
It does not manufacture a fresh sign-in or bypass MFA/conditional-access policy.

## Changes that need care

Keep `bridge_name`, source identity, and destination calendar stable. Changing
them can leave old copies behind or create a separate set. Stop the timer, preview
the new configuration, and plan cleanup of the old managed copies separately.
Turning `copy_details` off clears mirrored descriptions/locations on the next
update. Private event visibility does not hide details from every calendar editor.
