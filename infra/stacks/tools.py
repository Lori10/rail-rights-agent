"""Tools stack: trips and claims tables, one Lambda function per tool (design D6).

The functions are plain directory assets of ``src/``: the domain code is pure Python and the Lambda
runtime ships boto3, so there is no bundling step and no Docker.
"""

from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from rail_rights_agent.tools.deployment import (
    ENV_CLAIMS_TABLE,
    ENV_TRIPS_TABLE,
    HANDLER_MODULE,
    OUTPUT_CALCULATE_COMPENSATION_FUNCTION_ARN,
    OUTPUT_CLAIMS_TABLE,
    OUTPUT_GET_TRAIN_DELAY_FUNCTION_ARN,
    OUTPUT_SUBMIT_CLAIM_FUNCTION_ARN,
    OUTPUT_TRIPS_TABLE,
)

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
# Only the tools package and its imports ship; the knowledge-base client is not needed in Lambda.
ASSET_EXCLUDE = [
    "**/__pycache__",
    "**/*.pyc",
    "**/*.egg-info",
    "rail_rights_agent/knowledge_base",
    "rail_rights_agent/knowledge_base/**",
]
STRING = dynamodb.AttributeType.STRING


class ToolsStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        trips = dynamodb.Table(
            self,
            "Trips",
            partition_key=dynamodb.Attribute(name="pk", type=STRING),
            sort_key=dynamodb.Attribute(name="sk", type=STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        claims = dynamodb.Table(
            self,
            "Claims",
            partition_key=dynamodb.Attribute(name="claim_id", type=STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        code = lambda_.Code.from_asset(str(SRC_DIR), exclude=ASSET_EXCLUDE)

        def function(name: str, description: str, env: dict[str, str]) -> lambda_.Function:
            pascal = "".join(part.capitalize() for part in name.split("_"))
            log_group = logs.LogGroup(
                self,
                f"{pascal}Logs",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            )
            return lambda_.Function(
                self,
                pascal,
                description=description,
                runtime=lambda_.Runtime.PYTHON_3_12,
                architecture=lambda_.Architecture.ARM_64,
                handler=f"{HANDLER_MODULE}.{name}",
                code=code,
                memory_size=256,
                timeout=cdk.Duration.seconds(10),
                environment=env or None,
                log_group=log_group,
            )

        delay_fn = function(
            "get_train_delay",
            "Rail Rights Agent tool: look up a train's delay record",
            {ENV_TRIPS_TABLE: trips.table_name},
        )
        compensation_fn = function(
            "calculate_compensation",
            "Rail Rights Agent tool: deterministic compensation under Art. 19 and DB conditions",
            {},
        )
        submit_fn = function(
            "submit_claim",
            "Rail Rights Agent tool: record a confirmed compensation claim once",
            {ENV_CLAIMS_TABLE: claims.table_name},
        )

        trips.grant_read_data(delay_fn)
        claims.grant(submit_fn, "dynamodb:GetItem", "dynamodb:PutItem")

        cdk.CfnOutput(self, OUTPUT_TRIPS_TABLE, value=trips.table_name)
        cdk.CfnOutput(self, OUTPUT_CLAIMS_TABLE, value=claims.table_name)
        cdk.CfnOutput(self, OUTPUT_GET_TRAIN_DELAY_FUNCTION_ARN, value=delay_fn.function_arn)
        cdk.CfnOutput(
            self, OUTPUT_CALCULATE_COMPENSATION_FUNCTION_ARN, value=compensation_fn.function_arn
        )
        cdk.CfnOutput(self, OUTPUT_SUBMIT_CLAIM_FUNCTION_ARN, value=submit_fn.function_arn)
