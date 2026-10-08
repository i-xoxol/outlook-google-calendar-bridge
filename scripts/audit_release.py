"""Fail the public release if tracked files contain runtime state or likely secrets."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
patterns = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{15,}"),
    "API credential": re.compile(r"\b(?:sk-proj-|sk_live_|ghp_|github_pat_)[A-Za-z0-9_-]{20,}"),
    "personal Windows path": re.compile(r"[A-Z]:[\\/]+Users[\\/]+[A-Za-z0-9_-]+[\\/]"),
    "deployment home path": re.compile(r"/home/[A-Za-z0-9_-]+/"),
}


def audit():
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    if not any(names):
        raise RuntimeError("Stage the release files before auditing")
    failures = []
    for name in filter(None, names):
        path = ROOT / name
        lowered = name.lower()
        if (lowered.startswith(("private/", ".venv/")) or path.name in {"config.toml", ".env"}
                or path.suffix.lower() in {".pem", ".key", ".db", ".log", ".sqlite"}
                or re.search(r"(?:token|cache|client).*\.json$", lowered)):
            failures.append((name, "runtime/credential file"))
        if not path.exists() or path.is_symlink():
            failures.append((name, "missing file or symlink")); continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append((name, "unreviewed binary")); continue
        for label, pattern in patterns.items():
            if pattern.search(text):
                failures.append((name, label))
    if failures:
        for name, label in failures:
            print(f"FAIL {name}: {label}")
        return 1
    print(f"PASS: {len(list(filter(None, names)))} tracked text/SVG files; no runtime credentials or deployment paths detected.")
    return 0


if __name__ == "__main__":
    sys.exit(audit())
