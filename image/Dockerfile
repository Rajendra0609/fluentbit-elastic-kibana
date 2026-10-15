# Fluentd 1.19.4 with the plugins the logging stack needs.
#
# The official fluent/fluentd image contains only the core plugins, so this image adds:
#   fluent-plugin-elasticsearch               sends logs to Elasticsearch 9.x (5.x uses the ES 9 client)
#   fluent-plugin-kubernetes_metadata_filter  adds pod, namespace and label metadata
#   fluent-plugin-prometheus                  exposes Fluentd metrics on port 24231
#
# Build with image/build.sh. The gem versions are pinned, so rebuilding gives the same image.
FROM fluent/fluentd:v1.19-debian

USER root

# Some dependencies compile small C extensions when installed. The kubernetes metadata
# plugin pulls in llhttp-ffi, which is one of them. The base image has no compiler, so the
# build fails with "gcc: not found" (exit status 127). Install the toolchain for the gem
# build and remove it in the same layer, so the final image stays small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && gem install fluent-plugin-elasticsearch -v 5.3.0 --no-document \
 && gem install fluent-plugin-kubernetes_metadata_filter -v 3.7.1 --no-document \
 && gem install fluent-plugin-prometheus -v 1.8.0 --no-document \
 && apt-get purge -y --auto-remove build-essential \
 && rm -rf /var/lib/apt/lists/* /root/.gem

# Run fluentd directly. The DaemonSet runs this container as root, which it needs to
# read host logs. The config is mounted at /fluentd/etc by 42-fluentd-daemonset.yaml.
ENTRYPOINT ["fluentd"]
CMD ["-c", "/fluentd/etc/fluent.conf"]