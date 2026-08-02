"""Local version metadata for the public BlueArch AWS Ops CLI."""

from __future__ import annotations

import os


# The committed bare version is the release source of truth. Development and
# packaging tools may still override it explicitly for local diagnostics.
CURRENT_VERSION = os.environ.get("BLUEARCH_AWS_OPS_VERSION", "0.13.4")


def get_updates() -> list[dict]:
    """Return public release metadata.

    Public builds do not call BlueArch-hosted release APIs. Homebrew users can
    trust the exact Core formula and then the exact Ops formula before checking:
    `brew trust --formula bluearchio/tap/bluearch-aws-core`,
    `brew trust --formula bluearchio/tap/bluearch-aws-ops`, then
    `brew outdated bluearchio/tap/bluearch-aws-ops`.
    """
    return []
