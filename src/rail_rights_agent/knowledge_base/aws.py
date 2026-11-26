"""boto3 clients for the knowledge base, built from the shared session (profile and region)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rail_rights_agent.aws import session
from rail_rights_agent.settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_bedrock_agent import AgentsforBedrockClient
    from mypy_boto3_bedrock_agent_runtime import AgentsforBedrockRuntimeClient
    from mypy_boto3_cloudformation import CloudFormationClient
    from mypy_boto3_s3 import S3Client


@dataclass(frozen=True)
class AwsClients:
    cloudformation: "CloudFormationClient"
    s3: "S3Client"
    bedrock_agent: "AgentsforBedrockClient"
    bedrock_agent_runtime: "AgentsforBedrockRuntimeClient"


def clients(settings: Settings) -> AwsClients:
    aws = session(settings)
    return AwsClients(
        cloudformation=aws.client("cloudformation"),
        s3=aws.client("s3"),
        bedrock_agent=aws.client("bedrock-agent"),
        bedrock_agent_runtime=aws.client("bedrock-agent-runtime"),
    )
