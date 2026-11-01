"""Spec: knowledge-base / Live retrieval answers the core rights questions in both languages.

Live and billed (Titan embeddings, S3 Vectors queries): run only with ``pytest -m live`` against a
deployed and ingested knowledge base, with fresh ``railagent`` credentials.
"""

import re

import pytest

from rail_rights_agent.knowledge_base.aws import clients
from rail_rights_agent.knowledge_base.ingest import resolve_stack_outputs
from rail_rights_agent.knowledge_base.retrieval import KnowledgeBaseRetriever, Passage
from rail_rights_agent.settings import load_settings

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def retriever() -> KnowledgeBaseRetriever:
    aws = clients(load_settings())
    outputs = resolve_stack_outputs(aws.cloudformation)
    return KnowledgeBaseRetriever(aws.bedrock_agent_runtime, outputs.knowledge_base_id)


def mentions(passage: Passage, pattern: str) -> bool:
    return re.search(pattern, passage.text, re.IGNORECASE) is not None


def show(passages: list[Passage]) -> str:
    return "\n---\n".join(f"[{p.document}/{p.language} {p.score:.2f}] {p.text}" for p in passages)


def test_compensation_in_english(retriever: KnowledgeBaseRetriever):
    passages = retriever.retrieve(
        "How much compensation do I get if my train is 60 or 120 minutes late?", language="en"
    )
    assert any(
        p.document == "eu-2021-782" and mentions(p, r"25\s?%") and mentions(p, r"50\s?%")
        for p in passages
    ), show(passages)


def test_compensation_in_german(retriever: KnowledgeBaseRetriever):
    passages = retriever.retrieve(
        "Welche Entschädigung bekomme ich bei 60 oder 120 Minuten Verspätung?", language="de"
    )
    assert any(
        p.document in {"eu-2021-782", "db-befoerderungsbedingungen"}
        and (mentions(p, r"25\s?%") or mentions(p, r"50\s?%"))
        for p in passages
    ), show(passages)


def test_refund_in_german(retriever: KnowledgeBaseRetriever):
    passages = retriever.retrieve(
        "Wann habe ich Anspruch auf Erstattung des Fahrpreises?", language="de"
    )
    assert any(p.language == "de" and mentions(p, r"erstattung") for p in passages), show(passages)


def test_refund_in_english(retriever: KnowledgeBaseRetriever):
    passages = retriever.retrieve(
        "Can I get a refund of my ticket price if the journey is cancelled or delayed?",
        language="en",
    )
    assert any(
        p.document == "eu-2021-782" and mentions(p, r"reimburse|refund") for p in passages
    ), show(passages)
