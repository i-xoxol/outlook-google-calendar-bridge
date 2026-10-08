# Deployment

[← Project overview](../README.md) · [First-run setup](getting-started.md)

The example deployment is a Linux **user** service. Finish a preview and controlled
apply before enabling the timer. No public listener, incoming webhook, or tunnel is
needed for steady-state calendar synchronization.

## Install in your home directory

```bash
mkdir -p "$HOME/apps"
git clone https://github.com/i-xoxol/outlook-google-calendar-bridge.git "$HOME/apps/outlook-google-calendar-bridge"
cd "$HOME/apps/outlook-google-calendar-bridge"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp config.example.toml config.toml
mkdir -m 700 private
```

Configure your own providers using the setup guide. The examples use `%h`, which
systemd expands to your home directory. Edit both unit paths if you choose a
different installation location.

## A headless server

Google's callback must reach the helper on the machine running the browser.
Authenticate on your Linux/macOS workstation using the same Desktop client, then
transfer only the required private OAuth files over your own secure channel to the
server. Restrict directories to `0700` and files to `0600`. Do not put credentials
in Git, command arguments, screenshots, or an issue. Microsoft device-code login
can run on the server while you complete sign-in in a separate browser.

Verify the intended accounts and destination on the server with a preview. Its
configuration should point to the server's own local credential paths.

## Enable scheduling

```bash
mkdir -p "$HOME/.config/systemd/user"
cp deploy/calendar-bridge.service deploy/calendar-bridge.timer "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user start calendar-bridge.service
systemctl --user enable --now calendar-bridge.timer
systemctl --user list-timers calendar-bridge.timer
```

The service exits between runs; `inactive (dead)` after a successful one-shot is
normal. The timer should be active and have a next invocation. Its sample command
enables create/update but does not prune. Add `--allow-deletes` only if you intend
that behavior and have checked its preview.

To run after logout/reboot, your machine must permit user lingering. An administrator
can enable lingering for your user according to local policy. This is a host setup
step; the repository does not change it automatically.

```bash
systemctl --user status calendar-bridge.timer
journalctl --user -u calendar-bridge.service -n 40 --no-pager
systemctl --user disable --now calendar-bridge.timer
```

The unit preserves `UMask=0077`, `NoNewPrivileges`, and systemd filesystem controls.
Check your distribution's support for user namespaces. If filesystem protection
blocks private state writes, grant a narrow `ReadWritePaths` exception for the
configured state directory; do not disable the whole protection layer.

## Updates and backups

Stop the timer, wait for any current run, retain a private backup of your state,
pull the reviewed code, install dependencies, run offline tests, and preview again.
Reload changed unit files before restarting the timer. Keep a previous source
revision for rollback. Credential backups remain sensitive and stay outside Git.

macOS users can run the same CLI manually or configure their own launchd job;
this release provides and tests Linux scheduling examples only.
