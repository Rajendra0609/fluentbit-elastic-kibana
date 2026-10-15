#!/usr/bin/env bash
# Generates all credentials for the logging stack and stores them in one Secret.
#
# Passwords are random and never written to Git. The script is idempotent: if the
# Secret already exists it does not regenerate anything, because Elasticsearch reads
# ELASTIC_PASSWORD only on first start. Regenerating it would desynchronise the stored data.
#
# One exception: a Secret created by the earlier Fluent Bit version has no FLUENTD_PASSWORD.
# In that case the script adds only that key and leaves every other value untouched.
#
# To rotate later, change the password through the Elasticsearch security API and
# update this Secret to match. Do not just delete and recreate the Secret.
set -euo pipefail

cd "$(dirname "$0")"

NS=logging
SECRET=logging-credentials

kubectl apply -f 00-namespace.yaml >/dev/null

# Passwords use hex only so they are safe inside the JSON bodies the setup Job sends.
hex() { openssl rand -hex "$1"; }

if kubectl -n "$NS" get secret "$SECRET" >/dev/null 2>&1; then
  if [ -n "$(kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data.FLUENTD_PASSWORD}')" ]; then
    echo "Secret $SECRET already exists in namespace $NS. Nothing to do."
    exit 0
  fi

  # Upgrade path: add only the Fluentd key. Base64 of hex text contains no quotes or
  # backslashes, so it is safe to place inside the JSON patch below.
  value="$(hex 24 | tr -d '\n' | base64 | tr -d '\n')"
  kubectl -n "$NS" patch secret "$SECRET" --type merge \
    -p "{\"data\":{\"FLUENTD_PASSWORD\":\"$value\"}}" >/dev/null
  echo "Added FLUENTD_PASSWORD to existing Secret $SECRET."
  echo "deploy.sh re-runs the setup Job, which creates the fluentd user with this password."
  exit 0
fi

kubectl -n "$NS" create secret generic "$SECRET" \
  --from-literal=ELASTIC_PASSWORD="$(hex 24)" \
  --from-literal=KIBANA_SYSTEM_PASSWORD="$(hex 24)" \
  --from-literal=FLUENTD_PASSWORD="$(hex 24)" \
  --from-literal=KIBANA_SECURITY_KEY="$(hex 32)" \
  --from-literal=KIBANA_SAVED_OBJECTS_KEY="$(hex 32)" \
  --from-literal=KIBANA_REPORTING_KEY="$(hex 32)"

echo "Created Secret $SECRET in namespace $NS."
echo "Read the elastic password with:"
echo "  kubectl -n $NS get secret $SECRET -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d; echo"
