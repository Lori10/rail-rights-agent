#!/usr/bin/env bash
# Shared by deploy.sh and destroy.sh: the pinned CDK CLI and the deploy target from settings.
# Source it; don't run it.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Must be at least as new as the cloud assembly schema of the locked aws-cdk-lib.
CDK_CLI_VERSION=2.1147.0

# Validates settings (region lock) and exports the profile/region; fails loudly on bad config.
eval "$(uv run --quiet python -m infra.env)"
export AWS_REGION="$RAILAGENT_AWS_REGION" AWS_DEFAULT_REGION="$RAILAGENT_AWS_REGION"
echo "CDK target: profile=$RAILAGENT_AWS_PROFILE region=$RAILAGENT_AWS_REGION"

cdk() { npx --yes "aws-cdk@$CDK_CLI_VERSION" "$@" --profile "$RAILAGENT_AWS_PROFILE"; }
