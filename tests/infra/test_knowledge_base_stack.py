"""Spec: knowledge-base (infrastructure requirements, offline synthesis)."""

import json
import os
from collections.abc import Iterator
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from infra.app import build_app
from rail_rights_agent.settings import load_settings

KNOWLEDGE_BASE = "RailRightsAgent-KnowledgeBase"
EMBEDDING_MODEL_ID = load_settings({}).embedding_model_id


@pytest.fixture(scope="module", autouse=True)
def no_aws_credentials() -> Iterator[None]:
    with pytest.MonkeyPatch.context() as mp:
        for var in list(os.environ):
            if var.startswith(("AWS_", "CDK_DEFAULT_")):
                mp.delenv(var)
        yield


@pytest.fixture(scope="module")
def app() -> cdk.App:
    return build_app(load_settings({"RAILAGENT_BUDGET_EMAIL": "alerts@example.com"}))


@pytest.fixture(scope="module")
def template(app: cdk.App) -> dict[str, Any]:
    stack = app.node.find_child(KNOWLEDGE_BASE)
    assert isinstance(stack, cdk.Stack)
    result: dict[str, Any] = Template.from_stack(stack).to_json()
    return result


def resources_of(template: dict[str, Any], type_: str) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in template["Resources"].items() if v["Type"] == type_}


def only(template: dict[str, Any], type_: str) -> tuple[str, dict[str, Any]]:
    found = resources_of(template, type_)
    assert len(found) == 1, f"expected one {type_}, found {sorted(found)}"
    ((logical_id, res),) = found.items()
    return logical_id, res["Properties"]


def documents_bucket(template: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return only(template, "AWS::S3::Bucket")


def kb_role(template: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    roles = {
        k: v["Properties"]
        for k, v in resources_of(template, "AWS::IAM::Role").items()
        if any(
            s.get("Principal", {}).get("Service") == "bedrock.amazonaws.com"
            for s in v["Properties"]["AssumeRolePolicyDocument"]["Statement"]
        )
    }
    assert len(roles) == 1, f"expected one Bedrock service role, found {sorted(roles)}"
    ((logical_id, props),) = roles.items()
    return logical_id, props


def kb_role_policies(template: dict[str, Any]) -> dict[str, dict[str, Any]]:
    role_id, _ = kb_role(template)
    return {
        k: v["Properties"]
        for k, v in resources_of(template, "AWS::IAM::Policy").items()
        if {"Ref": role_id} in v["Properties"]["Roles"]
    }


def kb_role_statements(template: dict[str, Any]) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    for props in kb_role_policies(template).values():
        statements += props["PolicyDocument"]["Statement"]
    return statements


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


# --- Documents bucket ---------------------------------------------------------------------------


def test_documents_bucket_is_private_and_encrypted(template):
    _, props = documents_bucket(template)
    assert props["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "BlockPublicPolicy": True,
        "IgnorePublicAcls": True,
        "RestrictPublicBuckets": True,
    }
    assert props["BucketEncryption"]["ServerSideEncryptionConfiguration"]


def test_documents_bucket_requires_tls(template):
    bucket_id, _ = documents_bucket(template)
    policies = [
        p["Properties"]
        for p in resources_of(template, "AWS::S3::BucketPolicy").values()
        if p["Properties"]["Bucket"] == {"Ref": bucket_id}
    ]
    deny_insecure = [
        s
        for p in policies
        for s in p["PolicyDocument"]["Statement"]
        if s["Effect"] == "Deny"
        and s.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") == "false"
    ]
    assert deny_insecure


# --- Vector store -------------------------------------------------------------------------------


def test_one_vector_bucket(template):
    only(template, "AWS::S3Vectors::VectorBucket")


def test_index_matches_embedding_model(template):
    _, props = only(template, "AWS::S3Vectors::Index")
    assert props["DataType"] == "float32"
    assert props["Dimension"] == 1024
    assert props["DistanceMetric"] == "cosine"
    assert {"AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"} <= set(
        props["MetadataConfiguration"]["NonFilterableMetadataKeys"]
    )


def test_index_belongs_to_the_vector_bucket(template):
    bucket_id, _ = only(template, "AWS::S3Vectors::VectorBucket")
    _, props = only(template, "AWS::S3Vectors::Index")
    assert bucket_id in json.dumps(props.get("VectorBucketArn", props.get("VectorBucketName")))


def test_no_opensearch_serverless_in_any_stack(app: cdk.App):
    for stack in (c for c in app.node.children if isinstance(c, cdk.Stack)):
        resources = Template.from_stack(stack).to_json().get("Resources", {})
        types = {r["Type"] for r in resources.values()}
        assert not [t for t in types if t.startswith("AWS::OpenSearchServerless::")], stack


# --- Knowledge base and data source -------------------------------------------------------------


def test_knowledge_base_uses_s3_vectors_index(template):
    index_id, _ = only(template, "AWS::S3Vectors::Index")
    _, props = only(template, "AWS::Bedrock::KnowledgeBase")
    storage = props["StorageConfiguration"]
    assert storage["Type"] == "S3_VECTORS"
    assert storage["S3VectorsConfiguration"]["IndexArn"] == {"Ref": index_id}


def test_knowledge_base_embeds_with_configured_model_at_1024_float32(template):
    _, props = only(template, "AWS::Bedrock::KnowledgeBase")
    assert props["KnowledgeBaseConfiguration"]["Type"] == "VECTOR"
    vector = props["KnowledgeBaseConfiguration"]["VectorKnowledgeBaseConfiguration"]
    arn = json.dumps(vector["EmbeddingModelArn"])
    assert f"foundation-model/{EMBEDDING_MODEL_ID}" in arn
    assert vector["EmbeddingModelConfiguration"]["BedrockEmbeddingModelConfiguration"] == {
        "Dimensions": 1024,
        "EmbeddingDataType": "FLOAT32",
    }


def test_knowledge_base_uses_the_service_role(template):
    role_id, _ = kb_role(template)
    _, props = only(template, "AWS::Bedrock::KnowledgeBase")
    assert props["RoleArn"] == {"Fn::GetAtt": [role_id, "Arn"]}


def test_knowledge_base_waits_for_role_policy(template):
    kb_id, _ = only(template, "AWS::Bedrock::KnowledgeBase")
    depends_on = set(as_list(template["Resources"][kb_id].get("DependsOn", [])))
    assert set(kb_role_policies(template)) <= depends_on


def test_data_source_reads_documents_prefix_with_fixed_size_chunking(template):
    bucket_id, _ = documents_bucket(template)
    kb_id, _ = only(template, "AWS::Bedrock::KnowledgeBase")
    _, props = only(template, "AWS::Bedrock::DataSource")
    assert props["KnowledgeBaseId"] == {"Ref": kb_id} or kb_id in json.dumps(
        props["KnowledgeBaseId"]
    )
    config = props["DataSourceConfiguration"]
    assert config["Type"] == "S3"
    assert config["S3Configuration"]["BucketArn"] == {"Fn::GetAtt": [bucket_id, "Arn"]}
    assert config["S3Configuration"]["InclusionPrefixes"] == ["documents/"]
    chunking = props["VectorIngestionConfiguration"]["ChunkingConfiguration"]
    assert chunking == {
        "ChunkingStrategy": "FIXED_SIZE",
        "FixedSizeChunkingConfiguration": {"MaxTokens": 300, "OverlapPercentage": 20},
    }
    assert props["DataDeletionPolicy"] == "DELETE"


# --- Service role -------------------------------------------------------------------------------


def test_service_role_trusts_only_bedrock_for_this_account(template):
    _, props = kb_role(template)
    (statement,) = props["AssumeRolePolicyDocument"]["Statement"]
    assert statement["Principal"] == {"Service": "bedrock.amazonaws.com"}
    condition = statement["Condition"]
    assert "aws:SourceAccount" in condition["StringEquals"]
    assert "knowledge-base/*" in json.dumps(condition["ArnLike"]["aws:SourceArn"])


def test_service_role_invokes_only_the_embedding_model(template):
    statements = [s for s in kb_role_statements(template) if "bedrock:" in json.dumps(s["Action"])]
    assert [as_list(s["Action"]) for s in statements] == [["bedrock:InvokeModel"]]
    (resource,) = as_list(statements[0]["Resource"])
    assert f"foundation-model/{EMBEDDING_MODEL_ID}" in json.dumps(resource)


def test_service_role_reads_only_the_documents_bucket(template):
    bucket_id, _ = documents_bucket(template)
    statements = [s for s in kb_role_statements(template) if '"s3:' in json.dumps(s["Action"])]
    actions = {a for s in statements for a in as_list(s["Action"])}
    assert actions == {"s3:ListBucket", "s3:GetObject"}
    for s in statements:
        for resource in as_list(s["Resource"]):
            assert bucket_id in json.dumps(resource), resource


def test_service_role_uses_only_its_vector_index(template):
    index_id, _ = only(template, "AWS::S3Vectors::Index")
    statements = [
        s for s in kb_role_statements(template) if "s3vectors:" in json.dumps(s["Action"])
    ]
    actions = {a for s in statements for a in as_list(s["Action"])}
    assert actions == {
        "s3vectors:PutVectors",
        "s3vectors:GetVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:QueryVectors",
        "s3vectors:GetIndex",
    }
    assert all(as_list(s["Resource"]) == [{"Ref": index_id}] for s in statements)


def test_service_role_has_no_other_permissions(template):
    for s in kb_role_statements(template):
        for action in as_list(s["Action"]):
            assert action.split(":")[0] in {"bedrock", "s3", "s3vectors"}, action
            assert action != "*" and not action.endswith(":*"), action


# --- Outputs ------------------------------------------------------------------------------------


def test_stack_outputs_ids(template):
    assert {"KnowledgeBaseId", "DataSourceId", "DocumentsBucketName"} <= set(template["Outputs"])
