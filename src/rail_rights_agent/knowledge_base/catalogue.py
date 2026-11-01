"""The source documents the knowledge base holds, with the metadata used for filtering and citing.

The files live in ``docs/source/`` (gitignored). Ingestion uploads exactly these, each with a
Bedrock metadata sidecar, so a stray file can never enter the knowledge base (design D6).
"""

import json
from dataclasses import dataclass
from typing import Literal

Language = Literal["en", "de"]
LANGUAGES: tuple[Language, ...] = ("en", "de")


@dataclass(frozen=True)
class SourceDocument:
    filename: str
    document: str
    language: Language
    title: str


CATALOGUE: tuple[SourceDocument, ...] = (
    SourceDocument(
        filename="eu-2021-782-en.pdf",
        document="eu-2021-782",
        language="en",
        title="Regulation (EU) 2021/782 on rail passengers' rights and obligations",
    ),
    SourceDocument(
        filename="eu-2021-782-de.pdf",
        document="eu-2021-782",
        language="de",
        title=(
            "Verordnung (EU) 2021/782 über die Rechte und Pflichten der Fahrgäste"
            " im Eisenbahnverkehr"
        ),
    ),
    SourceDocument(
        filename="db-befoerderungsbedingungen-de.pdf",
        document="db-befoerderungsbedingungen",
        language="de",
        title="Beförderungsbedingungen der Deutschen Bahn",
    ),
)


def sidecar_json(doc: SourceDocument) -> bytes:
    """The ``<file>.metadata.json`` body Bedrock reads for an S3 data-source document."""
    attributes = {"document": doc.document, "language": doc.language}
    return json.dumps({"metadataAttributes": attributes}).encode()
