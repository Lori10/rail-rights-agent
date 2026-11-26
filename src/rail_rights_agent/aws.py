"""AWS helpers shared by the command-line tools: a session from settings and stack outputs.

Lambda handlers do not use this module: in Lambda there is no profile, so they build plain
``boto3.client(...)`` instances from the execution role (design D7).
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

from rail_rights_agent.settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_cloudformation import CloudFormationClient


class StackError(Exception):
    """A deployed stack could not be read; ``code`` is the service error code or our own."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def session(settings: Settings) -> boto3.Session:
    """A session on the configured profile and the locked region."""
    return boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)


def stack_outputs(
    cfn: "CloudFormationClient", stack_name: str, keys: Sequence[str]
) -> dict[str, str]:
    """Read the named outputs of a deployed stack; every key must be present."""
    try:
        (stack,) = cfn.describe_stacks(StackName=stack_name)["Stacks"]
    except ClientError as err:
        error = err.response.get("Error", {})
        if "does not exist" in error.get("Message", ""):
            raise StackError(
                "StackNotFound",
                f"stack {stack_name} does not exist; deploy first with scripts/deploy.sh",
            ) from err
        raise StackError(error.get("Code", "Unknown"), error.get("Message", str(err))) from err
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
    missing = [k for k in keys if k not in outputs]
    if missing:
        raise StackError(
            "StackOutputMissing", f"stack {stack_name} has no output {', '.join(missing)}"
        )
    return {k: outputs[k] for k in keys}
