"""Check local Markdown/image links and parse the repository's SVG assets."""
from pathlib import Path
import re
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def check():
    missing = []
    for file in ROOT.rglob("*.md"):
        if any(part in {".git", ".venv"} for part in file.relative_to(ROOT).parts):
            continue
        for groups in re.findall(r'\]\(([^)]+)\)|(?:src|href)="([^"]+)"', file.read_text(encoding="utf-8")):
            link = next(value for value in groups if value).split("#")[0]
            if link and not re.match(r"https?://|mailto:", link) and not (file.parent / link).exists():
                missing.append((str(file.relative_to(ROOT)), link))
    for file in (ROOT / "docs" / "assets").glob("*.svg"):
        ElementTree.parse(file)
    if missing:
        for file, link in missing:
            print(f"Broken local link: {file} → {link}")
        return 1
    print("PASS: local documentation links and SVG XML are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(check())
