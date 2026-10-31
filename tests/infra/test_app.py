"""Spec: infrastructure-baseline (offline synthesis with CDK assertions)."""

import os
from collections.abc import Iterator
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk import aws_sqs as sqs
from aws_cdk.assertions import Match, Template

from infra.app import build_app
from rail_rights_agent.settings import load_settings

EXPECTED_TAGS = {
    "project": "rail-rights-agent",
    "environment": "dev",
    "managed-by": "cdk",
    "repo": "Lori10/rail-rights-agent",
}
BASELINE = "RailRightsAgent-Baseline"
BUDGET = "RailRightsAgent-Budget"


@pytest.fixture(scope="module", autouse=True)
def no_aws_credentials() -> Iterator[None]:
    """Every test here synthesises with no AWS credentials or account configuration."""
    with pytest.MonkeyPatch.context() as mp:
        for var in list(os.environ):
            if var.startswith(("AWS_", "CDK_DEFAULT_")):
                mp.delenv(var)
        yield


def stacks(app: cdk.App) -> list[cdk.Stack]:
    return [c for c in app.node.children if isinstance(c, cdk.Stack)]


def tags_of(props: dict[str, Any]) -> dict[str, str] | None:
    raw = props.get("Tags", props.get("ResourceTags"))
    if raw is None:
        return None
    if isinstance(raw, dict):
        return dict(raw)
    return {t["Key"]: t["Value"] for t in raw}


@pytest.fixture(scope="module")
def default_app() -> cdk.App:
    app = build_app(load_settings({}))
    baseline = app.node.find_child(BASELINE)
    assert isinstance(baseline, cdk.Stack)
    sqs.Queue(baseline, "TagProbe")  # synth-only probe: any taggable resource
    return app


@pytest.fixture(scope="module")
def budget_app() -> cdk.App:
    return build_app(load_settings({"RAILAGENT_BUDGET_EMAIL": "alerts@example.com"}))


def test_synthesises_without_credentials(default_app: cdk.App):
    assembly = default_app.synth()
    names = {s.stack_name for s in assembly.stacks}
    assert BASELINE in names
    for stack in stacks(default_app):
        assert assembly.get_stack_by_name(stack.stack_name).template is not None


def test_every_stack_targets_eu_north_1(default_app: cdk.App, budget_app: cdk.App):
    all_stacks = stacks(default_app) + stacks(budget_app)
    assert all_stacks
    for stack in all_stacks:
        assert stack.region == "eu-north-1", stack.stack_name


def test_probe_resource_carries_project_tags(default_app: cdk.App):
    baseline = default_app.node.find_child(BASELINE)
    assert isinstance(baseline, cdk.Stack)
    queues = Template.from_stack(baseline).find_resources("AWS::SQS::Queue")
    assert len(queues) == 1
    (queue,) = queues.values()
    assert tags_of(queue["Properties"]) == EXPECTED_TAGS


def test_every_taggable_resource_carries_project_tags(default_app: cdk.App, budget_app: cdk.App):
    checked = 0
    for stack in stacks(default_app) + stacks(budget_app):
        resources = Template.from_stack(stack).to_json().get("Resources", {})
        for logical_id, res in resources.items():
            tags = tags_of(res.get("Properties", {}))
            if tags is None:
                continue
            checked += 1
            missing = {k: v for k, v in EXPECTED_TAGS.items() if tags.get(k) != v}
            assert not missing, f"{stack.stack_name}/{logical_id} missing {missing}"
    assert checked >= 2  # the probe queue and the budget


def test_budget_with_three_notifications_when_email_set(budget_app: cdk.App):
    budget_stack = budget_app.node.find_child(BUDGET)
    assert isinstance(budget_stack, cdk.Stack)
    template = Template.from_stack(budget_stack)
    template.resource_count_is("AWS::Budgets::Budget", 1)
    subscriber = [{"SubscriptionType": "EMAIL", "Address": "alerts@example.com"}]

    def notification(kind: str, threshold: int) -> dict[str, Any]:
        return {
            "Notification": {
                "NotificationType": kind,
                "ComparisonOperator": "GREATER_THAN",
                "Threshold": threshold,
                "ThresholdType": "PERCENTAGE",
            },
            "Subscribers": subscriber,
        }

    template.has_resource_properties(
        "AWS::Budgets::Budget",
        {
            "Budget": Match.object_like(
                {
                    "BudgetType": "COST",
                    "TimeUnit": "MONTHLY",
                    "BudgetLimit": {"Amount": 20, "Unit": "USD"},
                }
            ),
            "NotificationsWithSubscribers": Match.array_equals(
                [
                    notification("ACTUAL", 50),
                    notification("ACTUAL", 80),
                    notification("FORECASTED", 100),
                ]
            ),
        },
    )


def test_no_budget_when_email_unset(default_app: cdk.App):
    assert default_app.node.try_find_child(BUDGET) is None
    for stack in stacks(default_app):
        Template.from_stack(stack).resource_count_is("AWS::Budgets::Budget", 0)
