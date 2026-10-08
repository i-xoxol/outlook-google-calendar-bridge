# Getting started

[← Project overview](../README.md) · [Configuration](configuration.md) · [Deployment](deployment.md)

## Before you start

Use Python 3.11+ on Linux or macOS, Git, a browser, a Microsoft calendar you may
read, and a Google calendar you may edit. Windows users can run the CLI in WSL2.
Create your own OAuth applications. Organizational policy may require IT approval
for device-code sign-in, consent, or copying calendar data to another provider.
In WSL2, keep the clone and private state in the Linux home filesystem so Unix
ownership and permission checks work correctly, rather than a mounted Windows drive.

Start with a dedicated Google destination and a small test event. A preview
contacts both providers and may renew private credential files, but does not write
calendar events. The fictional demo needs no accounts or network access.

## 1. Install and try the demo

```bash
git clone https://github.com/i-xoxol/outlook-google-calendar-bridge.git
cd outlook-google-calendar-bridge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -v
python scripts/demo.py
cp config.example.toml config.toml
mkdir -m 700 private
```

Keep `config.toml` and everything in `private/` out of Git.

## 2. Register Microsoft authentication

In Microsoft Entra, register an application for your intended account type.
For one organization, use its tenant and account type. Enable **Allow public
client flows** for device-code authentication. Add Microsoft Graph **delegated**
permissions `User.Read` and `Calendars.Read`; no application secret is needed.
Obtain consent through your organization's normal process.

Set `microsoft.client_id` to the application's client ID. Set `microsoft.tenant`
to your tenant ID or domain; `organizations` supports work/school sign-in. For
personal Outlook accounts, use `common` or `consumers` with an app registration
that supports that account type. This release targets the global Microsoft cloud.

```bash
python ms_auth.py login --config config.toml
python ms_auth.py verify --config config.toml
```

Follow the device-code instructions yourself, complete any MFA, and verify that
the reported account is yours. No Microsoft password is stored.

Official references: [desktop/public-client configuration](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration),
[device-code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code),
[Graph calendarView](https://learn.microsoft.com/en-us/graph/api/user-list-calendarview?view=graph-rest-1.0).

## 3. Register Google authentication

Create a Google Cloud project and enable **Google Calendar API**. Configure the
OAuth consent screen for your account and its intended audience. During testing,
add your account as a test user. Create an OAuth client of type **Desktop app**.
Download its JSON credentials into `private/google-client.json` and restrict it:

```bash
chmod 600 private/google-client.json
python google_auth.py login --config config.toml
```

The helper opens a browser, listens briefly on `127.0.0.1` at a random port, and
uses state and PKCE. The browser and helper must run on the same machine. No
callback code needs to be pasted into a command. If browser launching is unavailable,
use `--no-browser` and open the displayed authorization URL locally.

Sign in to your intended Google account. The requested scope is
`https://www.googleapis.com/auth/calendar.events`. It permits event editing;
the implementation directs writes only to your configured destination.

For a separate destination, create a calendar in Google Calendar, obtain its
Calendar ID from its settings, and set `google.calendar_id` in `config.toml`.
Otherwise `primary` uses the signed-in account's primary calendar.

OAuth apps in Google's **Testing** publishing status can have short-lived refresh
authorization for this scope. Review consent status and provider policy before
expecting unattended operation.

Official references: [Desktop OAuth and loopback callbacks](https://developers.google.com/identity/protocols/oauth2/native-app),
[Calendar scopes](https://developers.google.com/identity/protocols/oauth2/scopes#calendar),
[refresh-token expiry](https://developers.google.com/identity/protocols/oauth2#expiration).

## 4. Preview a controlled example

Create a harmless appointment in Outlook. Then:

```bash
python calendar_bridge.py --config config.toml --days-past 1 --days-future 7
```

Review the action counts. To inspect names in your own terminal, add
`--show-details`; do not upload that output to a public issue. Check destination
sharing and your organization’s data-transfer policy before writing.

## 5. Apply, then prove it settled

```bash
python calendar_bridge.py --config config.toml --apply --days-past 1 --days-future 7 --max-writes 5
python calendar_bridge.py --config config.toml --days-past 1 --days-future 7
```

Check the created copy in Google: title, time, all-day dates, visibility, reminder,
and busy/free state. Verify that a personal Google event remains untouched.
Move the Outlook test appointment and repeat. The second preview should settle
to zero changes. Deferred actions require another run if the write cap was reached.

Pruning is a separate opt-in: preview with `--allow-deletes`, then add `--apply`
only after reviewing its effect. It removes obsolete **managed copies**, never
the Outlook source. [Enable the Linux timer after these checks →](deployment.md)
