set -eu
cd /opt/aceit
aws s3 cp s3://aceit-proto-bucket-2jyvdfsyc9c6/code.tgz /tmp/code.tgz --region ap-south-1
docker tag aceit aceit:prev
tar xzf /tmp/code.tgz -C /opt/aceit
docker build -t aceit /opt/aceit
PGPASS=$(cat /opt/aceit/db-password)
# an AI key, if one was stored in Parameter Store (aws ssm put-parameter --name /aceit/gemini-api-key --type SecureString ...), turns the explanation writer on
KEY=$(aws ssm get-parameter --name /aceit/gemini-api-key --with-decryption --query Parameter.Value --output text --region ap-south-1 2>/dev/null || true)
AI=""; [ -n "$KEY" ] && AI="-e GEMINI_API_KEY=$KEY -e ACEIT_EXPLAIN=1 -e ACEIT_EXPLAIN_BATCH=100"
run_app() { docker run -d --name app --network aceit --restart always -p 80:8000 -e ACEIT_DATABASE_URL="postgresql://postgres:$PGPASS@db:5432/aceit" \
  -e ACEIT_AUTH_MODE=jwt -e ACEIT_COGNITO_REGION=ap-south-1 -e ACEIT_COGNITO_POOL_ID=ap-south-1_CZ5wARQb1 \
  -e ACEIT_COGNITO_CLIENT_ID=drq4j56fiuornvf070jk2oh8t -e ACEIT_COGNITO_DOMAIN=aceit-prep.auth.ap-south-1.amazoncognito.com -e ACEIT_RUN_JOBS=1 $AI "$1"; }
docker rm -f app
run_app aceit
for i in $(seq 1 20); do sleep 3; if curl -sf localhost/v1/health >/dev/null; then echo HEALTHY-NEW; exit 0; fi; done
echo "new version failed its health check: rolling back"; docker logs app | tail -20; docker rm -f app; run_app aceit:prev; exit 1
