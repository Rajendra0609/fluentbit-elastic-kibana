#!/usr/bin/env bash
# Apply the telemetry collectors, wait for readiness, then import the dashboard.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${ELASTIC_PASSWORD:-}" ]; then
  echo "Set ELASTIC_PASSWORD to the Elasticsearch password before deploying." >&2
  exit 1
fi

command -v kubectl >/dev/null 2>&1 || {
  echo "kubectl is required to deploy telemetry collectors." >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to create the Kubernetes credential Secret." >&2
  exit 1
}

ELASTIC_USERNAME="${ELASTIC_USERNAME:-elastic}"
export ELASTIC_PASSWORD ELASTIC_USERNAME

python3 -c 'import base64, os; enc=lambda key: base64.b64encode(os.environ[key].encode()).decode(); print("apiVersion: v1\nkind: Secret\nmetadata:\n  name: jenkins-k8s-telemetry\n  namespace: logging\ntype: Opaque\ndata:\n  ELASTICSEARCH_USERNAME: " + enc("ELASTIC_USERNAME") + "\n  ELASTICSEARCH_PASSWORD: " + enc("ELASTIC_PASSWORD"))' \
  | kubectl apply -f -

kubectl apply -f "$SCRIPT_DIR/deploy/telemetry.yaml"

kubectl -n kube-system rollout status deployment/kube-state-metrics --timeout=180s
kubectl -n logging rollout status daemonset/jenkins-k8s-node-metricbeat --timeout=180s
kubectl -n logging rollout status deployment/jenkins-k8s-cluster-metricbeat --timeout=180s
kubectl -n logging rollout status deployment/jenkins-otel-collector --timeout=180s

bash "$SCRIPT_DIR/import-dashboard.sh"

echo
echo "Telemetry collection is deployed. Check Metricbeat and OTel Collector pod logs if panels are empty."
