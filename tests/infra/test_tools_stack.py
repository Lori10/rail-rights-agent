"""Specs: tool-functions, train-delay-lookup, claim-submission (infrastructure, offline synth)."""

import os
from collections.abc import Iterator
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from infra.app import build_app
from rail_rights_agent.settings import load_settings
from rail_rights_agent.tools.deployment import (
    ENV_CLAIMS_TABLE,
    ENV_TRIPS_TABLE,
    OUTPUT_CALCULATE_COMPENSATION_FUNCTION_ARN,
    OUTPUT_CLAIMS_TABLE,
    OUTPUT_GET_TRAIN_DELAY_FUNCTION_ARN,
    OUTPUT_SUBMIT_CLAIM_FUNCTION_ARN,
    OUTPUT_TRIPS_TABLE,
    STACK_NAME,
)

HANDLER_PREFIX = "rail_rights_agent.tools.handlers."
READ_ACTIONS = {
    "dynamodb:BatchGetItem",
    "dynamodb:GetRecords",
    "dynamodb:GetShardIterator",
    "dynamodb:Query",
    "dynamodb:GetItem",
    "dynamodb:Scan",
    "dynamodb:ConditionCheckItem",
    "dynamodb:DescribeTable",
}


@pytest.fixture(scope="module", autouse=True)
def no_aws_credentials() -> Iterator[None]:
    with pytest.MonkeyPatch.context() as mp:
        for var in list(os.environ):
            if var.startswith(("AWS_", "CDK_DEFAULT_")):
                mp.delenv(var)
        yield


@pytest.fixture(scope="module")
def template() -> dict[str, Any]:
    app = build_app(load_settings({}))
    stack = app.node.find_child(STACK_NAME)
    assert isinstance(stack, cdk.Stack)
    return dict(Template.from_stack(stack).to_json())


def resources_of(template: dict[str, Any], type_: str) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in template["Resources"].items() if v["Type"] == type_}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def tables(template: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found = resources_of(template, "AWS::DynamoDB::Table")
    assert len(found) == 2, sorted(found)
    return found


def table_by_key(template: dict[str, Any], partition_key: str) -> tuple[str, dict[str, Any]]:
    for logical_id, res in tables(template).items():
        keys = {k["AttributeName"]: k["KeyType"] for k in res["Properties"]["KeySchema"]}
        if keys.get(partition_key) == "HASH":
            return logical_id, res
    raise AssertionError(f"no table keyed by {partition_key}")


def functions(template: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The three tool functions by tool name (custom-resource providers excluded)."""
    found = {}
    for res in resources_of(template, "AWS::Lambda::Function").values():
        handler = res["Properties"].get("Handler", "")
        if handler.startswith(HANDLER_PREFIX):
            found[handler.removeprefix(HANDLER_PREFIX)] = res
    assert set(found) == {"get_train_delay", "calculate_compensation", "submit_claim"}
    return found


def role_id(function: dict[str, Any]) -> str:
    arn = function["Properties"]["Role"]
    assert arn["Fn::GetAtt"][1] == "Arn"
    return str(arn["Fn::GetAtt"][0])


def statements_of_role(template: dict[str, Any], role: str) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    for policy in resources_of(template, "AWS::IAM::Policy").values():
        if {"Ref": role} in policy["Properties"]["Roles"]:
            statements += policy["Properties"]["PolicyDocument"]["Statement"]
    return statements


def resource_ids(statement: dict[str, Any]) -> set[str]:
    """Logical ids a statement's resources point at (ARNs via GetAtt); NoValue is ignored."""
    ids = set()
    for res in as_list(statement["Resource"]):
        assert res != "*"
        if res == {"Ref": "AWS::NoValue"}:
            continue
        assert "Fn::GetAtt" in res, res
        ids.add(res["Fn::GetAtt"][0])
    return ids


# --- Tables -------------------------------------------------------------------------------------


def test_trips_table_is_on_demand_keyed_and_disposable(template):
    _, res = table_by_key(template, "pk")
    props = res["Properties"]
    assert props["BillingMode"] == "PAY_PER_REQUEST"
    assert [(k["AttributeName"], k["KeyType"]) for k in props["KeySchema"]] == [
        ("pk", "HASH"),
        ("sk", "RANGE"),
    ]
    assert res["DeletionPolicy"] == "Delete"
    assert res["UpdateReplacePolicy"] == "Delete"


def test_claims_table_is_on_demand_keyed_and_disposable(template):
    _, res = table_by_key(template, "claim_id")
    props = res["Properties"]
    assert props["BillingMode"] == "PAY_PER_REQUEST"
    assert [(k["AttributeName"], k["KeyType"]) for k in props["KeySchema"]] == [
        ("claim_id", "HASH")
    ]
    assert res["DeletionPolicy"] == "Delete"


def test_no_provisioned_capacity_or_recovery_cost(template):
    for res in tables(template).values():
        assert "ProvisionedThroughput" not in res["Properties"]
        pitr = res["Properties"].get("PointInTimeRecoverySpecification", {})
        assert not pitr.get("PointInTimeRecoveryEnabled", False)


# --- Functions ----------------------------------------------------------------------------------


def test_three_python_312_functions_with_short_timeout(template):
    for name, res in functions(template).items():
        props = res["Properties"]
        assert props["Runtime"] == "python3.12", name
        assert props["Timeout"] <= 10, name
        assert props["Architectures"] == ["arm64"], name
        assert props["Handler"] == f"{HANDLER_PREFIX}{name}"


def test_table_names_reach_functions_through_environment(template):
    fns = functions(template)
    trips_id, _ = table_by_key(template, "pk")
    claims_id, _ = table_by_key(template, "claim_id")
    delay_env = fns["get_train_delay"]["Properties"]["Environment"]["Variables"]
    submit_env = fns["submit_claim"]["Properties"]["Environment"]["Variables"]
    assert delay_env[ENV_TRIPS_TABLE] == {"Ref": trips_id}
    assert submit_env[ENV_CLAIMS_TABLE] == {"Ref": claims_id}
    comp_env = fns["calculate_compensation"]["Properties"].get("Environment", {})
    assert ENV_TRIPS_TABLE not in comp_env.get("Variables", {})
    assert ENV_CLAIMS_TABLE not in comp_env.get("Variables", {})


def test_each_function_logs_to_a_stack_owned_short_lived_log_group(template):
    log_groups = resources_of(template, "AWS::Logs::LogGroup")
    for name, res in functions(template).items():
        group_ref = res["Properties"]["LoggingConfig"]["LogGroup"]["Ref"]
        group = log_groups[group_ref]
        assert group["Properties"]["RetentionInDays"] == 7, name
        assert group["DeletionPolicy"] == "Delete", name


# --- Permissions --------------------------------------------------------------------------------


def test_delay_function_only_reads_the_trips_table(template):
    trips_id, _ = table_by_key(template, "pk")
    statements = statements_of_role(template, role_id(functions(template)["get_train_delay"]))
    assert statements
    for statement in statements:
        assert set(as_list(statement["Action"])) <= READ_ACTIONS
        assert resource_ids(statement) == {trips_id}


def test_submit_function_only_gets_and_puts_claims(template):
    claims_id, _ = table_by_key(template, "claim_id")
    statements = statements_of_role(template, role_id(functions(template)["submit_claim"]))
    assert len(statements) == 1
    assert set(as_list(statements[0]["Action"])) == {"dynamodb:GetItem", "dynamodb:PutItem"}
    assert resource_ids(statements[0]) == {claims_id}


def test_compensation_function_has_no_table_access(template):
    role = role_id(functions(template)["calculate_compensation"])
    assert statements_of_role(template, role) == []


def test_no_statement_in_the_stack_grants_every_resource(template):
    for policy in resources_of(template, "AWS::IAM::Policy").values():
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
            assert "*" not in as_list(statement["Resource"])


# --- Outputs ------------------------------------------------------------------------------------


def test_stack_outputs(template):
    outputs = template["Outputs"]
    assert set(outputs) >= {
        OUTPUT_TRIPS_TABLE,
        OUTPUT_CLAIMS_TABLE,
        OUTPUT_GET_TRAIN_DELAY_FUNCTION_ARN,
        OUTPUT_CALCULATE_COMPENSATION_FUNCTION_ARN,
        OUTPUT_SUBMIT_CLAIM_FUNCTION_ARN,
    }
    trips_id, _ = table_by_key(template, "pk")
    assert outputs[OUTPUT_TRIPS_TABLE]["Value"] == {"Ref": trips_id}
    fns = functions(template)
    for key, name in [
        (OUTPUT_GET_TRAIN_DELAY_FUNCTION_ARN, "get_train_delay"),
        (OUTPUT_CALCULATE_COMPENSATION_FUNCTION_ARN, "calculate_compensation"),
        (OUTPUT_SUBMIT_CLAIM_FUNCTION_ARN, "submit_claim"),
    ]:
        value = outputs[key]["Value"]
        assert value["Fn::GetAtt"][1] == "Arn"
        assert fns[name] == template["Resources"][value["Fn::GetAtt"][0]]
