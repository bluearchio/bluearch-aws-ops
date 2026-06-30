"""No-op startup version check for public builds.

The public CLI does not call BlueArch-hosted release metadata services. Users
installed through Homebrew can use `brew update` and `brew outdated`.
"""


def check_for_update_notice() -> None:
    return None
