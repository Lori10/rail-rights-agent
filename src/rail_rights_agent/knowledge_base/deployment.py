"""Names shared by the knowledge-base stack (infra) and the ingestion command that reads it."""

STACK_NAME = "RailRightsAgent-KnowledgeBase"

OUTPUT_KNOWLEDGE_BASE_ID = "KnowledgeBaseId"
OUTPUT_DATA_SOURCE_ID = "DataSourceId"
OUTPUT_DOCUMENTS_BUCKET = "DocumentsBucketName"

# The data source reads only this prefix of the documents bucket.
DOCUMENTS_PREFIX = "documents/"
