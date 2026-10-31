"""Knowledge-base stack: documents bucket, S3 Vectors index, Bedrock Knowledge Base (design D1-D7).

Documents are uploaded by the ingest command, not by CDK: ``docs/source/`` is gitignored, so an
asset would break offline and CI synthesis (D5).
"""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3vectors as s3vectors
from constructs import Construct

from rail_rights_agent.knowledge_base.deployment import (
    DOCUMENTS_PREFIX,
    OUTPUT_DATA_SOURCE_ID,
    OUTPUT_DOCUMENTS_BUCKET,
    OUTPUT_KNOWLEDGE_BASE_ID,
)

# Titan Text Embeddings V2 at its highest-quality size. The index, the knowledge base and the model
# must agree; another embedding model means a design change, not just an env var (D2).
EMBEDDING_DIMENSIONS = 1024

# The knowledge base stores chunk text and its own chunk metadata under these keys. They exceed the
# 2 KB filterable-metadata limit of S3 Vectors, so they must be non-filterable (D3).
BEDROCK_NON_FILTERABLE_KEYS = ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]

_KB = bedrock.CfnKnowledgeBase
_DS = bedrock.CfnDataSource

_VECTOR_ACTIONS = [
    "s3vectors:PutVectors",
    "s3vectors:GetVectors",
    "s3vectors:DeleteVectors",
    "s3vectors:QueryVectors",
    "s3vectors:GetIndex",
]


class KnowledgeBaseStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        embedding_model_id: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        documents = s3.Bucket(
            self,
            "Documents",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        vector_bucket = s3vectors.CfnVectorBucket(self, "VectorBucket")
        index = s3vectors.CfnIndex(
            self,
            "VectorIndex",
            vector_bucket_arn=vector_bucket.attr_vector_bucket_arn,
            data_type="float32",
            dimension=EMBEDDING_DIMENSIONS,
            distance_metric="cosine",
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=BEDROCK_NON_FILTERABLE_KEYS
            ),
        )

        embedding_model_arn = self.format_arn(
            service="bedrock",
            account="",
            resource="foundation-model",
            resource_name=embedding_model_id,
            arn_format=cdk.ArnFormat.SLASH_RESOURCE_NAME,
        )

        role = iam.Role(
            self,
            "ServiceRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": self.format_arn(
                            service="bedrock",
                            resource="knowledge-base",
                            resource_name="*",
                            arn_format=cdk.ArnFormat.SLASH_RESOURCE_NAME,
                        )
                    },
                },
            ),
        )
        # A separate policy the knowledge base depends on: it validates the index and the model
        # with this role at creation, so the permissions must be attached first (D7).
        policy = iam.Policy(
            self,
            "ServiceRolePolicy",
            roles=[role],
            statements=[
                iam.PolicyStatement(
                    actions=["bedrock:InvokeModel"], resources=[embedding_model_arn]
                ),
                iam.PolicyStatement(actions=["s3:ListBucket"], resources=[documents.bucket_arn]),
                iam.PolicyStatement(
                    actions=["s3:GetObject"],
                    resources=[documents.arn_for_objects(f"{DOCUMENTS_PREFIX}*")],
                ),
                iam.PolicyStatement(actions=_VECTOR_ACTIONS, resources=[index.ref]),
            ],
        )

        knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "KnowledgeBase",
            name="rail-rights-agent",
            description="EU 2021/782 (EN, DE) and DB conditions of carriage (DE)",
            role_arn=role.role_arn,
            knowledge_base_configuration=_KB.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=_KB.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=embedding_model_arn,
                    embedding_model_configuration=_KB.EmbeddingModelConfigurationProperty(
                        bedrock_embedding_model_configuration=_KB.BedrockEmbeddingModelConfigurationProperty(
                            dimensions=EMBEDDING_DIMENSIONS,
                            embedding_data_type="FLOAT32",
                        )
                    ),
                ),
            ),
            storage_configuration=_KB.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=_KB.S3VectorsConfigurationProperty(index_arn=index.ref),
            ),
        )
        knowledge_base.node.add_dependency(policy)

        data_source = bedrock.CfnDataSource(
            self,
            "DataSource",
            name="rights-documents",
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            data_deletion_policy="DELETE",
            data_source_configuration=_DS.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=_DS.S3DataSourceConfigurationProperty(
                    bucket_arn=documents.bucket_arn,
                    inclusion_prefixes=[DOCUMENTS_PREFIX],
                ),
            ),
            vector_ingestion_configuration=_DS.VectorIngestionConfigurationProperty(
                chunking_configuration=_DS.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=_DS.FixedSizeChunkingConfigurationProperty(
                        max_tokens=300, overlap_percentage=20
                    ),
                )
            ),
        )

        cdk.CfnOutput(self, OUTPUT_KNOWLEDGE_BASE_ID, value=knowledge_base.attr_knowledge_base_id)
        cdk.CfnOutput(self, OUTPUT_DATA_SOURCE_ID, value=data_source.attr_data_source_id)
        cdk.CfnOutput(self, OUTPUT_DOCUMENTS_BUCKET, value=documents.bucket_name)
