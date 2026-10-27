#!/bin/bash
# Ship code changes to the running prototype (the 68 MB of question images and SQL are not re-uploaded).
#   deploy/update.sh [stack-name] [region]
# Packs the code, uploads it, then rebuilds on the server through Session Manager and restarts the app; if the new version fails its
# health check the server rolls back to the previous image by itself.
set -euo pipefail
STACK=${1:-aceit-proto}; REGION=${2:-ap-south-1}
cd "$(dirname "$0")/.."
out() { aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
BUCKET=$(out PackageBucket); INSTANCE=$(out InstanceId)
TMP=$(mktemp -d)
COPYFILE_DISABLE=1 tar czf "$TMP/code.tgz" --exclude '__pycache__' --exclude '.DS_Store' Dockerfile .dockerignore apps/api/serve.py apps/api/src apps/web data/blueprints
aws s3 cp "$TMP/code.tgz" "s3://$BUCKET/code.tgz" --region "$REGION" --no-progress
PARAMS=$(python3 -c "import json,sys; print(json.dumps({'commands': sys.stdin.read().splitlines(), 'executionTimeout': ['900']}))" < deploy/server-update.sh | sed "s/aceit-proto-bucket-2jyvdfsyc9c6/$BUCKET/g")
CID=$(aws ssm send-command --instance-ids "$INSTANCE" --document-name AWS-RunShellScript --region "$REGION" --parameters "$PARAMS" --query Command.CommandId --output text)
until S=$(aws ssm get-command-invocation --command-id "$CID" --instance-id "$INSTANCE" --region "$REGION" --query Status --output text) && [[ "$S" =~ ^(Success|Failed|Cancelled|TimedOut)$ ]]; do sleep 10; done
echo "update: $S"; [ "$S" = Success ]
