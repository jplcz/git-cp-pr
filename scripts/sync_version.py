#!/usr/bin/env python3
"""Synchronize the application version into the GitHub Pages HTML."""

import argparse
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
INDEX_FILE = PROJECT_DIR / "docs" / "index.html"
VERSION_PATTERN = re.compile(r"(Command-line and GUI utility · version )([0-9]+(?:\.[0-9]+)+)")

sys.path.insert(0, str(PROJECT_DIR))
from git_cp_pr import __version__  # noqa: E402


def synchronize(check: bool) -> bool:
    content = INDEX_FILE.read_text(encoding="utf-8")
    updated, replacements = VERSION_PATTERN.subn(rf"\g<1>{__version__}", content)
    if replacements != 1:
        raise RuntimeError(f"Expected one version marker in {INDEX_FILE}, found {replacements}")
    if check:
        return updated == content
    if updated != content:
        INDEX_FILE.write_text(updated, encoding="utf-8")
        print(f"Updated {INDEX_FILE} to {__version__}")
    else:
        print(f"{INDEX_FILE} already contains {__version__}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize the app version into docs/index.html.")
    parser.add_argument("--check", action="store_true", help="Fail if docs/index.html is out of sync")
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
