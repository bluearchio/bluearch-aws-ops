#!/usr/bin/env python3
"""Render bundled template metadata deterministically for release builds."""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r'^version = "(\d+\.\d+\.\d+)"$', re.MULTILINE)


def committed_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(text)
    if not match:
        raise RuntimeError("pyproject.toml has no bare semantic project version")
    return match.group(1)


def source_epoch() -> int:
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured:
        return int(configured)
    result = subprocess.run(
        ["git", "show", "-s", "--format=%ct", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip())


def main() -> int:
    version = committed_version()
    release_tag = os.environ.get("RELEASE_TAG")
    if release_tag and release_tag != f"v{version}":
        raise RuntimeError(f"release tag {release_tag} does not match committed version {version}")
    deployment_date = dt.datetime.fromtimestamp(source_epoch(), tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    replacements = {
        "__TEMPLATE_VERSION__": version,
        "__CLI_VERSION__": version,
        "__DEPLOYMENT_DATE__": deployment_date,
    }
    changed = 0
    for path in sorted((ROOT / "src" / "api" / "templates").glob("*.yaml")):
        original = path.read_text(encoding="utf-8")
        rendered = original
        for placeholder, value in replacements.items():
            rendered = rendered.replace(placeholder, value)
        if rendered != original:
            path.write_text(rendered, encoding="utf-8")
            changed += 1
    if changed == 0:
        raise RuntimeError("no release template placeholders were rendered")
    print(f"rendered {changed} templates for {version} at {deployment_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
