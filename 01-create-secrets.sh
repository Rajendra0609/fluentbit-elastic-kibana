#!/usr/bin/env bash
# Generates all credentials for the logging stack and stores them in one Secret.
#
# Passwords are random and never written to Git. The script is idempotent: if the
# Secret already exists it does nothing, because Elasticsearch reads ELASTIC_PASSWORD
# only on first start. Regenerating it would desynchronise the stored data.
#
# To rotate later, change the password through the Elasticsearch security API and
# update this Secret to match. Do not just delete and recreate the Secret.
set -euo pipefail

cd "$(dirname "$0")"

NS=logging
SECRET=logging-credentials

kubectl apply -f 00-namespace.yaml >/dev/null

if kubectl -n "$NS" get secret "$SECRET" >/dev/null 2>&1; then
  echo "Secret $SECRET already exists in namespace $NS. Nothing to do."
  exit 0
fi

# Passwords use hex only so they are safe inside the JSON bodies the setup Job sends.
hex() { openssl rand -hex "$1"; }

kubectl -n "$NS" create secret generic "$SECRET" \
  --from-literal=ELASTIC_PASSWORD="$(hex 24)" \
  --from-literal=KIBANA_SYSTEM_PASSWORD="$(hex 24)" \
  --from-literal=FLUENT_BIT_PASSWORD="$(hex 24)" \
  --from-literal=KIBANA_SECURITY_KEY="$(hex 32)" \
  --from-literal=KIBANA_SAVED_OBJECTS_KEY="$(hex 32)" \
  --from-literal=KIBANA_REPORTING_KEY="$(hex 32)"

echo "Created Secret $SECRET in namespace $NS."
echo "Read the elastic password with:"
echo "  kubectl -n $NS get secret $SECRET -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d; echo"
