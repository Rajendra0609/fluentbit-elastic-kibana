#!/usr/bin/env bash
# Generates and imports the dashboards, then creates or updates their log alert rules.
# Safe to re-run: saved objects and existing alert rules are updated in place.
#
#   KIBANA_URL      default http://localhost:5601. Open the tunnel first:
#                   kubectl -n logging port-forward svc/kibana 5601:5601
#   ELASTIC_PASSWORD  default: read from the logging-credentials Secret with kubectl
#   KIBANA_ALERT_CONNECTOR_ID  default .server-log; used by create-alerts.py
#   SKIP_ALERTS     set to 1 to import dashboards without creating/updating alert rules
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"
SKIP_ALERTS="${SKIP_ALERTS:-0}"

if [ -z "${ELASTIC_PASSWORD:-}" ]; then
  command -v kubectl >/dev/null 2>&1 || {
    echo "kubectl is required to read logging-credentials; set ELASTIC_PASSWORD to provide it directly." >&2
    exit 1
  }
  ELASTIC_PASSWORD="$(kubectl -n logging get secret logging-credentials \
    -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d)"
fi

if [ -z "$ELASTIC_PASSWORD" ]; then
  echo "ELASTIC_PASSWORD is empty; check the logging-credentials Secret or set it in the environment." >&2
  exit 1
fi
export ELASTIC_PASSWORD KIBANA_URL

command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to generate dashboards and configure alert rules." >&2
  exit 1
}

command -v curl >/dev/null 2>&1 || {
  echo "curl is required to import saved objects into Kibana." >&2
  exit 1
}

python3 build_dashboards.py

response="$(curl -sS -u "elastic:${ELASTIC_PASSWORD}" \
  -H 'kbn-xsrf: true' \
  -X POST "${KIBANA_URL}/api/saved_objects/_import?overwrite=true" \
  --form file=@dashboards.ndjson)"

# Summarise the result. Kibana reports per-object failures in "errors" even when the
# HTTP status is 200, so the success flag is what matters.
printf '%s' "$response" | python3 -c '
import json
import sys

raw = sys.stdin.read()
try:
    result = json.loads(raw)
except json.JSONDecodeError:
    print("Kibana did not return JSON:\n" + raw)
    sys.exit(1)
if "statusCode" in result:
    print("Kibana returned an error:", result.get("message", result))
    sys.exit(1)
print("imported objects:", result.get("successCount", 0))
for err in result.get("errors", []):
    error = err.get("error", {})
    print("  FAILED {} {}: {}".format(err.get("type"), err.get("id"), error.get("type")))
print("success:", result.get("success"))
sys.exit(0 if result.get("success") else 1)
'

if [ "$SKIP_ALERTS" != "1" ]; then
  echo
  echo "Creating/updating Kubernetes log alert rules..."
  python3 create-alerts.py
fi

echo
echo "Open Kibana: Analytics -> Dashboards -> search for \"Kubernetes\"."
