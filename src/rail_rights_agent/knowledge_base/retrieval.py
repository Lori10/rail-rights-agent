"""Retrieve ranked, attributed passages from the knowledge base (design D8).

Input is validated before any AWS call. Passages keep the service's ranking, best first.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from botocore.exceptions import ClientError

from rail_rights_agent.knowledge_base.catalogue import LANGUAGES
from rail_rights_agent.knowledge_base.errors import KnowledgeBaseError

if TYPE_CHECKING:
    from mypy_boto3_bedrock_agent_runtime import AgentsforBedrockRuntimeClient
    from mypy_boto3_bedrock_agent_runtime.type_defs import (
        KnowledgeBaseRetrievalResultTypeDef,
        KnowledgeBaseVectorSearchConfigurationTypeDef,
    )

DEFAULT_TOP_K = 5
MAX_TOP_K = 20
# Set by the default parser for PDF chunks; not guaranteed, so the page is optional.
PAGE_NUMBER_KEY = "x-amz-bedrock-kb-document-page-number"


@dataclass(frozen=True)
class Passage:
    text: str
    document: str
    language: str
    source_uri: str
    score: float
    page: int | None


def validate_request(question: str, *, language: str | None, top_k: int) -> None:
    """Reject a request that would be invalid, without calling AWS."""
    if not question.strip():
        raise ValueError("The question is empty")
    if not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}, got {top_k}")
    if language is not None and language not in LANGUAGES:
        raise ValueError(f"Unsupported language {language!r}; supported: {', '.join(LANGUAGES)}")


class KnowledgeBaseRetriever:
    def __init__(self, client: "AgentsforBedrockRuntimeClient", knowledge_base_id: str) -> None:
        self._client = client
        self._knowledge_base_id = knowledge_base_id

    def retrieve(
        self, question: str, *, language: str | None = None, top_k: int = DEFAULT_TOP_K
    ) -> list[Passage]:
        validate_request(question, language=language, top_k=top_k)
        search: KnowledgeBaseVectorSearchConfigurationTypeDef = {"numberOfResults": top_k}
        if language is not None:
            # The stubs type the value as a JSON object; the API takes any JSON value (a string).
            value = cast("dict[str, Any]", language)
            search["filter"] = {"equals": {"key": "language", "value": value}}
        try:
            response = self._client.retrieve(
                knowledgeBaseId=self._knowledge_base_id,
                retrievalQuery={"text": question},
                retrievalConfiguration={"vectorSearchConfiguration": search},
            )
        except ClientError as err:
            raise KnowledgeBaseError.from_client_error(err) from err
        return [_passage(r) for r in response["retrievalResults"]]


def _passage(result: "KnowledgeBaseRetrievalResultTypeDef") -> Passage:
    metadata: dict[str, Any] = dict(result.get("metadata", {}))
    page = metadata.get(PAGE_NUMBER_KEY)
    return Passage(
        text=result["content"].get("text", ""),
        document=str(metadata.get("document", "")),
        language=str(metadata.get("language", "")),
        source_uri=result.get("location", {}).get("s3Location", {}).get("uri", ""),
        score=result.get("score", 0.0),
        page=int(page) if page is not None else None,
    )
