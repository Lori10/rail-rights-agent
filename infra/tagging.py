"""Project tags that every taggable resource carries (cost tracking and ownership)."""

import aws_cdk as cdk
from constructs import IConstruct

PROJECT_TAGS = {
    "project": "rail-rights-agent",
    "environment": "dev",
    "managed-by": "cdk",
    "repo": "Lori10/rail-rights-agent",
}


def apply_project_tags(scope: IConstruct) -> None:
    for key, value in PROJECT_TAGS.items():
        cdk.Tags.of(scope).add(key, value)
