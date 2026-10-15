#!/usr/bin/env bash
# Deploys the logging stack in the right order and waits until each part is ready.
# Build the Fluentd image first (README, step 0: image/build.sh).
set -euo pipefail
cd "$(dirname "$0")"

echo "1/5 credentials"
./01-create-secrets.sh

echo "2/5 applying manifests"
# A Job's pod template cannot be changed in place, so delete the old setup Job first.
# Re-running the setup is safe: every step is an idempotent PUT or POST.
kubectl -n logging delete job es-setup --ignore-not-found --wait=true
kubectl apply -k .

echo "3/5 waiting for Elasticsearch"
kubectl -n logging rollout status statefulset/elasticsearch --timeout=600s

echo "4/5 waiting for the security/retention setup job"
kubectl -n logging wait --for=condition=complete job/es-setup --timeout=600s

echo "5/5 waiting for Kibana and Fluentd"
kubectl -n logging rollout status deployment/kibana --timeout=600s
kubectl -n logging rollout status daemonset/fluentd --timeout=300s

echo
echo "Done. Kibana: http://<node-ip>:30601   user: elastic"
echo "Password: kubectl -n logging get secret logging-credentials -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d; echo"
