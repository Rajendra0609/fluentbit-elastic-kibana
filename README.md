# Home-lab logging stack: Fluent Bit, Elasticsearch, Kibana

A working log pipeline on Kubernetes. Fluent Bit collects every container's logs
on each node, Elasticsearch stores and indexes them, and Kibana searches them in near
real time. It is built the way a production team would build it, but sized for a
single home-lab node.

```
  every node                     logging namespace                       you
 ┌──────────────────────┐      ┌────────────────────────────────┐     ┌────────────┐
 │ app pods ──▶ stdout  │      │  Elasticsearch  (StatefulSet)  │     │            │
 │   /var/log/containers│      │   k8s-logs-YYYY.MM.DD indices  │◀────│  Kibana    │◀── browser
 │          │           │      │   ILM: delete after 7 days     │     │ (Deployment│    :30601
 │   Fluent Bit         │─────▶│                                │     │   :5601)   │
 │   (DaemonSet)        │ HTTP │  es-setup Job (one-time)       │     └────────────┘
 │   tail → kubernetes  │ +auth│   users, roles, ILM, template  │
 │   → modify → es      │      └────────────────────────────────┘
 └──────────────────────┘
```

## What each file does

| File | Kind | Purpose |
|---|---|---|
| `00-namespace.yaml` | Namespace | `logging` namespace (privileged, because Fluent Bit reads host logs) |
| `01-create-secrets.sh` | script | Generates random passwords and encryption keys into one Secret. Never commit them |
| `10-elasticsearch.yaml` | StatefulSet, Services | Single-node Elasticsearch 8.15.3 with security on and a 10 Gi volume |
| `20-es-setup-job.yaml` | ConfigMap, Job | Sets up the Kibana user, the Fluent Bit user and role, retention, and the index template |
| `30-kibana.yaml` | Deployment, Service | Kibana 8.15.3 as the `kibana_system` user, exposed on NodePort 30601 |
| `40-fluent-bit-rbac.yaml` | SA, ClusterRole, Binding | Read-only access to pods and namespaces, for metadata enrichment |
| `41-fluent-bit-config.yaml` | ConfigMap | The Fluent Bit pipeline: input, filters, output. Heavily commented |
| `42-fluent-bit-daemonset.yaml` | DaemonSet | One Fluent Bit agent per node |
| `50-log-generator.yaml` | Namespace, Deployment | Test app that writes JSON logs every second, so you can watch them arrive |
| `monitoring/prometheus-fluent-bit.yaml` | snippet | Scrape job and alert for your existing Prometheus. Not applied by kustomize |
| `kustomization.yaml` | Kustomization | Lists everything to apply |
| `deploy.sh` | script | Runs everything in order and waits for each step |

## Prerequisites

- A Kubernetes cluster (k3s, kubeadm, or kind all work) with `kubectl` access.
- About **4 GB of free RAM** on the node: Elasticsearch takes up to 2 GB, Kibana 1 GB, and Fluent Bit 512 MB.
- A default StorageClass. On k3s this is `local-path`. Check with `kubectl get storageclass`.
- `openssl` and `curl` on the machine you run the commands from.
- Node sysctl: the Elasticsearch init container sets `vm.max_map_count` automatically. If your nodes forbid privileged init containers, set it on the host instead: `sudo sysctl -w vm.max_map_count=262144`.

## Changes you might need

Nothing needs editing for a typical home lab. Only change these in the cases below.

**Slow hardware.** `deploy.sh` waits up to 10 minutes for Elasticsearch, the setup job,
and Kibana, and 5 minutes for Fluent Bit. On slow hardware, increase the `--timeout`
values in `deploy.sh`.

**Non-default cluster DNS domain.** The manifests assume `svc.cluster.local`. If your
cluster uses a different domain, update the hostname in these two places:
- `41-fluent-bit-config.yaml`: `Host elasticsearch.logging.svc.cluster.local`
- `20-es-setup-job.yaml`: the `ES=` URL in the setup script

Kibana uses the short name `elasticsearch`, so it needs no change.

**Elasticsearch heap or memory.** Change these together in `10-elasticsearch.yaml`:
- `ES_JAVA_OPTS`: set `-Xms` and `-Xmx` to the same value.
- `resources.limits.memory`: keep it at about twice the heap. For a 2 GB heap, use `4Gi`.
- `resources.requests.memory`: keep it at or below the limit.

Raising the heap without raising the memory limit gets the pod OOM-killed.

**Elasticsearch volume size.** The `10Gi` in `volumeClaimTemplates` applies only when
the volume is first created. Changing it later does nothing to an existing install.
Growing an existing volume requires a StorageClass that allows expansion, and
`local-path` usually doesn't. For a fresh install, change the value before running
`deploy.sh`.

**Optional Prometheus integration.** The snippet in `monitoring/` is not needed for the
logging stack to work. Edit your `prod-observability` repo only if you want Fluent Bit
metrics and the delivery alert in Alertmanager.

---

## Deploy

```bash
cd home-lab-logging
./deploy.sh
```

This takes 3–6 minutes on first run. Elasticsearch and Kibana start slowly. Kibana may
restart a few times while it waits for `es-setup` to finish, and that is expected.

To deploy step by step instead:

```bash
./01-create-secrets.sh
kubectl apply -k .
kubectl -n logging get pods -w          # wait for elasticsearch-0, kibana, fluent-bit-*
kubectl -n logging logs job/es-setup    # should end with "setup complete"
```

## Get the password

```bash
kubectl -n logging get secret logging-credentials -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d; echo
```

## Verify each layer, from the bottom up

**1. Elasticsearch is up and secured**

```bash
kubectl -n logging port-forward svc/elasticsearch 9200:9200 &
PW=$(kubectl -n logging get secret logging-credentials -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d)
curl -s -u elastic:$PW localhost:9200/_cluster/health?pretty
# "status" should be "green". Single-node clusters run with replicas=0, so green is correct.
curl -s -u elastic:$PW localhost:9200/_cat/indices?v
```

Without the password, the same request returns `401`. That confirms security is on.

**2. The setup job created its objects**

```bash
curl -s -u elastic:$PW localhost:9200/_security/role/fluent-bit-writer?pretty
curl -s -u elastic:$PW localhost:9200/_ilm/policy/k8s-logs-retention?pretty
curl -s -u elastic:$PW localhost:9200/_index_template/k8s-logs?pretty
```

**3. Fluent Bit is reading logs and sending them**

```bash
FB=$(kubectl -n logging get pod -l app.kubernetes.io/name=fluent-bit -o name | head -1)
kubectl -n logging port-forward "$FB" 2020:2020 &
curl -s localhost:2020/api/v1/health                 # prints "ok"
curl -s localhost:2020/api/v1/metrics/prometheus | grep -E "fluentbit_(input_records|output_proc_records|output_errors)_total"
```

`fluentbit_input_records_total` should go up. `fluentbit_output_errors_total` should stay at 0.

**4. Logs are in Elasticsearch**

```bash
curl -s -u elastic:$PW "localhost:9200/k8s-logs-*/_search?size=2&pretty" | head -60
```

**5. Kibana**

1. Open `http://<node-ip>:30601` and log in as `elastic` with the password above.
2. Go to **Stack Management → Data Views → Create data view**. Set the name and index pattern to `k8s-logs-*`, and the timestamp field to `@timestamp`. Save.
3. Go to **Analytics → Discover**. Select the `k8s-logs-*` data view.
4. Set the time picker to **Last 15 minutes**, then click the refresh control and set it to **Refresh every 5 seconds**. New log lines now appear without reloading the page. That is the real-time view.

## Things to try in Discover

Kibana Query Language (KQL) examples:

```text
kubernetes.namespace_name : "demo"
kubernetes.pod_name : log-generator*
level : "error"
level : ("error" or "warn") and kubernetes.namespace_name : "demo"
kubernetes.labels.team : "platform"
```

Fields come from the Kubernetes filter (`kubernetes.*`), and from the JSON the app wrote
(`level`, `msg`, `order_id`), because `Merge_Log On` promotes them to top-level fields.

To see errors appear in real time, watch `level : error` while the generator runs. It writes an error every tenth line.

## Learn by breaking it

These exercises teach the most. Each one shows a failure mode you will meet in production.

1. **Stop Elasticsearch, then watch buffering.** Run `kubectl -n logging scale sts/elasticsearch --replicas=0`. Wait 2 minutes, then check `fluentbit_output_retries_total` and the buffer files under `/var/lib/fluent-bit/storage` on the node. Scale back to 1. The logs should arrive with no gap. That is what filesystem buffering is for.
2. **Read the position database.** Look at `/var/lib/fluent-bit/tail.db` on the node. Then delete the Fluent Bit pod. When it restarts, it resumes at the same offset, so nothing is duplicated or skipped.
3. **Change the retention.** Edit the ILM `min_age` (for example to `1d`) with `PUT _ilm/policy/k8s-logs-retention`. Note that existing indices keep the policy they had when created, unless you update them.
4. **Break authentication on purpose.** Change the `fluent-bit` password through the security API, and watch `fluentbit_output_errors_total` climb. This is the alert in `monitoring/prometheus-fluent-bit.yaml` firing.

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| `elasticsearch-0` crashes with "max virtual memory areas" | `vm.max_map_count` too low | `sysctl vm.max_map_count`, and the init container's logs |
| `elasticsearch-0` is `Pending` | No default StorageClass, or the PVC can't bind | `kubectl -n logging get pvc`, `kubectl get storageclass` |
| Kibana logs "Unable to authenticate user kibana_system" | The setup job has not run yet, or the job failed | `kubectl -n logging logs job/es-setup` |
| `es-setup` keeps restarting | Elasticsearch not ready yet, which is normal for the first few minutes | `kubectl -n logging logs job/es-setup --tail=20` |
| Fluent Bit logs `401` from Elasticsearch | Wrong `fluent-bit` password, or the role is missing | Compare the secret with the `fluent-bit` user in the security API |
| Fluent Bit logs `mapper_parsing_exception` | A field type conflict, such as the same field sent as string and number | Check the index mapping, and the `Replace_Dots` setting |
| No logs in Discover but indices exist | Wrong time range, or the data view does not match `k8s-logs-*` | Widen the time range and check `_cat/indices` |
| Kibana shows "Please configure encryption key" | Encryption keys missing from the secret | `kubectl -n logging get secret logging-credentials -o yaml` |

General approach: check the **source** first (Fluent Bit metrics), then the **transport**
(its output errors), then the **sink** (Elasticsearch health), then the **view** (Kibana).

## Re-running the setup job

The Job is one-shot. To apply changes to Elasticsearch security or retention:

```bash
kubectl -n logging delete job es-setup
kubectl apply -k .
```

## Production differences

This lab uses several shortcuts. Here is what real production does instead.

| Lab | Production |
|---|---|
| 1 Elasticsearch node | At least 3 nodes, with dedicated master, data, and ingest roles |
| `replicas: 0` | `replicas: 1` at minimum, so losing a node loses no data |
| TLS off inside the cluster | TLS on HTTP and transport, with certificates from cert-manager |
| Plain-text passwords in a generated Secret | Sealed Secrets, External Secrets, or Vault, with rotation |
| Daily indices with a delete-after-7-days ILM | Rollover aliases with hot, warm, and cold tiers, plus snapshots to S3 or MinIO |
| Kibana on NodePort | Kibana behind an Ingress with TLS and single sign-on |
| Fluent Bit config as a ConfigMap | Helm chart or Fluent Operator, with a parser per application |
| No network policies | Default-deny NetworkPolicies, with explicit allows for Fluent Bit → ES → Kibana |
| Manual setup Job | Terraform or an ECK / Elastic Operator manifest |

**If you want to go further,** install the **Elastic Cloud on Kubernetes (ECK)**
operator. It is how most companies run Elasticsearch on Kubernetes today. It manages
TLS, upgrades, and scaling for you. Once this lab makes sense, that is the logical next step.

## Connect to your existing Prometheus

1. Copy the `fluent-bit` scrape job from `monitoring/prometheus-fluent-bit.yaml` into
   `argocd/apps/20-configmap.yaml`.
2. Copy the `logging-alerts` group into `argocd/apps/20-alert-rules-configmap.yaml`.
3. Sync with ArgoCD, then reload Prometheus: `curl -X POST http://localhost:9090/-/reload`.

Now a Fluent Bit delivery failure goes to Alertmanager, then to Slack and email. That is the same
path your pod alerts use.

## Cleanup

```bash
kubectl delete -k .
kubectl delete namespace demo
kubectl delete clusterrole fluent-bit
kubectl delete clusterrolebinding fluent-bit
# To also remove stored data, delete the PVC:
kubectl -n logging delete pvc data-elasticsearch-0
```
