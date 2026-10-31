"""Spec: knowledge-base / The knowledge base holds exactly the catalogued source documents."""

import json

from rail_rights_agent.knowledge_base.catalogue import CATALOGUE, LANGUAGES, sidecar_json


def test_catalogue_holds_exactly_the_three_source_documents():
    assert {(d.filename, d.document, d.language) for d in CATALOGUE} == {
        ("eu-2021-782-en.pdf", "eu-2021-782", "en"),
        ("eu-2021-782-de.pdf", "eu-2021-782", "de"),
        ("db-befoerderungsbedingungen-de.pdf", "db-befoerderungsbedingungen", "de"),
    }


def test_supported_languages():
    assert set(LANGUAGES) == {"en", "de"}


def test_sidecar_carries_document_id_and_language():
    for doc in CATALOGUE:
        assert json.loads(sidecar_json(doc)) == {
            "metadataAttributes": {"document": doc.document, "language": doc.language}
        }
