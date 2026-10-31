"""boto3 clients for the knowledge base, built from the project settings (profile and region)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import boto3

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
    session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
    return AwsClients(
        cloudformation=session.client("cloudformation"),
        s3=session.client("s3"),
        bedrock_agent=session.client("bedrock-agent"),
        bedrock_agent_runtime=session.client("bedrock-agent-runtime"),
    )
