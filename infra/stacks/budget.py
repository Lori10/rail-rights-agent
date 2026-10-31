"""Opt-in monthly cost budget with email alerts (free-plan credit protection).

CloudFormation in eu-north-1 has no ``AWS::Budgets::Budget`` type, so the budget is created and
deleted through the Budgets API by a CDK custom resource (design D7).
"""

import hashlib
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import custom_resources as cr
from constructs import Construct

from infra.tagging import PROJECT_TAGS

# (notification type, percentage of the monthly limit)
_ALERTS = [("ACTUAL", 50), ("ACTUAL", 80), ("FORECASTED", 100)]


def budget_name(email: str, limit_usd: int) -> str:
    """A changed email or limit gives a new name, so the custom resource replaces the budget."""
    digest = hashlib.sha256(f"{email}:{limit_usd}".encode()).hexdigest()[:8]
    return f"rail-rights-agent-monthly-{digest}"


class BudgetStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        email: str,
        limit_usd: int,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        name = budget_name(email, limit_usd)
        create = cr.AwsSdkCall(
            service="Budgets",
            action="CreateBudget",
            parameters={
                "AccountId": self.account,
                "Budget": {
                    "BudgetName": name,
                    "BudgetType": "COST",
                    "TimeUnit": "MONTHLY",
                    "BudgetLimit": {"Amount": str(limit_usd), "Unit": "USD"},
                },
                "NotificationsWithSubscribers": [
                    {
                        "Notification": {
                            "NotificationType": kind,
                            "ComparisonOperator": "GREATER_THAN",
                            "Threshold": threshold,
                            "ThresholdType": "PERCENTAGE",
                        },
                        "Subscribers": [{"SubscriptionType": "EMAIL", "Address": email}],
                    }
                    for kind, threshold in _ALERTS
                ],
                "ResourceTags": [{"Key": k, "Value": v} for k, v in PROJECT_TAGS.items()],
            },
            physical_resource_id=cr.PhysicalResourceId.of(name),
        )
        delete = cr.AwsSdkCall(
            service="Budgets",
            action="DeleteBudget",
            parameters={"AccountId": self.account, "BudgetName": name},
        )
        budget_arn = self.format_arn(
            service="budgets",
            region="",
            resource="budget",
            resource_name=name,
            arn_format=cdk.ArnFormat.SLASH_RESOURCE_NAME,
        )
        log_group = logs.LogGroup(
            self,
            "BudgetHandlerLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        cr.AwsCustomResource(
            self,
            "MonthlyCost",
            on_create=create,
            on_delete=delete,
            # CreateBudget/DeleteBudget are not IAM actions; the Budgets API maps them to these.
            policy=cr.AwsCustomResourcePolicy.from_statements(
                [
                    iam.PolicyStatement(
                        actions=[
                            "budgets:ModifyBudget",
                            "budgets:ViewBudget",
                            "budgets:TagResource",
                        ],
                        resources=[budget_arn],
                    )
                ]
            ),
            log_group=log_group,
            install_latest_aws_sdk=False,
        )
