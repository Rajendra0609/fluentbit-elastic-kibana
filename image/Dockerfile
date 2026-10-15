# Fluentd 1.19.4 with the plugins the logging stack needs.
#
# The official fluent/fluentd image contains only the core plugins, so this image adds:
#   fluent-plugin-elasticsearch               sends logs to Elasticsearch 9.x (5.x uses the ES 9 client)
#   fluent-plugin-kubernetes_metadata_filter  adds pod, namespace and label metadata
#   fluent-plugin-prometheus                  exposes Fluentd metrics on port 24231
#
# Build with image/build.sh. The gem versions are pinned, so rebuilding gives the same image.
FROM fluent/fluentd:v1.19.4-debian-1.0

USER root

RUN gem install fluent-plugin-elasticsearch -v 5.3.0 --no-document \
 && gem install fluent-plugin-kubernetes_metadata_filter -v 3.7.1 --no-document \
 && gem install fluent-plugin-prometheus -v 1.8.0 --no-document

# Run fluentd directly. The DaemonSet runs this container as root, which it needs to
# read host logs. The config is mounted at /fluentd/etc by 42-fluentd-daemonset.yaml.
ENTRYPOINT ["fluentd"]
CMD ["-c", "/fluentd/etc/fluent.conf"]
