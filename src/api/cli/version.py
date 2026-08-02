from typer import Exit

from aws.misc.version_controller import CURRENT_VERSION


PUBLIC_OPS_EXECUTABLE = "bluearch-aws-ops"


def version_callback(value: bool):
    if value:
        print(f"{PUBLIC_OPS_EXECUTABLE} {CURRENT_VERSION}")
        raise Exit()
