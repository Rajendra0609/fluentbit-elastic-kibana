#!/usr/bin/env bash
# Generate and import the Jenkins + Kubernetes Kibana saved-object bundle.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"
ELASTIC_USERNAME="${ELASTIC_USERNAME:-elastic}"
JENKINS_NAMESPACE="${JENKINS_NAMESPACE:-jenkins}"

if [ -z "${ELASTIC_PASSWORD:-}" ]; then
  echo "Set ELASTIC_PASSWORD before importing the dashboard." >&2
  exit 1
fi

command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to generate the saved-object bundle." >&2
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "curl is required to import the saved-object bundle." >&2
  exit 1
}

export JENKINS_NAMESPACE
python3 build_dashboard.py

response="$(curl --fail-with-body -sS -u "${ELASTIC_USERNAME}:${ELASTIC_PASSWORD}" \
  -H 'kbn-xsrf: true' \
  -X POST "${KIBANA_URL%/}/api/saved_objects/_import?overwrite=true" \
  --form file=@jenkins-kubernetes.ndjson)"

printf '%s' "$response" | python3 -c '
import json
import sys

raw = sys.stdin.read()
try:
    result = json.loads(raw)
except json.JSONDecodeError:
    print("Kibana returned invalid JSON:\n" + raw, file=sys.stderr)
    raise SystemExit(1)
if "statusCode" in result:
    print("Kibana import failed:", result.get("message", result), file=sys.stderr)
    raise SystemExit(1)
for error in result.get("errors", []):
    detail = error.get("error", {})
    print("FAILED {} {}: {}".format(error.get("type"), error.get("id"), detail.get("type")), file=sys.stderr)
print("Imported saved objects:", result.get("successCount", 0))
print("Import success:", result.get("success"))
raise SystemExit(0 if result.get("success") else 1)
'

echo "Open Analytics -> Dashboards -> Jenkins + Kubernetes - Real-time Operations."
