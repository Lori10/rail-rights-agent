"""Spec: knowledge-base / retrieval requirements."""

from typing import Any

import pytest
from botocore.stub import Stubber

from rail_rights_agent.knowledge_base.errors import KnowledgeBaseError
from rail_rights_agent.knowledge_base.retrieval import KnowledgeBaseRetriever, Passage

KB_ID = "KB12345678"
QUESTION = "How much compensation do I get for a 90 minute delay?"
EU_EN_URI = "s3://docs-bucket/documents/eu-2021-782-en.pdf"
DB_DE_URI = "s3://docs-bucket/documents/db-befoerderungsbedingungen-de.pdf"


def result(text: str, uri: str, score: float, **metadata: Any) -> dict[str, Any]:
    return {
        "content": {"type": "TEXT", "text": text},
        "location": {"type": "S3", "s3Location": {"uri": uri}},
        "score": score,
        "metadata": metadata,
    }


def expect_retrieve(
    stub: Stubber,
    results: list[dict[str, Any]],
    *,
    top_k: int = 5,
    language: str | None = None,
    question: str = QUESTION,
) -> None:
    search: dict[str, Any] = {"numberOfResults": top_k}
    if language is not None:
        search["filter"] = {"equals": {"key": "language", "value": language}}
    stub.add_response(
        "retrieve",
        {"retrievalResults": results},
        {
            "knowledgeBaseId": KB_ID,
            "retrievalQuery": {"text": question},
            "retrievalConfiguration": {"vectorSearchConfiguration": search},
        },
    )


@pytest.fixture
def retriever(runtime_client) -> KnowledgeBaseRetriever:
    return KnowledgeBaseRetriever(runtime_client, KB_ID)


def test_passages_carry_attribution_in_service_order(retriever, runtime_stub):
    expect_retrieve(
        runtime_stub,
        [
            result(
                "Article 19: 25 % of the ticket price for a delay of 60 to 119 minutes ...",
                EU_EN_URI,
                0.82,
                document="eu-2021-782",
                language="en",
                **{"x-amz-bedrock-kb-document-page-number": 21.0},
            ),
            result(
                "Fahrgastrechte bei Verspätung ...",
                DB_DE_URI,
                0.61,
                document="db-befoerderungsbedingungen",
                language="de",
            ),
        ],
    )
    passages = retriever.retrieve(QUESTION)
    assert passages == [
        Passage(
            text="Article 19: 25 % of the ticket price for a delay of 60 to 119 minutes ...",
            document="eu-2021-782",
            language="en",
            source_uri=EU_EN_URI,
            score=0.82,
            page=21,
        ),
        Passage(
            text="Fahrgastrechte bei Verspätung ...",
            document="db-befoerderungsbedingungen",
            language="de",
            source_uri=DB_DE_URI,
            score=0.61,
            page=None,
        ),
    ]


def test_no_matches_returns_empty_list(retriever, runtime_stub):
    expect_retrieve(runtime_stub, [])
    assert retriever.retrieve(QUESTION) == []


def test_language_filter_is_sent_and_respected(retriever, runtime_stub):
    question = "Wie viel Entschädigung bekomme ich bei 60 Minuten Verspätung?"
    expect_retrieve(
        runtime_stub,
        [result("Entschädigung: 25 % ...", DB_DE_URI, 0.7, document="eu-2021-782", language="de")],
        language="de",
        question=question,
    )
    passages = retriever.retrieve(question, language="de")
    assert [p.language for p in passages] == ["de"]


def test_unsupported_language_rejected_without_aws_call(retriever, runtime_stub):
    with pytest.raises(ValueError, match=r"en.*de|de.*en"):
        retriever.retrieve(QUESTION, language="fr")


@pytest.mark.parametrize("question", ["", "   \n"])
def test_empty_question_rejected_without_aws_call(retriever, runtime_stub, question):
    with pytest.raises(ValueError, match="empty"):
        retriever.retrieve(question)


@pytest.mark.parametrize("top_k", [0, 21])
def test_result_count_out_of_range_rejected_without_aws_call(retriever, runtime_stub, top_k):
    with pytest.raises(ValueError, match=r"1.*20"):
        retriever.retrieve(QUESTION, top_k=top_k)


def test_default_requests_five_results(retriever, runtime_stub):
    expect_retrieve(runtime_stub, [], top_k=5)
    retriever.retrieve(QUESTION)


def test_custom_result_count_is_sent(retriever, runtime_stub):
    expect_retrieve(runtime_stub, [], top_k=20)
    retriever.retrieve(QUESTION, top_k=20)


def test_unknown_knowledge_base_wrapped_with_service_code(retriever, runtime_stub):
    runtime_stub.add_client_error(
        "retrieve",
        service_error_code="ResourceNotFoundException",
        service_message=f"Knowledge base {KB_ID} not found",
        http_status_code=404,
    )
    with pytest.raises(KnowledgeBaseError, match="ResourceNotFoundException") as err:
        retriever.retrieve(QUESTION)
    assert err.value.code == "ResourceNotFoundException"
