#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# AWS EOL Monitor — Full Deployment Script
# Creates all AWS infrastructure and deploys all three Lambda functions.
#
# Usage:
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh
#
# Prerequisites:
#   - AWS CLI configured with appropriate permissions
#   - Python 3 and pip installed
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
REGION="${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || echo us-east-1)}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
DYNAMO_TABLE="aws-eol-inventory"
CONFIG_TABLE="aws-eol-config"
DEDUP_TABLE="aws-eol-alert-dedup"
SNS_TOPIC="eol-alerts"
COLLECTOR_FN="aws-eol-collector"
API_FN="aws-eol-api"
NOTIFIER_FN="aws-eol-alert-notifier"
IAM_ROLE="EOLCollectorRole"
WARN_DAYS="${WARN_DAYS:-180}"
ZIP_FILE="eol_monitor.zip"

# ── Colours ───────────────────────────────────────────────────────────────────
GRN="\033[32m"; YLW="\033[33m"; RED="\033[31m"; RST="\033[0m"
ok()   { echo -e "${GRN}  ✓ $*${RST}"; }
info() { echo -e "${YLW}  → $*${RST}"; }
err()  { echo -e "${RED}  ✗ $*${RST}"; exit 1; }

echo ""
echo "═══════════════════════════════════════════════"
echo "  AWS EOL Monitor — Deployment"
echo "  Account : $ACCOUNT_ID"
echo "  Region  : $REGION"
echo "═══════════════════════════════════════════════"
echo ""

# ── 1. IAM Role ───────────────────────────────────────────────────────────────
info "Creating IAM role $IAM_ROLE..."
if aws iam get-role --role-name "$IAM_ROLE" &>/dev/null; then
    ok "Role $IAM_ROLE already exists — skipping"
else
    aws iam create-role \
        --role-name "$IAM_ROLE" \
        --assume-role-policy-document file://iam/trust-lambda.json \
        --query "Role.Arn" --output text > /dev/null
    ok "Created role $IAM_ROLE"
fi

info "Attaching policy to $IAM_ROLE..."
aws iam put-role-policy \
    --role-name "$IAM_ROLE" \
    --policy-name EOLCollectorPolicy \
    --policy-document file://iam/eol-collector-policy.json
ok "Policy attached"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${IAM_ROLE}"

# ── 2. DynamoDB Tables ────────────────────────────────────────────────────────
info "Creating DynamoDB table $DYNAMO_TABLE..."
aws dynamodb create-table \
    --table-name "$DYNAMO_TABLE" \
    --attribute-definitions \
        AttributeName=resource_id,AttributeType=S \
        AttributeName=service_type,AttributeType=S \
        AttributeName=eol_status,AttributeType=S \
    --key-schema \
        AttributeName=resource_id,KeyType=HASH \
        AttributeName=service_type,KeyType=RANGE \
    --global-secondary-indexes '[{
        "IndexName":"eol_status-index",
        "KeySchema":[{"AttributeName":"eol_status","KeyType":"HASH"}],
        "Projection":{"ProjectionType":"ALL"}
    }]' \
    --billing-mode PAY_PER_REQUEST \
    --stream-specification StreamEnabled=true,StreamViewType=NEW_IMAGE \
    --region "$REGION" 2>/dev/null || ok "$DYNAMO_TABLE already exists"

aws dynamodb create-table \
    --table-name "$CONFIG_TABLE" \
    --attribute-definitions AttributeName=config_key,AttributeType=S \
    --key-schema AttributeName=config_key,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" 2>/dev/null || ok "$CONFIG_TABLE already exists"

aws dynamodb create-table \
    --table-name "$DEDUP_TABLE" \
    --attribute-definitions AttributeName=alert_key,AttributeType=S \
    --key-schema AttributeName=alert_key,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" 2>/dev/null || ok "$DEDUP_TABLE already exists"

info "Enabling TTL on tables..."
aws dynamodb update-time-to-live --table-name "$DYNAMO_TABLE" \
    --time-to-live-specification Enabled=true,AttributeName=ttl --region "$REGION" 2>/dev/null || true
aws dynamodb update-time-to-live --table-name "$DEDUP_TABLE" \
    --time-to-live-specification Enabled=true,AttributeName=ttl --region "$REGION" 2>/dev/null || true
ok "DynamoDB ready"

# Wait for table to be active
info "Waiting for $DYNAMO_TABLE to become ACTIVE..."
aws dynamodb wait table-exists --table-name "$DYNAMO_TABLE" --region "$REGION"
ok "Tables active"

# ── 3. SNS Topic ──────────────────────────────────────────────────────────────
info "Creating SNS topic $SNS_TOPIC..."
SNS_TOPIC_ARN=$(aws sns create-topic \
    --name "$SNS_TOPIC" \
    --region "$REGION" \
    --query TopicArn --output text)
ok "SNS topic: $SNS_TOPIC_ARN"

# ── 4. Package Lambda ─────────────────────────────────────────────────────────
info "Packaging Lambda functions..."
rm -rf /tmp/eol-package && mkdir /tmp/eol-package
pip3 install requests -t /tmp/eol-package/ --break-system-packages -q
cp backend/*.py /tmp/eol-package/
(cd /tmp/eol-package && zip -r "${OLDPWD}/${ZIP_FILE}" . -q)
ok "Created $ZIP_FILE ($(du -sh "$ZIP_FILE" | cut -f1))"

# ── 5. Lambda Functions ───────────────────────────────────────────────────────
deploy_lambda() {
    local name="$1" handler="$2"
    shift 2
    local env_vars="$*"

    if aws lambda get-function --function-name "$name" --region "$REGION" &>/dev/null; then
        info "Updating $name..."
        aws lambda update-function-code \
            --function-name "$name" \
            --zip-file "fileb://${ZIP_FILE}" \
            --region "$REGION" > /dev/null
        aws lambda update-function-configuration \
            --function-name "$name" \
            --environment "Variables={${env_vars}}" \
            --region "$REGION" > /dev/null
    else
        info "Creating $name..."
        # Wait a moment for IAM role to propagate
        sleep 10
        aws lambda create-function \
            --function-name "$name" \
            --runtime python3.12 \
            --role "$ROLE_ARN" \
            --handler "$handler" \
            --zip-file "fileb://${ZIP_FILE}" \
            --timeout 300 \
            --memory-size 256 \
            --environment "Variables={${env_vars}}" \
            --region "$REGION" > /dev/null
    fi
    ok "$name deployed"
}

deploy_lambda "$COLLECTOR_FN" "eol_collector.lambda_handler" \
    "DYNAMODB_TABLE=${DYNAMO_TABLE},CONFIG_TABLE=${CONFIG_TABLE},SNS_TOPIC_ARN=${SNS_TOPIC_ARN},WARN_DAYS=${WARN_DAYS}"

deploy_lambda "$API_FN" "api_handler.lambda_handler" \
    "DYNAMODB_TABLE=${DYNAMO_TABLE},CONFIG_TABLE=${CONFIG_TABLE},COLLECTOR_FUNCTION=${COLLECTOR_FN}"

deploy_lambda "$NOTIFIER_FN" "alert_notifier.lambda_handler" \
    "SNS_TOPIC_ARN=${SNS_TOPIC_ARN},DEDUP_TABLE=${DEDUP_TABLE}"

# ── 6. EventBridge Schedule ───────────────────────────────────────────────────
info "Creating EventBridge schedule (daily 08:00 UTC)..."
aws events put-rule \
    --name eol-daily-scan \
    --schedule-expression "cron(0 8 * * ? *)" \
    --state ENABLED \
    --region "$REGION" > /dev/null

COLLECTOR_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${COLLECTOR_FN}"

aws events put-targets \
    --rule eol-daily-scan \
    --targets "Id=1,Arn=${COLLECTOR_ARN}" \
    --region "$REGION" > /dev/null

aws lambda add-permission \
    --function-name "$COLLECTOR_FN" \
    --statement-id eol-daily-schedule \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/eol-daily-scan" \
    --region "$REGION" 2>/dev/null || true
ok "EventBridge schedule set"

# ── 7. DynamoDB Streams → Alert Notifier ─────────────────────────────────────
info "Wiring DynamoDB Streams to $NOTIFIER_FN..."
STREAM_ARN=$(aws dynamodb describe-table \
    --table-name "$DYNAMO_TABLE" \
    --region "$REGION" \
    --query "Table.LatestStreamArn" --output text)

NOTIFIER_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${NOTIFIER_FN}"

# Only add if not already mapped
EXISTING=$(aws lambda list-event-source-mappings \
    --function-name "$NOTIFIER_FN" \
    --region "$REGION" \
    --query "EventSourceMappings[?EventSourceArn=='${STREAM_ARN}'].UUID" \
    --output text)

if [ -z "$EXISTING" ]; then
    aws lambda create-event-source-mapping \
        --function-name "$NOTIFIER_FN" \
        --event-source-arn "$STREAM_ARN" \
        --starting-position LATEST \
        --batch-size 10 \
        --region "$REGION" > /dev/null
    ok "Stream trigger created"
else
    ok "Stream trigger already exists"
fi

# ── 8. Run First Scan ─────────────────────────────────────────────────────────
info "Running first scan..."
aws lambda invoke \
    --function-name "$COLLECTOR_FN" \
    --payload '{}' \
    --region "$REGION" \
    /tmp/scan-out.json > /dev/null
cat /tmp/scan-out.json
echo ""
ok "First scan complete"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo -e "${GRN}  Deployment complete!${RST}"
echo ""
echo "  Next steps:"
echo "  1. Set up API Gateway with Lambda proxy to $API_FN"
echo "  2. Subscribe your email to SNS topic:"
echo "     aws sns subscribe --topic-arn $SNS_TOPIC_ARN \\"
echo "       --protocol email --notification-endpoint you@example.com"
echo "  3. Build and deploy the frontend:"
echo "     cd frontend && npm install && npm run build"
echo "     # Then sync build/ to your S3 bucket"
echo "  4. Tail logs: make logs"
echo "═══════════════════════════════════════════════"
