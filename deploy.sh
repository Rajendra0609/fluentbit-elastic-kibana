#!/usr/bin/env bash
# Deploys the logging stack in the right order and waits until each part is ready.
set -euo pipefail
cd "$(dirname "$0")"

echo "1/5 credentials"
./01-create-secrets.sh

echo "2/5 applying manifests"
kubectl apply -k .

echo "3/5 waiting for Elasticsearch"
kubectl -n logging rollout status statefulset/elasticsearch --timeout=600s

echo "4/5 waiting for the security/retention setup job"
kubectl -n logging wait --for=condition=complete job/es-setup --timeout=600s

echo "5/5 waiting for Kibana and Fluent Bit"
kubectl -n logging rollout status deployment/kibana --timeout=600s
kubectl -n logging rollout status daemonset/fluent-bit --timeout=300s

echo
echo "Done. Kibana: http://<node-ip>:30601   user: elastic"
echo "Password: kubectl -n logging get secret logging-credentials -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d; echo"
