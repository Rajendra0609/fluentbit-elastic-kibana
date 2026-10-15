#!/usr/bin/env bash
# Imports the data view, saved searches, visualizations and dashboards into Kibana.
# Safe to re-run: overwrite=true updates the existing objects in place.
#
#   KIBANA_URL      default http://localhost:5601. Open the tunnel first:
#                   kubectl -n logging port-forward svc/kibana 5601:5601
#   ELASTIC_PASSWORD  default: read from the logging-credentials Secret with kubectl
set -euo pipefail
cd "$(dirname "$0")"

KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"

if [ -z "${ELASTIC_PASSWORD:-}" ]; then
  ELASTIC_PASSWORD="$(kubectl -n logging get secret logging-credentials \
    -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d)"
fi

if [ ! -f dashboards.ndjson ]; then
  echo "dashboards.ndjson not found. Run: python3 build_dashboards.py" >&2
  exit 1
fi

response="$(curl -sS -u "elastic:${ELASTIC_PASSWORD}" \
  -H 'kbn-xsrf: true' \
  -X POST "${KIBANA_URL}/api/saved_objects/_import?overwrite=true" \
  --form file=@dashboards.ndjson)"

# Summarise the result. Kibana reports per-object failures in "errors" even when the
# HTTP status is 200, so the success flag is what matters.
python3 - "$response" <<'EOF'
import json, sys
raw = sys.argv[1]
try:
    result = json.loads(raw)
except json.JSONDecodeError:
    print("Kibana did not return JSON:\n" + raw)
    sys.exit(1)
if "statusCode" in result:
    print(f"Kibana returned an error: {result.get('message', result)}")
    sys.exit(1)
print(f"imported objects: {result.get('successCount', 0)}")
for err in result.get("errors", []):
    print(f"  FAILED {err.get('type')} {err.get('id')}: {err.get('error', {}).get('type')}")
print("success:", result.get("success"))
sys.exit(0 if result.get("success") else 1)
EOF

echo
echo "Open Kibana: Analytics -> Dashboards -> search for \"K8s Logs\"."
