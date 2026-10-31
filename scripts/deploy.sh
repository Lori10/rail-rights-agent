#!/usr/bin/env bash
# Deploy every stack to eu-north-1 with the configured profile. Live: creates AWS resources.
#   --dry-run  print the target and synthesise only; no AWS calls
source "$(dirname "$0")/_cdk.sh"
if [[ "${1:-}" == "--dry-run" ]]; then
  npx --yes "aws-cdk@$CDK_CLI_VERSION" synth --quiet
  exit
fi
cdk deploy --all --require-approval never
