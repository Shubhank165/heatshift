#!/usr/bin/env bash
# Build the dashboard and publish it to AWS Amplify Hosting (manual deployment).
set -euo pipefail
APP_ID="${AMPLIFY_APP_ID:-d2gge5mhbtu65h}"
REGION=ap-south-1
cd "$(dirname "$0")/../frontend"
npx vite build >/dev/null
rm -f /tmp/heatshift-web.zip && (cd dist && zip -qr /tmp/heatshift-web.zip .)
read -r JOB URL < <(aws amplify create-deployment --region $REGION --app-id "$APP_ID" --branch-name main \
  --query '[jobId, zipUploadUrl]' --output text)
curl -sf -T /tmp/heatshift-web.zip "$URL"
aws amplify start-deployment --region $REGION --app-id "$APP_ID" --branch-name main --job-id "$JOB" \
  --query 'jobSummary.status' --output text
echo "https://main.$APP_ID.amplifyapp.com"
