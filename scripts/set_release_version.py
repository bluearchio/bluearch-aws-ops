#!/usr/bin/env python3
"""Set the committed BlueArch AWS Ops release version."""

from __future__ import annotations

import re
import sys
from pathlib import Path


TAG_PATTERN = re.compile(r"^v(\d+\.\d+\.\d+)$")
ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"Expected exactly one version field in {path}")
    path.write_text(updated, encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not (match := TAG_PATTERN.fullmatch(argv[1])):
        print("usage: set_release_version.py vMAJOR.MINOR.PATCH", file=sys.stderr)
        return 2

    version = match.group(1)
    replace_once(
        ROOT / "pyproject.toml",
        r'^version = "[^"]+"$',
        f'version = "{version}"',
    )
    replace_once(
        ROOT / "src" / "api" / "aws" / "misc" / "version_controller.py",
        r'^(CURRENT_VERSION = os\.environ\.get\("BLUEARCH_AWS_OPS_VERSION", ")[^"]+("\))$',
        rf"\g<1>{version}\g<2>",
    )
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
