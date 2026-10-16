# Jenkins + Kubernetes real-time dashboard

This package is separate from the existing log-only dashboards. It creates:

- `jenkins-kubernetes-dashboard.json`: readable JSON bundle of the saved objects.
- `jenkins-kubernetes.ndjson`: the Kibana import file generated from the same objects.
- `deploy/telemetry.yaml`: kube-state-metrics, Metricbeat, and an OTLP trace collector.

The dashboard refreshes every 15 seconds. Metricbeat scrapes kubelet and the Jenkins
Prometheus endpoint every 10-15 seconds. Kubernetes events are watched through the
Kubernetes API. Jenkins spans are received over OTLP and indexed as `traces-jenkins`.
The two Jenkins log panels query the existing Fluentd `k8s-logs-*` data view.

## Data and Jenkins plugins

Before deploying:

1. Install and configure the Jenkins **Prometheus** plugin. Its default metrics endpoint
   is `/prometheus/` (keep the trailing slash). The default metric namespace is
   `default_jenkins`; the dashboard uses the plugin's standard executor, queue, agent,
   and build metric names. If you change the plugin's metric namespace, update the
   `prometheus.metrics.default_jenkins_*` field names in `build_dashboard.py`.
2. Install and configure the Jenkins **OpenTelemetry** plugin to send traces to
   `jenkins-otel-collector.logging.svc.cluster.local:4317` using OTLP/gRPC. Set the
   service name to `jenkins`. Pipeline spans require the plugin's supported Pipeline
   instrumentation; installing a receiver alone does not create spans.
3. Ensure controller and agent container logs are already collected into `k8s-logs-*`.
   The default namespace is `jenkins`, and the agent log search assumes container names
   `jnlp` or `agent`. Change `JENKINS_NAMESPACE` when generating/importing the
   dashboard, and edit the agent search if your container names differ.
4. Edit `deploy/telemetry.yaml` if the Elasticsearch service URL or Jenkins service
   endpoint differs from the provided defaults:
   - Elasticsearch: `http://elasticsearch.logging.svc.cluster.local:9200`
   - Jenkins metrics: `http://jenkins.jenkins.svc.cluster.local:8080/prometheus/`

The Metricbeat node module uses the kubelet's HTTPS endpoint and disables certificate
verification for kubelet only, to support common self-signed kubelet certificates.
For production, configure the trusted kubelet CA in `node-modules.yml` instead.
Metricbeat and kube-state-metrics use read-only Kubernetes API permissions.

## Deploy

Run from Bash, Git Bash, or WSL with access to the target cluster. The `logging` and
`kube-system` namespaces, Elasticsearch service, and Kibana must already exist. The
deploy script creates/updates a namespace-scoped Elasticsearch credential Secret,
applies the telemetry resources, waits for collector readiness, and imports the
dashboard:

```bash
export ELASTIC_PASSWORD='your Elasticsearch password'
export ELASTIC_USERNAME='elastic'
export KIBANA_URL='http://localhost:5601'
export JENKINS_NAMESPACE='jenkins'
bash deploy.sh
```

Open Kibana at **Analytics -> Dashboards -> Jenkins + Kubernetes - Real-time Operations**.
To import the dashboard without deploying collectors, run `bash import-dashboard.sh`.

## Dashboard sections

- **Kubernetes infrastructure:** node CPU/memory/readiness; pod and container CPU,
  memory, and restarts; kube-state-metrics pod phases and deployments; recent Kubernetes
  API events.
- **Jenkins:** health/uptime, executor and queue gauges, agent online/connecting
  signals, successful/failed/unstable/total build counters, build and stage duration
  samples, and OTLP build spans.
- **Logs:** Kubernetes controller/system logs plus Jenkins controller and agent log
  tables from the existing Kubernetes log stream.

Panels that depend on a plugin, endpoint, or log source remain empty until that source is
configured. Jenkins build counters are cumulative values, not per-minute rates. “Agent
connecting” is the Jenkins executor gauge, not a cloud-provider provisioning duration.
Kubernetes CPU and memory values are sampled observations; this package does not add
alert thresholds or replace production alerting.
