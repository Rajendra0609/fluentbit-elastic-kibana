# home-lab-logging

Fluent Bit, Elasticsearch and Kibana logging stack for a Kubernetes home lab. This single document contains every file in the project. To recreate the project, create each file at the path shown in its heading, paste in the contents, make the `.sh` files executable (`chmod +x deploy.sh 01-create-secrets.sh`), and run `./deploy.sh`.

## Contents

- [`README.md`](#readmemd)
- [`deploy.sh`](#deploysh)
- [`01-create-secrets.sh`](#01-create-secretssh)
- [`kustomization.yaml`](#kustomizationyaml)
- [`00-namespace.yaml`](#00-namespaceyaml)
- [`10-elasticsearch.yaml`](#10-elasticsearchyaml)
- [`20-es-setup-job.yaml`](#20-es-setup-jobyaml)
- [`30-kibana.yaml`](#30-kibanayaml)
- [`40-fluent-bit-rbac.yaml`](#40-fluent-bit-rbacyaml)
- [`41-fluent-bit-config.yaml`](#41-fluent-bit-configyaml)
- [`42-fluent-bit-daemonset.yaml`](#42-fluent-bit-daemonsetyaml)
- [`50-log-generator.yaml`](#50-log-generatoryaml)
- [`monitoring/prometheus-fluent-bit.yaml`](#monitoringprometheus-fluent-bityaml)

---

## `README.md`

````markdown
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
- A default StorageClass that can provision volumes. See **Storage and kernel setup** below.
- `openssl` and `curl` on the machine you run the commands from.
- **`vm.max_map_count` on every node.** Elasticsearch needs `262144`. Set it on each node, because the pod can be scheduled anywhere: `sudo sysctl -w vm.max_map_count=262144`, and persist it with `echo "vm.max_map_count=262144" | sudo tee /etc/sysctl.d/99-elasticsearch.conf`.

## Storage and kernel setup

Do these once, before `deploy.sh`.

### 1. Check for a default StorageClass

```bash
kubectl get storageclass
```

Look for `(default)` after one of the names. k3s includes `local-path` as the default. kubeadm and kind clusters usually have none, and Elasticsearch's volume claim then stays `Pending` forever.

If no class is marked `(default)`, install the local-path provisioner and make it the default. Replace `<LATEST_TAG>` with the newest release tag listed at `github.com/rancher/local-path-provisioner/releases`:

```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/<LATEST_TAG>/deploy/local-path-storage.yaml
kubectl patch storageclass local-path -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
kubectl get storageclass     # local-path should now show (default)
```

A claim created before a default existed keeps an empty StorageClass, so it stays `Pending` even after you install one. If that happened, delete the pod and claim, and the StatefulSet recreates them:

```bash
kubectl -n logging delete pod elasticsearch-0 --ignore-not-found
kubectl -n logging delete pvc data-elasticsearch-0 --ignore-not-found
kubectl -n logging get pvc data-elasticsearch-0 -o jsonpath='{.spec.storageClassName}'; echo   # should print local-path
```

### 2. Set the kernel parameter on every node

Elasticsearch refuses to start unless `vm.max_map_count` is at least `262144`. Set it on each node, because the pod can be scheduled on any of them. Run this on every node:

```bash
sudo sysctl -w vm.max_map_count=262144
echo "vm.max_map_count=262144" | sudo tee /etc/sysctl.d/99-elasticsearch.conf
sysctl vm.max_map_count     # must print 262144
```

The `/etc/sysctl.d` file makes the setting survive a reboot.

### 3. Confirm the nodes are ready

```bash
kubectl get nodes     # every node should be Ready
```

---

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
| `elasticsearch-0` is `Init:Error` | An old spec still has the `sysctl` init container | `kubectl -n logging get statefulset elasticsearch -o jsonpath='{.spec.template.spec.initContainers[*].name}'`. It should print nothing. If it prints `sysctl`, copy the updated `10-elasticsearch.yaml` and re-apply |
| `es-setup` logs `Failed to connect to elasticsearch...` | Elasticsearch is not running yet. The job retries, so this is harmless until the job fails | `kubectl -n logging get pods`. Fix the Elasticsearch pod first |
| Fluent Bit cannot reach Elasticsearch | Wrong `Host` in the output config | `grep -n Host 41-fluent-bit-config.yaml`. It must be `elasticsearch.logging.svc.cluster.local`. Then `kubectl -n logging rollout restart daemonset/fluent-bit` |
| `elasticsearch-0` crashes with "max virtual memory areas" | `vm.max_map_count` too low on that node | Run `sysctl vm.max_map_count` on every node (see Prerequisites) |
| `elasticsearch-0` is `Pending` | No default StorageClass, or the claim was created before one existed | `kubectl get storageclass` shows `(default)`? If not, see **Storage and kernel setup** |
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
````

---

## `deploy.sh`

````bash
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
````

---

## `01-create-secrets.sh`

````bash
#!/usr/bin/env bash
# Generates all credentials for the logging stack and stores them in one Secret.
#
# Passwords are random and never written to Git. The script is idempotent: if the
# Secret already exists it does nothing, because Elasticsearch reads ELASTIC_PASSWORD
# only on first start. Regenerating it would desynchronise the stored data.
#
# To rotate later, change the password through the Elasticsearch security API and
# update this Secret to match. Do not just delete and recreate the Secret.
set -euo pipefail

cd "$(dirname "$0")"

NS=logging
SECRET=logging-credentials

kubectl apply -f 00-namespace.yaml >/dev/null

if kubectl -n "$NS" get secret "$SECRET" >/dev/null 2>&1; then
  echo "Secret $SECRET already exists in namespace $NS. Nothing to do."
  exit 0
fi

# Passwords use hex only so they are safe inside the JSON bodies the setup Job sends.
hex() { openssl rand -hex "$1"; }

kubectl -n "$NS" create secret generic "$SECRET" \
  --from-literal=ELASTIC_PASSWORD="$(hex 24)" \
  --from-literal=KIBANA_SYSTEM_PASSWORD="$(hex 24)" \
  --from-literal=FLUENT_BIT_PASSWORD="$(hex 24)" \
  --from-literal=KIBANA_SECURITY_KEY="$(hex 32)" \
  --from-literal=KIBANA_SAVED_OBJECTS_KEY="$(hex 32)" \
  --from-literal=KIBANA_REPORTING_KEY="$(hex 32)"

echo "Created Secret $SECRET in namespace $NS."
echo "Read the elastic password with:"
echo "  kubectl -n $NS get secret $SECRET -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d; echo"
````

---

## `kustomization.yaml`

````yaml
# Applies the whole logging stack with:  kubectl apply -k .
# Secrets are NOT listed here. Create them first with ./01-create-secrets.sh
# (deploy.sh does both in the right order).
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - 00-namespace.yaml
  - 10-elasticsearch.yaml
  - 20-es-setup-job.yaml
  - 30-kibana.yaml
  - 40-fluent-bit-rbac.yaml
  - 41-fluent-bit-config.yaml
  - 42-fluent-bit-daemonset.yaml
  - 50-log-generator.yaml
````

---

## `00-namespace.yaml`

````yaml
# Namespace for the logging stack.
# Fluent Bit mounts host paths (/var/log), which the "baseline" and "restricted"
# Pod Security levels forbid, so this namespace uses "privileged". Keep log
# collection isolated in this namespace and do not run application workloads here.
apiVersion: v1
kind: Namespace
metadata:
  name: logging
  labels:
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/audit: privileged
    pod-security.kubernetes.io/warn: privileged
````

---

## `10-elasticsearch.yaml`

````yaml
# Elasticsearch 8.x, single node, security enabled.
#
# Lab trade-offs (see README "Production differences"):
#   - single-node discovery, so no cluster formation and replicas = 0
#   - HTTP TLS off inside the cluster; authentication is still on
#   - one PersistentVolume for data
#
# vm.max_map_count must be set on EVERY node beforehand (see README). It is a host
# kernel setting, and some runtimes refuse to let a pod change it.
apiVersion: v1
kind: Service
metadata:
  name: elasticsearch-headless
  namespace: logging
  labels:
    app.kubernetes.io/name: elasticsearch
spec:
  clusterIP: None
  publishNotReadyAddresses: true
  selector:
    app.kubernetes.io/name: elasticsearch
  ports:
    - name: http
      port: 9200
      targetPort: 9200
    - name: transport
      port: 9300
      targetPort: 9300
---
# Stable DNS name used by Kibana, Fluent Bit and the setup Job:
#   elasticsearch.logging.svc.cluster.local:9200
apiVersion: v1
kind: Service
metadata:
  name: elasticsearch
  namespace: logging
  labels:
    app.kubernetes.io/name: elasticsearch
spec:
  selector:
    app.kubernetes.io/name: elasticsearch
  ports:
    - name: http
      port: 9200
      targetPort: 9200
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: elasticsearch
  namespace: logging
  labels:
    app.kubernetes.io/name: elasticsearch
spec:
  serviceName: elasticsearch-headless
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: elasticsearch
  template:
    metadata:
      labels:
        app.kubernetes.io/name: elasticsearch
    spec:
      securityContext:
        runAsUser: 1000
        runAsGroup: 0
        runAsNonRoot: true
        fsGroup: 1000
      containers:
        - name: elasticsearch
          image: docker.elastic.co/elasticsearch/elasticsearch:8.15.3
          ports:
            - name: http
              containerPort: 9200
            - name: transport
              containerPort: 9300
          env:
            - name: cluster.name
              value: home-lab
            - name: node.name
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: discovery.type
              value: single-node
            - name: ES_JAVA_OPTS
              value: "-Xms1g -Xmx1g"          # JVM heap: about half of the memory limit
            - name: xpack.security.enabled
              value: "true"
            - name: xpack.security.http.ssl.enabled
              value: "false"                  # lab only; enable in production
            - name: xpack.security.transport.ssl.enabled
              value: "false"                  # not needed for a single node
            - name: ELASTIC_PASSWORD          # bootstrap password for the "elastic" superuser
              valueFrom:
                secretKeyRef:
                  name: logging-credentials
                  key: ELASTIC_PASSWORD
          resources:
            requests:
              cpu: 500m
              memory: 1536Mi
            limits:
              cpu: "2"
              memory: 2Gi
          # Use TCP probes. HTTP probes get 401 Unauthorized once security is on,
          # and the kubelet treats that as a failure.
          readinessProbe:
            tcpSocket:
              port: 9200
            initialDelaySeconds: 30
            periodSeconds: 10
          livenessProbe:
            tcpSocket:
              port: 9200
            initialDelaySeconds: 120
            periodSeconds: 20
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: data
              mountPath: /usr/share/elasticsearch/data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        # No storageClassName, so the cluster default is used. On k3s this is local-path.
        resources:
          requests:
            storage: 10Gi
````

---

## `20-es-setup-job.yaml`

````yaml
# One-time bootstrap for Elasticsearch security and retention.
#
# This Job does what a production team normally does with Terraform or an Ansible
# playbook. It:
#   1. sets the kibana_system password Kibana logs in with
#   2. creates a least-privilege role and user for Fluent Bit (write to k8s-logs-* only)
#   3. creates an ILM policy that deletes indices after 7 days
#   4. creates an index template that applies the policy to every k8s-logs-* index
#
# The Job is idempotent, so re-running it is safe. To re-run it, delete it first:
#   kubectl -n logging delete job es-setup
apiVersion: v1
kind: ConfigMap
metadata:
  name: es-setup-script
  namespace: logging
data:
  setup.sh: |
    #!/bin/sh
    set -eu

    ES="http://elasticsearch.logging.svc.cluster.local:9200"
    AUTH="elastic:${ELASTIC_PASSWORD}"

    # api METHOD PATH [JSON_BODY]  -> prints response, fails on HTTP >= 400
    api() {
      method="$1"; path="$2"; body="${3:-}"
      # "|| return 1" is essential. Without it the function returns the status of
      # the final echo, which is always 0, so the wait loop below never waits.
      if [ -n "$body" ]; then
        curl -fsS -u "$AUTH" -H 'Content-Type: application/json' -X "$method" "$ES$path" -d "$body" || return 1
      else
        curl -fsS -u "$AUTH" -X "$method" "$ES$path" || return 1
      fi
      echo
    }

    echo "==> waiting for Elasticsearch"
    until api GET "/_cluster/health?wait_for_status=yellow&timeout=10s" >/dev/null 2>&1; do
      sleep 5
    done
    echo "==> Elasticsearch is reachable"

    echo "==> setting kibana_system password"
    api POST "/_security/user/kibana_system/_password" \
      "{\"password\":\"${KIBANA_SYSTEM_PASSWORD}\"}" >/dev/null

    echo "==> creating role fluent-bit-writer (write access to k8s-logs-* only)"
    api PUT "/_security/role/fluent-bit-writer" '{
      "cluster": ["monitor"],
      "indices": [{
        "names": ["k8s-logs-*"],
        "privileges": ["create_index", "create", "write", "auto_configure"]
      }]
    }' >/dev/null

    echo "==> creating user fluent-bit"
    api PUT "/_security/user/fluent-bit" \
      "{\"password\":\"${FLUENT_BIT_PASSWORD}\",\"roles\":[\"fluent-bit-writer\"],\"full_name\":\"Fluent Bit log collector\"}" >/dev/null

    echo "==> creating ILM policy k8s-logs-retention (delete after 7 days)"
    api PUT "/_ilm/policy/k8s-logs-retention" '{
      "policy": {"phases": {"delete": {"min_age": "7d", "actions": {"delete": {}}}}}
    }' >/dev/null

    echo "==> creating index template for k8s-logs-*"
    api PUT "/_index_template/k8s-logs" '{
      "index_patterns": ["k8s-logs-*"],
      "priority": 100,
      "template": {
        "settings": {
          "number_of_shards": 1,
          "number_of_replicas": 0,
          "refresh_interval": "1s",
          "index.lifecycle.name": "k8s-logs-retention"
        }
      }
    }' >/dev/null

    echo "==> setup complete"
---
apiVersion: batch/v1
kind: Job
metadata:
  name: es-setup
  namespace: logging
spec:
  # Retries until Elasticsearch is ready, so ordering between manifests does not matter.
  backoffLimit: 30
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: setup
          image: curlimages/curl:8.10.1
          command: ["/bin/sh", "/scripts/setup.sh"]
          env:
            - name: ELASTIC_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: logging-credentials
                  key: ELASTIC_PASSWORD
            - name: KIBANA_SYSTEM_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: logging-credentials
                  key: KIBANA_SYSTEM_PASSWORD
            - name: FLUENT_BIT_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: logging-credentials
                  key: FLUENT_BIT_PASSWORD
          volumeMounts:
            - name: script
              mountPath: /scripts
              readOnly: true
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
      volumes:
        - name: script
          configMap:
            name: es-setup-script
            defaultMode: 0755
````

---

## `30-kibana.yaml`

````yaml
# Kibana: the web UI for searching and visualising logs.
# Connects to Elasticsearch as the built-in kibana_system user, never as "elastic".
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kibana
  namespace: logging
  labels:
    app.kubernetes.io/name: kibana
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: kibana
  template:
    metadata:
      labels:
        app.kubernetes.io/name: kibana
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
        - name: kibana
          image: docker.elastic.co/kibana/kibana:8.15.3
          ports:
            - name: http
              containerPort: 5601
          env:
            - name: ELASTICSEARCH_HOSTS
              value: "http://elasticsearch:9200"
            - name: ELASTICSEARCH_USERNAME
              value: kibana_system
            - name: ELASTICSEARCH_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: logging-credentials
                  key: KIBANA_SYSTEM_PASSWORD
            # Encryption keys protect saved objects and reports. They must be at least
            # 32 characters and must stay stable, or saved objects become unreadable.
            - name: XPACK_SECURITY_ENCRYPTIONKEY
              valueFrom:
                secretKeyRef:
                  name: logging-credentials
                  key: KIBANA_SECURITY_KEY
            - name: XPACK_ENCRYPTEDSAVEDOBJECTS_ENCRYPTIONKEY
              valueFrom:
                secretKeyRef:
                  name: logging-credentials
                  key: KIBANA_SAVED_OBJECTS_KEY
            - name: XPACK_REPORTING_ENCRYPTIONKEY
              valueFrom:
                secretKeyRef:
                  name: logging-credentials
                  key: KIBANA_REPORTING_KEY
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: "1"
              memory: 1Gi
          readinessProbe:
            httpGet:
              path: /api/status
              port: 5601
            initialDelaySeconds: 60
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /api/status
              port: 5601
            initialDelaySeconds: 120
            periodSeconds: 30
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
---
# NodePort for a home lab: open http://<node-ip>:30601.
# In production, use an Ingress with TLS and single sign-on instead.
apiVersion: v1
kind: Service
metadata:
  name: kibana
  namespace: logging
  labels:
    app.kubernetes.io/name: kibana
spec:
  type: NodePort
  selector:
    app.kubernetes.io/name: kibana
  ports:
    - name: http
      port: 5601
      targetPort: 5601
      nodePort: 30601
````

---

## `40-fluent-bit-rbac.yaml`

````yaml
# Fluent Bit's kubernetes filter calls the API server to attach pod metadata
# (namespace, pod name, labels) to every log line. It needs read-only access.
apiVersion: v1
kind: ServiceAccount
metadata:
  name: fluent-bit
  namespace: logging
  labels:
    app.kubernetes.io/name: fluent-bit
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: fluent-bit
  labels:
    app.kubernetes.io/name: fluent-bit
rules:
  - apiGroups: [""]
    resources: ["pods", "namespaces"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: fluent-bit
  labels:
    app.kubernetes.io/name: fluent-bit
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: fluent-bit
subjects:
  - kind: ServiceAccount
    name: fluent-bit
    namespace: logging
````

---

## `41-fluent-bit-config.yaml`

````yaml
# Fluent Bit pipeline:  INPUT (tail) -> FILTER (kubernetes, modify) -> OUTPUT (es)
#
# Every stage is annotated. Fluent Bit reads this file on startup, so after a change
# run:  kubectl -n logging rollout restart daemonset/fluent-bit
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
  namespace: logging
  labels:
    app.kubernetes.io/name: fluent-bit
data:
  fluent-bit.conf: |
    [SERVICE]
        # Flush buffered records to the output every 5 seconds. Lower this for
        # faster near-real-time updates at the cost of more, smaller requests.
        Flush                       5
        Log_Level                   info
        Parsers_File                parsers.conf
        # Built-in HTTP server: /api/v1/health and /api/v1/metrics/prometheus
        HTTP_Server                 On
        HTTP_Listen                 0.0.0.0
        HTTP_Port                   2020
        Health_Check                On
        # Filesystem buffering. If Elasticsearch is down, Fluent Bit keeps the logs
        # on disk and resends them when it recovers, instead of dropping them.
        storage.path                /var/lib/fluent-bit/storage
        storage.sync                normal
        storage.checksum            off
        storage.backlog.mem_limit   16M

    # ---------------------------------------------------------------------------
    # INPUT: read every container log file on this node.
    # Kubernetes writes each container's stdout/stderr to
    # /var/log/containers/<pod>_<namespace>_<container>-<id>.log, a symlink into
    # /var/log/pods. The /var/log mount in the DaemonSet covers both.
    # ---------------------------------------------------------------------------
    [INPUT]
        Name              tail
        Tag               kube.*
        Path              /var/log/containers/*.log
        # Do not collect Fluent Bit's own logs. Otherwise it reads what it writes,
        # which creates a feedback loop.
        Exclude_Path      /var/log/containers/*_logging_fluent-bit-*.log
        # Understand container-runtime log formats (containerd CRI and Docker JSON).
        multiline.parser  docker, cri
        # Position database: remembers the byte offset in each file, so a restart
        # does not re-send or skip lines.
        DB                /var/lib/fluent-bit/tail.db
        DB.sync           normal
        Mem_Buf_Limit     50MB
        Skip_Long_Lines   On
        Refresh_Interval  5
        storage.type      filesystem

    # ---------------------------------------------------------------------------
    # FILTER: add Kubernetes metadata (namespace, pod, container, labels).
    # Merge_Log On parses JSON application logs, so their fields (level, msg, ...)
    # become top-level fields you can search on directly.
    # ---------------------------------------------------------------------------
    [FILTER]
        Name                 kubernetes
        Match                kube.*
        Kube_URL             https://kubernetes.default.svc:443
        Kube_CA_File         /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        Kube_Token_File      /var/run/secrets/kubernetes.io/serviceaccount/token
        Kube_Tag_Prefix      kube.var.log.containers.
        Merge_Log            On
        Merge_Log_Key        log_processed
        Keep_Log             Off
        K8S-Logging.Parser   On
        K8S-Logging.Exclude  Off
        Labels               On
        Annotations          Off

    # Stamp every record with the cluster it came from. This matters once you have
    # more than one cluster sending to the same Elasticsearch.
    [FILTER]
        Name    modify
        Match   kube.*
        Add     cluster   home-lab
        Add     environment   lab

    # ---------------------------------------------------------------------------
    # OUTPUT: send to Elasticsearch as daily indices, k8s-logs-YYYY.MM.DD.
    # Replace_Dots and Suppress_Type_Name are needed for Elasticsearch 8.x, which
    # rejects field names containing dots and typed bulk actions.
    # ---------------------------------------------------------------------------
    [OUTPUT]
        Name                 es
        Match                kube.*
        Host                 elasticsearch.logging.svc.cluster.local
        Port                 9200
        HTTP_User            ${FLUENT_BIT_ES_USER}
        HTTP_Passwd          ${FLUENT_BIT_ES_PASSWORD}
        tls                  Off
        Logstash_Format      On
        Logstash_Prefix      k8s-logs
        Logstash_DateFormat  %Y.%m.%d
        Time_Key             @timestamp
        Suppress_Type_Name   On
        Replace_Dots         On
        Retry_Limit          5
        Trace_Error          On
        # Cap the on-disk buffer for this output. If it fills up, the oldest chunks
        # are dropped first, which protects the node's disk.
        storage.total_limit_size  1G

  parsers.conf: |
    # Custom parsers go here. Nothing uses this one yet. To apply it to a
    # plain-text application, add a [FILTER] with Name parser, a Match pattern
    # for that application's tag, Key_Name log, and Parser app_plain.
    [PARSER]
        Name         app_plain
        Format       regex
        Regex        ^(?<time>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z) (?<level>\w+) (?<message>.*)$
        Time_Key     time
        Time_Format  %Y-%m-%dT%H:%M:%S.%LZ
````

---

## `42-fluent-bit-daemonset.yaml`

````yaml
# Fluent Bit runs as a DaemonSet, so exactly one agent runs on every node and reads
# that node's container logs. This is the standard pattern for node-level collection.
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit
  namespace: logging
  labels:
    app.kubernetes.io/name: fluent-bit
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: fluent-bit
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
  template:
    metadata:
      labels:
        app.kubernetes.io/name: fluent-bit
      annotations:
        # Changes to the config trigger a rolling restart when the ConfigMap is re-applied.
        checksum/config-hash: "fluent-bit-config-v1"
    spec:
      serviceAccountName: fluent-bit
      # Collect logs from control-plane nodes too. Single-node labs have only that node.
      tolerations:
        - key: node-role.kubernetes.io/control-plane
          operator: Exists
          effect: NoSchedule
        - key: node-role.kubernetes.io/master
          operator: Exists
          effect: NoSchedule
      # Must run as root to read /var/log/pods, which is root-owned.
      securityContext:
        runAsUser: 0
      containers:
        - name: fluent-bit
          image: fluent/fluent-bit:3.1.9
          imagePullPolicy: IfNotPresent
          ports:
            - name: http-metrics
              containerPort: 2020
          env:
            - name: FLUENT_BIT_ES_USER
              value: fluent-bit
            - name: FLUENT_BIT_ES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: logging-credentials
                  key: FLUENT_BIT_PASSWORD
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          livenessProbe:
            httpGet:
              path: /api/v1/health
              port: 2020
            initialDelaySeconds: 10
            periodSeconds: 30
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: varlog
              mountPath: /var/log
              readOnly: true
            - name: config
              mountPath: /fluent-bit/etc/
              readOnly: true
            - name: state
              mountPath: /var/lib/fluent-bit
      volumes:
        - name: varlog
          hostPath:
            path: /var/log
        - name: config
          configMap:
            name: fluent-bit-config
        # Position database and disk buffer. They live on the host, so a pod restart
        # resumes where it stopped and does not lose buffered logs.
        - name: state
          hostPath:
            path: /var/lib/fluent-bit
            type: DirectoryOrCreate
````

---

## `50-log-generator.yaml`

````yaml
# A test workload that writes one JSON log line per second. Use it to watch logs
# arrive in Kibana in real time. It runs in its own namespace so you can filter it.
apiVersion: v1
kind: Namespace
metadata:
  name: demo
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: log-generator
  namespace: demo
  labels:
    app: log-generator
spec:
  replicas: 2
  selector:
    matchLabels:
      app: log-generator
  template:
    metadata:
      labels:
        app: log-generator
        team: platform
    spec:
      containers:
        - name: generator
          image: busybox:1.36
          command:
            - sh
            - -c
            - |
              i=0
              while true; do
                i=$((i+1))
                case $((i % 10)) in
                  0) lvl=error ;;
                  3) lvl=warn ;;
                  *) lvl=info ;;
                esac
                echo "{\"level\":\"$lvl\",\"msg\":\"order processed\",\"order_id\":$i,\"pod\":\"$HOSTNAME\"}"
                sleep 1
              done
          resources:
            requests:
              cpu: 10m
              memory: 16Mi
            limits:
              cpu: 50m
              memory: 32Mi
````

---

## `monitoring/prometheus-fluent-bit.yaml`

````yaml
# Monitoring integration for the EXISTING Prometheus in your prod-observability repo.
# This is not part of the logging kustomization. Copy the pieces below into:
#   - scrape_configs in argocd/apps/20-configmap.yaml   (prometheus.yml)
#   - a new group in argocd/apps/20-alert-rules-configmap.yaml   (alerts.yml)
#
# Fluent Bit exposes its own pipeline metrics on port 2020:
#   fluentbit_input_records_total   lines read from container logs
#   fluentbit_output_proc_records_total   records accepted by Elasticsearch
#   fluentbit_output_errors_total   failed sends (this is what the alert watches)
---
# 1) scrape job (prometheus.yml)
- job_name: fluent-bit
  metrics_path: /api/v1/metrics/prometheus
  kubernetes_sd_configs:
    - role: pod
  relabel_configs:
    - source_labels: [__meta_kubernetes_namespace]
      action: keep
      regex: logging
    - source_labels: [__meta_kubernetes_pod_label_app_kubernetes_io_name]
      action: keep
      regex: fluent-bit
    - source_labels: [__meta_kubernetes_pod_container_port_name]
      action: keep
      regex: http-metrics
---
# 2) alert rule group (alerts.yml). Logs silently lost is serious, so this is critical
#    and therefore also goes to email, through your existing critical-notifications receiver.
groups:
  - name: logging-alerts
    rules:
      - alert: FluentBitOutputErrors
        expr: sum by (instance) (rate(fluentbit_output_errors_total[5m])) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Fluent Bit cannot deliver logs to Elasticsearch on {{ $labels.instance }}"
          description: "Fluent Bit is failing to send logs to Elasticsearch. Check the fluent-bit and elasticsearch pods. Buffered logs on disk will be resent when delivery recovers."
````
