#!/usr/bin/env bash
# Destroy every stack of the app (budget included). Live: deletes AWS resources.
source "$(dirname "$0")/_cdk.sh"
cdk destroy --all --force
