# Contributing

Focused fixes, tests, and documentation improvements are welcome. Open an issue
with a fictional reproducer before proposing a large behavior change.

1. Create a branch for your change.
2. Install `requirements-dev.txt` in a virtual environment.
3. Run `python -m unittest discover -v` and `python scripts/demo.py`.
4. Stage only source/docs and run `python scripts/audit_release.py`.
5. Explain the trigger, resulting behavior, and validation in your pull request.

Keep provider scopes minimal, writes explicit, state private, and examples
fictional. Tests must not require account credentials or real calendars. Changes
to identity matching, ownership, deletion, or privacy defaults need tests proving
both the intended action and rejection of the unintended one.
