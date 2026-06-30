"""Local version metadata for the public BlueArch AWS Ops CLI."""

from __future__ import annotations

import os


# Build and release automation can override this at package time.
CURRENT_VERSION = os.environ.get("BLUEARCH_AWS_OPS_VERSION", "LOCAL")


def get_updates() -> list[dict]:
    """Return public release metadata.

    Public builds do not call BlueArch-hosted release APIs. Homebrew users can
    check for updates with `brew outdated bluearchio/tap/bluearch-aws-ops`.
    """
    return []
