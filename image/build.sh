#!/usr/bin/env bash
# Builds the Fluentd image used by ../42-fluentd-daemonset.yaml.
#
#   ./build.sh                                      build, then import into k3s on this node
#   REGISTRY=registry.example.com/lab ./build.sh    build and push to a registry instead
#
# With a registry, also set newName in ../kustomization.yaml to "$REGISTRY/fluentd-logging".
# Without one, the image must be present in the container runtime of every node that runs Fluentd.
set -euo pipefail
cd "$(dirname "$0")"

TAG="fluentd-logging:1.19.4"
docker build -t "$TAG" .

if [ -n "${REGISTRY:-}" ]; then
  docker tag "$TAG" "$REGISTRY/$TAG"
  docker push "$REGISTRY/$TAG"
  echo "Pushed $REGISTRY/$TAG"
elif command -v k3s >/dev/null 2>&1; then
  tar_file="$(mktemp -t fluentd-logging.XXXXXX.tar)"
  trap 'rm -f "$tar_file"' EXIT
  docker save -o "$tar_file" "$TAG"
  sudo k3s ctr images import "$tar_file"
  echo "Imported $TAG into k3s on this node. Repeat on every other node."
else
  echo "Built $TAG. No REGISTRY set and no k3s found: make sure every node can pull this image."
fi
