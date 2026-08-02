"""No-op startup version check for public builds.

The public CLI does not call BlueArch-hosted release metadata services. Users
installed through Homebrew should trust the exact Core formula and then the
exact Ops formula before using `brew update` and
`brew outdated bluearchio/tap/bluearch-aws-ops`.
"""


def check_for_update_notice() -> None:
    return None
