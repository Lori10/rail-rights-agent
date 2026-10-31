"""Command line: ``python -m rail_rights_agent.knowledge_base {ingest,retrieve}`` (design D8).

Both commands are live: they use the configured AWS profile and the deployed knowledge-base stack.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from botocore.exceptions import BotoCoreError

from rail_rights_agent.knowledge_base.aws import clients
from rail_rights_agent.knowledge_base.catalogue import LANGUAGES
from rail_rights_agent.knowledge_base.errors import KnowledgeBaseError
from rail_rights_agent.knowledge_base.ingest import ingest_catalogue, resolve_stack_outputs
from rail_rights_agent.knowledge_base.retrieval import (
    DEFAULT_TOP_K,
    KnowledgeBaseRetriever,
    Passage,
    validate_request,
)
from rail_rights_agent.settings import load_settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rail_rights_agent.knowledge_base",
        description="Ingest the rights documents into, or query, the deployed knowledge base.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser(
        "ingest", help="upload the catalogued PDFs and run an ingestion job"
    )
    ingest.add_argument(
        "--source-dir",
        type=Path,
        default=Path("docs/source"),
        help="folder holding the source PDFs (default: docs/source)",
    )
    retrieve = commands.add_parser("retrieve", help="print the passages retrieved for a question")
    retrieve.add_argument("question")
    retrieve.add_argument("--language", choices=LANGUAGES, help="only passages in this language")
    retrieve.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="number of passages")
    return parser


def _show(index: int, p: Passage) -> str:
    page = f" p.{p.page}" if p.page is not None else ""
    header = f"[{index}] {p.document} ({p.language}){page}  score {p.score:.3f}"
    return f"{header}\n{p.source_uri}\n{p.text}"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "retrieve":
            validate_request(args.question, language=args.language, top_k=args.top_k)
        aws = clients(load_settings())
        if args.command == "ingest":
            result = ingest_catalogue(
                aws.cloudformation, aws.s3, aws.bedrock_agent, args.source_dir
            )
            print(
                f"Ingestion job {result.job_id} {result.status}: {result.scanned} scanned, "
                f"{result.indexed} indexed, {result.failed} failed"
            )
        else:
            outputs = resolve_stack_outputs(aws.cloudformation)
            retriever = KnowledgeBaseRetriever(aws.bedrock_agent_runtime, outputs.knowledge_base_id)
            passages = retriever.retrieve(args.question, language=args.language, top_k=args.top_k)
            print("\n\n".join(_show(i, p) for i, p in enumerate(passages, 1)) or "No passages.")
    except (KnowledgeBaseError, ValueError, BotoCoreError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
