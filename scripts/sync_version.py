#!/usr/bin/env python3
"""Synchronize application assets into the GitHub Pages site."""

import argparse
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
INDEX_FILE = PROJECT_DIR / "docs" / "index.html"
SOURCE_ICON = PROJECT_DIR / "icon.svg"
PUBLISHED_ICON = PROJECT_DIR / "docs" / "icon.svg"
VERSION_PATTERN = re.compile(r"(Command-line and GUI utility · version )([0-9]+(?:\.[0-9]+)+)")

sys.path.insert(0, str(PROJECT_DIR))
from git_cp_pr import __version__  # noqa: E402


def synchronize(check: bool) -> bool:
    content = INDEX_FILE.read_text(encoding="utf-8")
    updated, replacements = VERSION_PATTERN.subn(rf"\g<1>{__version__}", content)
    if replacements != 1:
        raise RuntimeError(f"Expected one version marker in {INDEX_FILE}, found {replacements}")
    if check:
        return updated == content and SOURCE_ICON.read_bytes() == PUBLISHED_ICON.read_bytes()
    if updated != content:
        INDEX_FILE.write_text(updated, encoding="utf-8")
        print(f"Updated {INDEX_FILE} to {__version__}")
    else:
        print(f"{INDEX_FILE} already contains {__version__}")
    if SOURCE_ICON.read_bytes() != PUBLISHED_ICON.read_bytes():
        PUBLISHED_ICON.write_bytes(SOURCE_ICON.read_bytes())
        print(f"Updated {PUBLISHED_ICON}")
    else:
        print(f"{PUBLISHED_ICON} already matches {SOURCE_ICON}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize application assets into the GitHub Pages site.")
    parser.add_argument("--check", action="store_true", help="Fail if the site version or icon is out of sync")
    args = parser.parse_args()
    try:
        synchronized = synchronize(args.check)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    if args.check and not synchronized:
        print(f"{INDEX_FILE} is out of sync with version {__version__}", file=sys.stderr)
        return 1
    if args.check:
        print(f"{INDEX_FILE} matches version {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
