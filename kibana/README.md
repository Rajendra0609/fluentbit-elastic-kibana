# Kibana dashboards and alerts for the pod logs

This folder adds five dashboards, three live-feed searches, and four alert rules on top of
the `k8s-logs-*` indices that Fluentd writes. Everything is generated from code, so you can
change it and re-install in one step.

| File | Purpose |
|---|---|
| `build_dashboards.py` | Generates the saved objects. Edit thresholds, panels, and queries here |
| `dashboards.ndjson` | The generated objects: data view, searches, 48 visualizations, 5 dashboards |
| `import-dashboards.sh` | Imports `dashboards.ndjson` into Kibana through the saved objects API |
| `create-alerts.py` | Creates four Elasticsearch query alert rules through the alerting API |

## Install

**1. Apply the field mappings.** The dashboards aggregate on `kubernetes.namespace_name`, `kubernetes.pod_name`,
`kubernetes.container_name`, `kubernetes.host`, `level`, and `stream`. They must be `keyword` fields, and
`20-es-setup-job.yaml` now maps them that way. Re-run the setup job (`./deploy.sh` does this).

The index template applies only to indices created after it changes. Fluentd writes one index per day,
so the mapping takes effect at the next daily index. To apply it to today's index now, delete it.
This also deletes today's logs:

```bash
kubectl -n logging port-forward svc/elasticsearch 9200:9200 &
PW=$(kubectl -n logging get secret logging-credentials -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d)
curl -s -u elastic:$PW -X DELETE "localhost:9200/k8s-logs-$(date +%Y.%m.%d)"
```

**2. Import the dashboards.** Open a tunnel to Kibana, then run the import:

```bash
kubectl -n logging port-forward svc/kibana 5601:5601 &
cd kibana
./import-dashboards.sh
```

The script reads the Elastic password from the cluster. It prints `success: True` when every object
imports. Re-running is safe: objects are overwritten, not duplicated.

**3. Create the alert rules:**

```bash
python3 create-alerts.py
```

**Making the scripts executable.** If you get "Permission denied", run `chmod +x import-dashboards.sh create-alerts.py`
once, or use `bash import-dashboards.sh` and `python3 create-alerts.py`.

## The dashboards

Open them in Kibana under **Analytics → Dashboards**, and search for "K8s Logs".

**1. K8s Logs: Cluster Overview** (last 24 hours). Start here. Six headline numbers (lines, errors, warnings,
active pods, namespaces, nodes), volume by namespace, the errors-and-warnings trend, a namespace table, a
node table, a container table, and a live feed of problems. A sudden change in the volume chart shows a
noisy deployment or an outage.

**2. K8s Logs: Errors and Warnings** (last 24 hours). The triage view. Errors and warnings over time, split by
namespace. The pods that produce the most errors and warnings. The most frequent error messages, which is
usually the fastest way to find a bug. Errors grouped by namespace and container, and a live feed.

**3. K8s Logs: Pod and Container Drill-down** (last hour, refreshes every 30 seconds). Type a query in the bar at
the top, and every panel follows it. Examples:

```text
kubernetes.namespace_name : "demo"
kubernetes.namespace_name : "demo" and kubernetes.pod_name : log-generator*
kubernetes.container_name : "generator" and level : (error or warn)
stream : "stderr"
```

**4. K8s Logs: Pipeline Health and Freshness** (last 6 hours). Checks that logging itself works.
- *Ingest rate* shows lines per minute. A drop to zero means the pipeline or every source has stopped.
- *Last seen per namespace* and *Last seen per pod* show the newest log for each source. A source whose
  newest line is much older than now has gone silent, even if the others are fine.
- *Documents per index* confirms the daily indices and the 7-day retention.

**5. K8s Logs: Logging Stack Self-Monitoring** (last 24 hours). Monitors Elasticsearch, Kibana, and anything
else in the `logging` namespace. Fluentd is not listed, because its own logs are excluded to avoid a feedback
loop. Its health comes from the Prometheus metrics and alert in `monitoring/prometheus-fluentd.yaml`.

## The alert rules

Each rule runs every minute over a short window. When its condition is met, it writes a line to the Kibana
server log.

| Rule | Fires when | Default |
|---|---|---|
| `K8s logs: error spike` | error lines in 5 minutes | more than 50 |
| `K8s logs: warning spike` | warning lines in 10 minutes | more than 200 |
| `K8s logs: no logs ingested` | log lines in 10 minutes | fewer than 1 |
| `Logging stack: errors` | error lines in the `logging` namespace, in 5 minutes | more than 0 |

Read the fired alerts in the Kibana server log:

```bash
kubectl -n logging logs deploy/kibana | grep "Elasticsearch query rule"
```

The default thresholds are starting points. Set them from your own baseline, which the Overview dashboard
shows. To tune a rule, edit `RULES` in `create-alerts.py` and run the script again. It deletes and recreates
each rule.

To send alerts to email or Slack, create the connector in **Stack Management → Connectors**, then add it to
the rule's actions. The Server log connector is only a visible, zero-setup destination.

## Limitations

- **Visualizations use the Aggregation-based editor.** Kibana 9.x still supports this format and it is stable
  to write by hand. Elastic recommends Lens for new work. Open any panel in edit mode, and Kibana offers to
  convert it to Lens. Rebuilding the panels in Lens is a sensible next step.
- **The dashboards were generated, not exported from a running Kibana.** The generator checks that every
  object is well-formed and that every reference resolves. It has not been imported into a live Kibana in this
  project. If a panel shows an error after import, open it in edit mode, read the message, and fix the setting
  in `build_dashboards.py`.
- **Message search and counts use `msg.keyword`.** That field holds the first 256 characters of a message, so
  "most frequent error messages" groups on that prefix. Messages longer than that are counted only by their prefix.
- **Log level values vary between libraries.** The queries cover the common spellings (`error`, `ERROR`,
  `fatal`, `warn`, `warning`, and so on). If an application uses another name, add it to `ERROR_Q` or
  `WARN_Q` in `build_dashboards.py`.
- **Elasticsearch node health is not covered.** Heap, disk, and shard status belong to Kibana Stack Monitoring,
  which needs monitoring collection enabled. That is a separate setup.
