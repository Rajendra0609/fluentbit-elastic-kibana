# Home-lab logging stack: Fluentd, Elasticsearch, Kibana

A working log pipeline on Kubernetes. Fluentd collects every container's logs on each
node, Elasticsearch 9.5.5 stores and indexes them, and Kibana 9.5.5 searches them in near
real time. It is built the way a production team would build it, but sized for a
single home-lab node.

```
  every node                     logging namespace                       you
 ┌──────────────────────┐      ┌────────────────────────────────┐     ┌────────────┐
 │ app pods ──▶ stdout  │      │  Elasticsearch  (StatefulSet)  │     │            │
 │   /var/log/containers│      │   k8s-logs-YYYY.MM.DD indices  │◀────│  Kibana    │◀── browser
 │          │           │      │   ILM: delete after 7 days     │     │ (Deployment│    :30601
 │   Fluentd            │─────▶│                                │     │   :5601)   │
 │   (DaemonSet)        │ HTTP │  es-setup Job (one-time)       │     └────────────┘
 │   tail → kubernetes  │ +auth│   users, roles, ILM, template  │
 │   → record → es      │      └────────────────────────────────┘
 └──────────────────────┘
```

## What changed from the Fluent Bit version

| Part | Before | Now |
|---|---|---|
| Log collector | Fluent Bit 3.1.9 (DaemonSet, public image) | Fluentd 1.19.4 (DaemonSet, image built from `image/`) |
| Elasticsearch | 8.15.3 | 9.5.5 |
| Kibana | 8.15.3 | 9.5.5 |
| Collector's Elasticsearch user | `fluent-bit`, role `fluent-bit-writer` | `fluentd`, role `fluentd-writer` |
| Secret key for that password | `FLUENT_BIT_PASSWORD` | `FLUENTD_PASSWORD` |
| Metrics endpoint | port 2020, `/api/v1/metrics/prometheus` | port 24231, `/metrics` |
| Retry behaviour | `Retry_Limit 5`, then the chunk is discarded | Retries until the disk buffer is full, oldest chunks dropped first |
| Collector memory limit | 512 Mi | 768 Mi |

**Retry behaviour changed on purpose.** The Fluent Bit config said logs wait on disk while
Elasticsearch is down, but `Retry_Limit 5` discarded a chunk after five failed attempts. A
long outage would therefore lose logs. The Fluentd config retries until the disk buffer
fills, which matches what the old comments promised.

**Known differences:**
- **Partial lines.** The container runtime splits lines longer than 16 KB into partial
  records. Fluent Bit joined them again. This Fluentd config does not, so a very long line
  arrives as several records. If you need them joined, add `fluent-plugin-concat` and a
  `concat` filter.
- **Plain-text lines** stay in the `log` field. JSON lines are promoted to top-level fields.
- **Image build.** Fluentd needs an image you build yourself (step 0 below). The official
  DaemonSet images ship an Elasticsearch 8 plugin, and this stack needs the Elasticsearch 9 one.

## What each file does

| File | Kind | Purpose |
|---|---|---|
| `00-namespace.yaml` | Namespace | `logging` namespace (privileged, because Fluentd reads host logs) |
| `01-create-secrets.sh` | script | Generates random passwords and encryption keys into one Secret. Never commit them |
| `10-elasticsearch.yaml` | StatefulSet, Services | Single-node Elasticsearch 9.5.5 with security on and a 10 Gi volume |
| `20-es-setup-job.yaml` | ConfigMap, Job | Sets up the Kibana user, the Fluentd user and role, retention, and the index template |
| `30-kibana.yaml` | Deployment, Service | Kibana 9.5.5 as the `kibana_system` user, exposed on NodePort 30601 |
| `40-fluentd-rbac.yaml` | SA, ClusterRole, Binding | Read-only access to pods and namespaces, for metadata enrichment |
| `41-fluentd-config.yaml` | ConfigMap | The Fluentd pipeline: source, filters, output, metrics. Heavily commented |
| `42-fluentd-daemonset.yaml` | DaemonSet | One Fluentd agent per node, running the image from `image/` |
| `50-log-generator.yaml` | Namespace, Deployment | Test app that writes JSON logs every second, so you can watch them arrive |
| `image/Dockerfile` | Dockerfile | Official Fluentd 1.19.4 plus the Elasticsearch, Kubernetes metadata and Prometheus plugins |
| `image/build.sh` | script | Builds the image, then imports it into k3s or pushes it to a registry |
| `kibana/` | scripts, generated objects | Five Kibana dashboards, live-feed searches, and four alert rules. See `kibana/README.md` |
| `monitoring/prometheus-fluentd.yaml` | snippet | Scrape job and alert for your existing Prometheus. Not applied by kustomize |
| `kustomization.yaml` | Kustomization | Lists everything to apply, and pins the Fluentd image tag |
| `deploy.sh` | script | Runs everything in order and waits for each step |

## Prerequisites

- A Kubernetes cluster (k3s, kubeadm, or kind all work) with `kubectl` access.
- About **4.5 GB of free RAM** on the node: Elasticsearch takes up to 2 GB, Kibana 1 GB, and Fluentd 768 MB.
- Docker on the machine that builds the Fluentd image (step 0).
- A default StorageClass. On k3s this is `local-path`. Check with `kubectl get storageclass`.
- `openssl` and `curl` on the machine you run the commands from.
- **`vm.max_map_count` on every node.** Elasticsearch needs `262144`. Set it on each node, because the pod can be scheduled anywhere: `sudo sysctl -w vm.max_map_count=262144`, and persist it with `echo "vm.max_map_count=262144" | sudo tee /etc/sysctl.d/99-elasticsearch.conf`.

## Changes you might need

Nothing needs editing for a typical home lab. Only change these in the cases below.

**Slow hardware.** `deploy.sh` waits up to 10 minutes for Elasticsearch, the setup job,
and Kibana, and 5 minutes for Fluentd. On slow hardware, increase the `--timeout`
values in `deploy.sh`.

**Non-default cluster DNS domain.** The manifests assume `svc.cluster.local`. If your
cluster uses a different domain, update the hostname in these two places:
- `41-fluentd-config.yaml`: `host elasticsearch.logging.svc.cluster.local`
- `20-es-setup-job.yaml`: the `ES=` URL in the setup script

Kibana uses the short name `elasticsearch`, so it needs no change.

**Elasticsearch heap or memory.** Change these together in `10-elasticsearch.yaml`:
- `ES_JAVA_OPTS`: set `-Xms` and `-Xmx` to the same value.
- `resources.limits.memory`: keep it at about twice the heap. For a 2 GB heap, use `4Gi`.
- `resources.requests.memory`: keep it at or below the limit.

Raising the heap without raising the memory limit gets the pod OOM-killed.

**Fluentd memory.** If the `fluentd` pods are OOMKilled under heavy log volume, raise
`resources.limits.memory` in `42-fluentd-daemonset.yaml`.

**Elasticsearch volume size.** The `10Gi` in `volumeClaimTemplates` applies only when
the volume is first created. Changing it later does nothing to an existing install.
Growing an existing volume requires a StorageClass that allows expansion, and
`local-path` usually doesn't. For a fresh install, change the value before running
`deploy.sh`.

**Optional Prometheus integration.** The snippet in `monitoring/` is not needed for the
logging stack to work. Edit your `prod-observability` repo only if you want Fluentd
metrics and the delivery alert in Alertmanager.

---

## Upgrading from the Fluent Bit version

This is a required procedure. It is not optional, because of two version constraints:

- **Elasticsearch 9.x cannot open 8.x data.** Elastic's supported path from 8.x to 9.x goes
  through 8.19.x, which is a multi-step in-place upgrade. For a home lab the simpler route
  is a fresh data volume. Logs are kept for 7 days anyway, so this loses only that window.
  Kibana saved objects, including the `k8s-logs-*` data view, are stored in Elasticsearch
  and go with the volume. You will recreate the data view once (see step 5).
- **Two collectors would ship every log twice.** Remove Fluent Bit before Fluentd starts.

Run these once, in order:

```bash
# 1. Remove the Fluent Bit collector and its RBAC, so logs are not shipped twice.
kubectl -n logging delete daemonset fluent-bit --ignore-not-found
kubectl -n logging delete configmap fluent-bit-config --ignore-not-found
kubectl delete clusterrolebinding fluent-bit --ignore-not-found
kubectl delete clusterrole fluent-bit --ignore-not-found
kubectl -n logging delete serviceaccount fluent-bit --ignore-not-found
# Optional, on each node: sudo rm -rf /var/lib/fluent-bit
# Logs still in the old Fluent Bit disk buffer are discarded with that directory.

# 2. Remove the Elasticsearch 8.x data volume.
kubectl -n logging delete statefulset elasticsearch --ignore-not-found
kubectl -n logging delete pvc data-elasticsearch-0 --ignore-not-found

# 3. Build the Fluentd image (step 0 below), then deploy.
cd image && ./build.sh && cd ..
./deploy.sh
```

Keep the `logging-credentials` Secret. Its `ELASTIC_PASSWORD` is the bootstrap password for
the new cluster, so the `elastic` password does not change. `01-create-secrets.sh` detects
that the Secret lacks `FLUENTD_PASSWORD` and adds only that key. The old `FLUENT_BIT_PASSWORD`
key is unused and can be removed:

```bash
kubectl -n logging patch secret logging-credentials --type json \
  -p='[{"op":"remove","path":"/data/FLUENT_BIT_PASSWORD"}]'
```

`kubectl apply -k .` does not delete objects that have been removed from the manifests, which
is why step 1 removes the Fluent Bit objects by name.

---

## Deploy

### Step 0: build the Fluentd image

```bash
cd image
./build.sh
cd ..
```

On k3s, `build.sh` imports the image into the node's container runtime, so the DaemonSet
can start it without a registry. On a multi-node cluster, do one of these:
- Push to a registry: `REGISTRY=registry.example.com/lab ./build.sh`, then set `newName` in
  `kustomization.yaml` to `registry.example.com/lab/fluentd-logging`.
- Or import the image on every node.

### Steps 1 to 5

```bash
cd home-lab-logging
./deploy.sh
```

Some download tools drop the executable bit. If you get "Permission denied", run
`chmod +x deploy.sh 01-create-secrets.sh image/build.sh` once, or run the scripts with `bash`.

This takes 3–6 minutes on first run. Elasticsearch and Kibana start slowly. Kibana may
restart a few times while it waits for `es-setup` to finish, and that is expected.

To deploy step by step instead:

```bash
./01-create-secrets.sh
kubectl -n logging delete job es-setup --ignore-not-found
kubectl apply -k .
kubectl -n logging get pods -w          # wait for elasticsearch-0, kibana, fluentd-*
kubectl -n logging logs job/es-setup    # should end with "setup complete"
```

## Get the password

```bash
kubectl -n logging get secret logging-credentials -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d; echo
```

## Verify each layer, from the bottom up

**1. Elasticsearch is up, secured, and on 9.5.5**

```bash
kubectl -n logging port-forward svc/elasticsearch 9200:9200 &
PW=$(kubectl -n logging get secret logging-credentials -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d)
curl -s -u elastic:$PW localhost:9200/ | grep '"number"'     # should print "number" : "9.5.5"
curl -s -u elastic:$PW localhost:9200/_cluster/health?pretty
# "status" should be "green". Single-node clusters run with replicas=0, so green is correct.
curl -s -u elastic:$PW localhost:9200/_cat/indices?v
```

Without the password, the same request returns `401`. That confirms security is on.

**2. The setup job created its objects**

```bash
curl -s -u elastic:$PW localhost:9200/_security/role/fluentd-writer?pretty
curl -s -u elastic:$PW localhost:9200/_ilm/policy/k8s-logs-retention?pretty
curl -s -u elastic:$PW localhost:9200/_index_template/k8s-logs?pretty
```

**3. Fluentd is reading logs and sending them**

```bash
FD=$(kubectl -n logging get pod -l app.kubernetes.io/name=fluentd -o name | head -1)
kubectl -n logging port-forward "$FD" 24231:24231 &
curl -s localhost:24231/metrics | grep -E "^fluentd_output_status_(emit_records|num_errors|retry_count)"
kubectl -n logging logs "$FD" --tail=20
```

`fluentd_output_status_emit_records` should go up. `fluentd_output_status_num_errors` should
stay at 0. The pod logs should contain no repeated errors.

**4. Logs are in Elasticsearch**

```bash
curl -s -u elastic:$PW "localhost:9200/k8s-logs-*/_search?size=2&pretty" | head -60
```

**5. Kibana**

1. Open `http://<node-ip>:30601` and log in as `elastic` with the password above.
2. Go to **Stack Management → Data Views → Create data view**. Set the name and index pattern
   to `k8s-logs-*`, and the timestamp field to `@timestamp`. Save. Menu names can shift
   between Kibana versions; the Data Views page is under Stack Management.
3. Go to **Analytics → Discover**. Select the `k8s-logs-*` data view.
4. Set the time picker to **Last 15 minutes**, then click the refresh control and set it to
   **Refresh every 5 seconds**. New log lines now appear without reloading the page.

## Things to try in Discover

Kibana Query Language (KQL) examples:

```text
kubernetes.namespace_name : "demo"
kubernetes.pod_name : log-generator*
level : "error"
level : ("error" or "warn") and kubernetes.namespace_name : "demo"
kubernetes.labels.team : "platform"
```

Fields come from the Kubernetes metadata filter (`kubernetes.*`), and from the JSON the app
wrote (`level`, `msg`, `order_id`), because `merge_json_log true` promotes them to top-level
fields. Plain-text lines keep their text in `log`.

To see errors appear in real time, watch `level : error` while the generator runs. It writes
an error every tenth line.

## Learn by breaking it

These exercises teach the most. Each one shows a failure mode you will meet in production.

1. **Stop Elasticsearch, then watch buffering.** Run `kubectl -n logging scale sts/elasticsearch --replicas=0`.
   Wait 2 minutes, then check `fluentd_output_status_retry_count` and
   `fluentd_output_status_buffer_queue_length` on the metrics port, and the buffer files under
   `/var/lib/fluentd/buffer/es` on the node. Scale back to 1. The logs should arrive with no
   gap. That is what the disk buffer is for.
2. **Read the position file.** Look at `/var/lib/fluentd/containers.log.pos` on the node. Then
   delete the Fluentd pod. When it restarts, it resumes at the same offset, so nothing is
   duplicated or skipped.
3. **Change the retention.** Edit the ILM `min_age` (for example to `1d`) with
   `PUT _ilm/policy/k8s-logs-retention`. Note that existing indices keep the policy they had when
   created, unless you update them.
4. **Break authentication on purpose.** Change the `fluentd` password through the security API, and
   watch `fluentd_output_status_num_errors` climb. This is the alert in `monitoring/prometheus-fluentd.yaml`
   firing.

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| `elasticsearch-0` refuses to start with a version or upgrade error | The 8.x data volume was kept | Delete the PVC as described in "Upgrading from the Fluent Bit version" |
| `elasticsearch-0` crashes with "max virtual memory areas" | `vm.max_map_count` too low on that node | Run `sysctl vm.max_map_count` on every node (see Prerequisites) |
| `elasticsearch-0` is `Pending` | No default StorageClass, or the PVC can't bind | `kubectl -n logging get pvc`, `kubectl get storageclass` |
| `fluentd-*` pods are `ErrImagePull` or `ImagePullBackOff` | The image was not built, or not present on that node | Run `image/build.sh` on every node, or push to a registry and set `newName` |
| Kibana logs "Unable to authenticate user kibana_system" | The setup job has not run yet, or it failed | `kubectl -n logging logs job/es-setup` |
| `es-setup` keeps restarting | Elasticsearch not ready yet, which is normal for the first few minutes | `kubectl -n logging logs job/es-setup --tail=20` |
| Fluentd logs `401` from Elasticsearch | Wrong `fluentd` password, or the role is missing | Compare the secret with the `fluentd` user in the security API, then re-run the setup job |
| Fluentd logs `mapper_parsing_exception` | A field type conflict, such as the same field sent as string and number | `log_es_400_reason` prints the reason in the pod logs. Check the index mapping |
| Fluentd logs `403` or "forbidden" on the Kubernetes API | The ClusterRole is missing or not bound | `kubectl auth can-i list pods --as=system:serviceaccount:logging:fluentd` |
| `fluentd-*` pods are OOMKilled | Memory limit too low for the log volume | Raise `resources.limits.memory` in `42-fluentd-daemonset.yaml` |
| No logs in Discover but indices exist | Wrong time range, or the data view does not match `k8s-logs-*` | Widen the time range and check `_cat/indices` |
| Kibana shows "Please configure encryption key" | Encryption keys missing from the secret | `kubectl -n logging get secret logging-credentials -o yaml` |
| Kibana and Elasticsearch show a version mismatch | The two images are on different versions | Both must be `9.5.5` in `10-elasticsearch.yaml` and `30-kibana.yaml` |

General approach: check the **source** first (Fluentd metrics), then the **transport**
(its output errors), then the **sink** (Elasticsearch health), then the **view** (Kibana).

## Re-running the setup job

`deploy.sh` re-runs the setup job on every deploy, because a Job's pod template cannot be
changed in place. To run it by hand:

```bash
kubectl -n logging delete job es-setup --ignore-not-found
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
| Fluentd config as a ConfigMap, image built by hand | Helm chart or Fluentd Operator, with a parser per application, and a CI-built image |
| No network policies | Default-deny NetworkPolicies, with explicit allows for Fluentd → ES → Kibana |
| Manual setup Job | Terraform or an ECK / Elastic Operator manifest |

**If you want to go further,** install the **Elastic Cloud on Kubernetes (ECK)**
operator. It is how most companies run Elasticsearch on Kubernetes today. It manages
TLS, upgrades, and scaling for you. Once this lab makes sense, that is the logical next step.

## Connect to your existing Prometheus

1. Copy the `fluentd` scrape job from `monitoring/prometheus-fluentd.yaml` into
   `argocd/apps/20-configmap.yaml`.
2. Copy the `logging-alerts` group into `argocd/apps/20-alert-rules-configmap.yaml`.
3. Sync with ArgoCD, then reload Prometheus: `curl -X POST http://localhost:9090/-/reload`.

Now a Fluentd delivery failure goes to Alertmanager, then to Slack and email. That is the same
path your pod alerts use.

## Dashboards and alerts

Once the stack is running, import the monitoring views and alert rules. Details are in `kibana/README.md`:

```bash
kubectl -n logging port-forward svc/kibana 5601:5601 &
cd kibana
./import-dashboards.sh        # five dashboards: overview, errors, pod drill-down, pipeline health, logging stack
python3 create-alerts.py      # error spike, warning spike, no logs ingested, logging-stack errors
```

The index template now maps the dashboard fields as keyword. It applies from the next daily index, so
the dashboards are most useful once a fresh index has been created.

## Cleanup

```bash
kubectl delete -k .
kubectl delete namespace demo
kubectl delete clusterrole fluentd
kubectl delete clusterrolebinding fluentd
# To also remove stored data, delete the PVC:
kubectl -n logging delete pvc data-elasticsearch-0
```
