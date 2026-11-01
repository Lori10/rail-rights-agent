"""CDK entry point (``cdk.json`` runs ``python -m infra.app``)."""

import os

import aws_cdk as cdk

from infra.stacks.baseline import BaselineStack
from infra.stacks.budget import BudgetStack
from infra.stacks.knowledge_base import KnowledgeBaseStack
from infra.tagging import apply_project_tags
from rail_rights_agent.knowledge_base.deployment import STACK_NAME as KNOWLEDGE_BASE_STACK
from rail_rights_agent.settings import Settings, load_settings

STACK_PREFIX = "RailRightsAgent"


def build_app(settings: Settings, outdir: str | None = None) -> cdk.App:
    """Build every stack. The account comes from the deploying credentials (unset offline)."""
    app = cdk.App(outdir=outdir)
    env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=settings.aws_region)
    BaselineStack(app, f"{STACK_PREFIX}-Baseline", env=env)
    KnowledgeBaseStack(
        app, KNOWLEDGE_BASE_STACK, embedding_model_id=settings.embedding_model_id, env=env
    )
    if settings.budget_email:
        BudgetStack(
            app,
            f"{STACK_PREFIX}-Budget",
            email=settings.budget_email,
            limit_usd=settings.budget_limit_usd,
            env=env,
        )
    apply_project_tags(app)
    return app


def main() -> None:
    build_app(load_settings()).synth()


if __name__ == "__main__":
    main()
