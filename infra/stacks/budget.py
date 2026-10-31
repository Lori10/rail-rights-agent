"""Opt-in monthly cost budget with email alerts (free-plan credit protection)."""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_budgets as budgets
from constructs import Construct

# (notification type, percentage of the monthly limit)
_ALERTS = [("ACTUAL", 50), ("ACTUAL", 80), ("FORECASTED", 100)]


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
        budgets.CfnBudget(
            self,
            "MonthlyCost",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="rail-rights-agent-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=limit_usd, unit="USD"),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type=kind,
                        comparison_operator="GREATER_THAN",
                        threshold=threshold,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            subscription_type="EMAIL", address=email
                        )
                    ],
                )
                for kind, threshold in _ALERTS
            ],
        )
