#!/bin/bash
# Pack the app and upload it to the prototype's bucket; the waiting server then builds and starts it.
#   deploy/package.sh [stack-name] [region]
set -euo pipefail
STACK=${1:-aceit-proto}; REGION=${2:-ap-south-1}
cd "$(dirname "$0")/.."
BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" --query "Stacks[0].Outputs[?OutputKey=='PackageBucket'].OutputValue" --output text)
TMP=$(mktemp -d)
COPYFILE_DISABLE=1 tar czf "$TMP/aceit.tgz" --exclude '__pycache__' --exclude '.DS_Store' \
  Dockerfile .dockerignore apps/api/serve.py apps/api/src apps/web data/blueprints deploy/sql deploy/crops
ls -lh "$TMP/aceit.tgz"
aws s3 cp "$TMP/aceit.tgz" "s3://$BUCKET/aceit.tgz" --region "$REGION"
rm -rf "$TMP"; echo "uploaded; the server needs about 5-10 minutes to build and load. Watch: aws ssm start-session --target <InstanceId>  then  sudo tail -f /var/log/aceit-setup.log"
