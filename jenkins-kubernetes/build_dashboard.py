#!/usr/bin/env python3
"""Builds a Kibana saved-object export for Jenkins and Kubernetes telemetry."""

import json
import os
from pathlib import Path

KIBANA_VERSION = "9.5.5"
METRICBEAT_VIEW_ID = "jk-metricbeat"
TRACES_VIEW_ID = "jk-jenkins-traces"
LOGS_VIEW_ID = "k8s-logs"
INDEX_REF = "kibanaSavedObjectMeta.searchSourceJSON.index"
JENKINS_NAMESPACE = os.environ.get("JENKINS_NAMESPACE", "jenkins")

METRIC_PARAMS = {
    "addTooltip": True,
    "addLegend": False,
    "type": "metric",
    "metric": {
        "percentageMode": False,
        "useRanges": False,
        "colorSchema": "Green to Red",
        "metricColorMode": "None",
        "colorsRange": [{"from": 0, "to": 10000}],
        "labels": {"show": True},
        "invertColors": False,
        "style": {
            "bgFill": "#000",
            "bgColor": False,
            "labelColor": False,
            "subText": "",
            "fontSize": 48,
        },
    },
}

HISTOGRAM_PARAMS = {
    "type": "histogram",
    "grid": {"categoryLines": False, "valueAxis": "ValueAxis-1"},
    "categoryAxes": [{
        "id": "CategoryAxis-1",
        "type": "category",
        "position": "bottom",
        "show": True,
        "style": {},
        "scale": {"type": "linear"},
        "labels": {"show": True, "filter": True, "truncate": 100},
        "title": {},
    }],
    "valueAxes": [{
        "id": "ValueAxis-1",
        "name": "LeftAxis-1",
        "type": "value",
        "position": "left",
        "show": True,
        "style": {},
        "scale": {"type": "linear", "mode": "normal"},
        "labels": {"show": True, "rotate": 0, "filter": False, "truncate": 100},
        "title": {"text": "Value"},
    }],
    "seriesParams": [{
        "show": True,
        "type": "histogram",
        "mode": "normal",
        "data": {"label": "Value", "id": "1"},
        "valueAxis": "ValueAxis-1",
        "drawLinesBetweenPoints": True,
        "lineWidth": 2,
        "showCircles": True,
    }],
    "addTooltip": True,
    "addLegend": False,
    "legendPosition": "right",
    "times": [],
    "addTimeMarker": False,
    "labels": {"show": False},
    "thresholdLine": {"show": False, "value": 10, "width": 1, "style": "full", "color": "#E7664C"},
}


def index_view(view_id, title):
    return {
        "id": view_id,
        "type": "index-pattern",
        "attributes": {"title": title, "timeFieldName": "@timestamp"},
        "references": [],
    }


def saved_search(object_id, title, index_id, query, columns, description):
    return {
        "id": object_id,
        "type": "search",
        "attributes": {
            "title": title,
            "description": description,
            "columns": columns,
            "sort": [["@timestamp", "desc"]],
            "version": 1,
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps({
                    "query": {"query": query, "language": "kuery"},
                    "filter": [],
                    "indexRefName": INDEX_REF,
                }),
            },
        },
        "references": [{"name": INDEX_REF, "type": "index-pattern", "id": index_id}],
    }


def make_agg(agg_id, agg_type, params, schema):
    return {"id": agg_id, "enabled": True, "type": agg_type, "params": params, "schema": schema}


def saved_visualization(object_id, title, view_id, query, vis_type, aggs, params, description=""):
    return {
        "id": object_id,
        "type": "visualization",
        "attributes": {
            "title": title,
            "description": description,
            "visState": json.dumps({
                "title": title,
                "type": vis_type,
                "aggs": aggs,
                "params": params,
            }),
            "uiStateJSON": "{}",
            "version": 1,
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps({
                    "query": {"query": query, "language": "kuery"},
                    "filter": [],
                    "indexRefName": INDEX_REF,
                }),
            },
        },
        "references": [{"name": INDEX_REF, "type": "index-pattern", "id": view_id}],
    }


def metric(object_id, title, field, query, description="", operation="max"):
    aggs = [make_agg("1", operation, {"field": field}, "metric")]
    return saved_visualization(
        object_id, title, METRICBEAT_VIEW_ID, query, "metric", aggs,
        METRIC_PARAMS, description,
    )


def histogram(object_id, title, field, query, description="", operation="avg"):
    aggs = [
        make_agg("1", operation, {"field": field}, "metric"),
        make_agg("2", "date_histogram", {
            "field": "@timestamp",
            "useNormalizedEsInterval": True,
            "scaleMetricValues": False,
            "interval": "auto",
            "drop_partials": False,
            "min_doc_count": 1,
            "extended_bounds": {},
        }, "segment"),
    ]
    params = json.loads(json.dumps(HISTOGRAM_PARAMS))
    params["seriesParams"][0]["data"]["label"] = operation.title()
    return saved_visualization(
        object_id, title, METRICBEAT_VIEW_ID, query, "histogram", aggs,
        params, description,
    )


def table(object_id, title, field, query, description="", size=20):
    aggs = [
        make_agg("1", "count", {}, "metric"),
        make_agg("2", "terms", {
            "field": field,
            "orderBy": "1",
            "order": "desc",
            "size": size,
            "otherBucket": False,
            "otherBucketLabel": "Other",
            "missingBucket": False,
            "missingBucketLabel": "Missing",
        }, "bucket"),
    ]
    params = {
        "perPage": 15,
        "showPartialRows": False,
        "showMetricsAtAllLevels": False,
        "sort": {"columnIndex": None, "direction": None},
        "showTotal": False,
        "totalFunc": "sum",
        "percentageCol": "",
    }
    return saved_visualization(
        object_id, title, METRICBEAT_VIEW_ID, query, "table", aggs, params,
        description,
    )


def search_panel(object_id, title, index_id, query, columns, description):
    return {
        "id": object_id,
        "type": "search",
        "attributes": {
            "title": title,
            "description": description,
            "columns": columns,
            "sort": [["@timestamp", "desc"]],
            "version": 1,
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps({
                    "query": {"query": query, "language": "kuery"},
                    "filter": [],
                    "indexRefName": INDEX_REF,
                }),
            },
        },
        "references": [{"name": INDEX_REF, "type": "index-pattern", "id": index_id}],
    }


def dashboard(rows):
    panels = []
    references = []
    y = 0
    panel_number = 1
    for row in rows:
        if sum(width for _, width, _ in row) != 48:
            raise ValueError(f"Dashboard row must span 48 columns: {row}")
        row_height = max(height for _, _, height in row)
        x = 0
        for object_id, width, height in row:
            target = OBJECTS_BY_ID[object_id]
            ref_name = f"panel_{panel_number - 1}"
            panels.append({
                "version": KIBANA_VERSION,
                "type": target["type"],
                "gridData": {"x": x, "y": y, "w": width, "h": height, "i": str(panel_number)},
                "panelIndex": str(panel_number),
                "embeddableConfig": {},
                "panelRefName": ref_name,
            })
            references.append({
                "name": ref_name,
                "type": target["type"],
                "id": object_id,
            })
            x += width
            panel_number += 1
        y += row_height
    return {
        "id": "jenkins-kubernetes-realtime",
        "type": "dashboard",
        "attributes": {
            "title": "Jenkins + Kubernetes - Real-time Operations",
            "description": (
                "Real-time Jenkins and Kubernetes operations: kubelet and kube-state-metrics, "
                "Kubernetes events, Jenkins Prometheus metrics, OpenTelemetry build traces, and "
                f"Jenkins namespace controller/agent logs ({JENKINS_NAMESPACE}). Metrics refresh every "
                "10-15 seconds. Trace and log panels populate only after their respective sources are configured."
            ),
            "panelsJSON": json.dumps(panels),
            "optionsJSON": json.dumps({
                "useMargins": True,
                "syncColors": False,
                "syncCursor": True,
                "syncTooltips": False,
                "hidePanelTitles": False,
            }),
            "timeRestore": True,
            "timeFrom": "now-1h",
            "timeTo": "now",
            "refreshInterval": {"pause": False, "value": 15000},
            "version": 1,
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps({
                    "query": {"query": "", "language": "kuery"},
                    "filter": [],
                }),
            },
        },
        "references": references,
    }


def build():
    objects = [
        index_view(METRICBEAT_VIEW_ID, "metricbeat-*"),
        index_view(TRACES_VIEW_ID, "traces-jenkins"),
        index_view(LOGS_VIEW_ID, "k8s-logs-*"),
        saved_search(
            "jk-kubernetes-events",
            "Kubernetes events (live)",
            METRICBEAT_VIEW_ID,
            "event.module : kubernetes and metricset.name : event",
            [
                "kubernetes.event.metadata.namespace",
                "kubernetes.event.type",
                "kubernetes.event.reason",
                "kubernetes.event.involved_object.kind",
                "kubernetes.event.involved_object.name",
                "kubernetes.event.count",
                "kubernetes.event.message",
            ],
            "Recent Kubernetes API events collected by Metricbeat.",
        ),
        saved_search(
            "jk-jenkins-traces",
            "Jenkins build traces (live)",
            TRACES_VIEW_ID,
            "",
            ["resource.attributes.service.name", "trace_id", "name", "status.code", "duration"],
            "OTel spans sent by Jenkins to the included OpenTelemetry Collector.",
        ),
        search_panel(
            "jk-kubernetes-controller-logs",
            "Kubernetes controller logs (live)",
            LOGS_VIEW_ID,
            'kubernetes.namespace_name : "kube-system"',
            [
                "kubernetes.namespace_name",
                "kubernetes.pod_name",
                "kubernetes.container_name",
                "kubernetes.host",
                "level",
                "msg",
                "log",
            ],
            "Control-plane and system-controller logs, when the cluster log pipeline collects kube-system.",
        ),
        search_panel(
            "jk-jenkins-controller-logs",
            "Jenkins controller logs (live)",
            LOGS_VIEW_ID,
            f'kubernetes.namespace_name : "{JENKINS_NAMESPACE}"',
            [
                "kubernetes.namespace_name",
                "kubernetes.pod_name",
                "kubernetes.container_name",
                "level",
                "msg",
                "log",
            ],
            "Controller/application logs from the Jenkins namespace in the existing Fluentd k8s-logs-* stream.",
        ),
        search_panel(
            "jk-jenkins-agent-logs",
            "Jenkins agent logs (live)",
            LOGS_VIEW_ID,
            f'kubernetes.namespace_name : "{JENKINS_NAMESPACE}" and '
            '(kubernetes.container_name : "jnlp" or kubernetes.container_name : "agent")',
            [
                "kubernetes.namespace_name",
                "kubernetes.pod_name",
                "kubernetes.container_name",
                "level",
                "msg",
                "log",
            ],
            "Agent container logs in the Jenkins namespace. Adjust the container-name filter for your agent image.",
        ),
    ]

    kubernetes = "event.module : kubernetes"
    jenkins = "event.module : prometheus and metricset.name : collector"
    kubernetes += " and metricset.name : node"
    objects.extend([
        metric("jk-node-cpu", "Node CPU (nanocores)", "kubernetes.node.cpu.usage.nanocores",
               kubernetes, "Live kubelet CPU use.", "avg"),
        metric("jk-node-memory", "Node memory (bytes)", "kubernetes.node.memory.usage.bytes",
               kubernetes, "Live kubelet memory use.", "avg"),
        metric("jk-node-ready", "Node readiness (0-1)", "kubernetes.node.status.ready",
               "event.module : kubernetes and metricset.name : state_node",
               "Average ready status across nodes. Requires kube-state-metrics.", "avg"),
        histogram("jk-node-cpu-over-time", "Node CPU use over time",
                  "kubernetes.node.cpu.usage.nanocores", kubernetes, operation="avg"),
        histogram("jk-node-memory-over-time", "Node memory use over time",
                  "kubernetes.node.memory.usage.bytes", kubernetes, operation="avg"),
        table("jk-node-table", "Nodes by CPU use", "kubernetes.node.name", kubernetes,
              "Node inventory from kubelet observations."),
        metric("jk-pod-cpu", "Pod CPU (nanocores)", "kubernetes.pod.cpu.usage.nanocores",
               "event.module : kubernetes and metricset.name : pod", operation="avg"),
        metric("jk-pod-memory", "Pod memory (bytes)", "kubernetes.pod.memory.usage.bytes",
               "event.module : kubernetes and metricset.name : pod", operation="avg"),
        metric("jk-container-restarts", "Container restart observations",
               "kubernetes.container.status.restarts",
               "event.module : kubernetes and metricset.name : container", operation="max"),
        histogram("jk-container-cpu-over-time", "Container CPU use over time",
                  "kubernetes.container.cpu.usage.nanocores",
                  "event.module : kubernetes and metricset.name : container"),
        histogram("jk-container-memory-over-time", "Container memory use over time",
                  "kubernetes.container.memory.usage.bytes",
                  "event.module : kubernetes and metricset.name : container"),
        table("jk-pod-phase", "Pods by phase", "kubernetes.pod.status.phase",
              "event.module : kubernetes and metricset.name : state_pod",
              "Pod phase inventory from kube-state-metrics."),
        table("jk-deployments", "Deployment observations", "kubernetes.deployment.name",
              "event.module : kubernetes and metricset.name : state_deployment",
              "Deployment state observations from kube-state-metrics."),
        metric("jk-jenkins-up", "Jenkins health (1=up)", "prometheus.metrics.default_jenkins_up",
               jenkins, "Requires the Jenkins Prometheus plugin and reachable /prometheus/ endpoint."),
        metric("jk-jenkins-uptime", "Jenkins uptime (seconds)",
               "prometheus.metrics.default_jenkins_uptime", jenkins, operation="max"),
        metric("jk-jenkins-queue", "Build queue length",
               "prometheus.metrics.default_jenkins_executors_queue_length", jenkins, operation="max"),
        metric("jk-jenkins-executors-busy", "Busy executors",
               "prometheus.metrics.default_jenkins_executors_busy", jenkins, operation="max"),
        metric("jk-jenkins-executors-idle", "Idle executors",
               "prometheus.metrics.default_jenkins_executors_idle", jenkins, operation="max"),
        metric("jk-jenkins-executors-connecting", "Executors connecting",
               "prometheus.metrics.default_jenkins_executors_connecting", jenkins, operation="max",
               description="Agent provisioning signal exposed by Jenkins; not cloud-provider provisioning latency."),
        metric("jk-jenkins-nodes-online", "Jenkins agents online",
               "prometheus.metrics.default_jenkins_nodes_online", jenkins, operation="max"),
        histogram("jk-jenkins-running-builds", "Running build duration over time",
                  "prometheus.metrics.default_jenkins_builds_running_build_duration_milliseconds",
                  jenkins, "Prometheus scrape of the Jenkins Prometheus plugin.", "max"),
        metric("jk-jenkins-builds-success", "Successful builds (counter)",
               "prometheus.metrics.default_jenkins_builds_success_build_count", jenkins,
               "Cumulative counter snapshot; use rate/delta analysis for a per-time-window rate."),
        metric("jk-jenkins-builds-failed", "Failed builds (counter)",
               "prometheus.metrics.default_jenkins_builds_failed_build_count", jenkins,
               "Cumulative counter snapshot; use rate/delta analysis for a per-time-window rate."),
        metric("jk-jenkins-builds-total", "Total builds (counter)",
               "prometheus.metrics.default_jenkins_builds_total_build_count", jenkins,
               "Cumulative counter snapshot; use rate/delta analysis for a per-time-window rate."),
        metric("jk-jenkins-builds-unstable", "Unstable builds (counter)",
               "prometheus.metrics.default_jenkins_builds_unstable_build_count", jenkins,
               "Cumulative counter snapshot; use rate/delta analysis for a per-time-window rate."),
        metric("jk-jenkins-build-duration", "Last build duration (ms)",
               "prometheus.metrics.default_jenkins_builds_last_build_duration_milliseconds", jenkins,
               "Latest build duration reported by the Jenkins Prometheus plugin."),
        metric("jk-jenkins-stage-duration", "Stage duration total (ms)",
               "prometheus.metrics.default_jenkins_builds_last_stage_duration_milliseconds_summary_sum", jenkins,
               "Last-build stage summary from the Jenkins Prometheus plugin."),
    ])

    OBJECTS_BY_ID.update({obj["id"]: obj for obj in objects})
    rows = [
        [("jk-node-cpu", 16, 7), ("jk-node-memory", 16, 7), ("jk-node-ready", 16, 7)],
        [("jk-node-cpu-over-time", 24, 14), ("jk-node-memory-over-time", 24, 14)],
        [("jk-node-table", 48, 12)],
        [("jk-pod-cpu", 16, 7), ("jk-pod-memory", 16, 7), ("jk-container-restarts", 16, 7)],
        [("jk-container-cpu-over-time", 24, 14), ("jk-container-memory-over-time", 24, 14)],
        [("jk-pod-phase", 24, 12), ("jk-deployments", 24, 12)],
        [("jk-kubernetes-events", 48, 16)],
        [("jk-jenkins-up", 16, 7), ("jk-jenkins-uptime", 16, 7), ("jk-jenkins-queue", 16, 7)],
        [("jk-jenkins-executors-busy", 12, 7), ("jk-jenkins-executors-idle", 12, 7),
         ("jk-jenkins-executors-connecting", 12, 7), ("jk-jenkins-nodes-online", 12, 7)],
        [("jk-jenkins-running-builds", 24, 14), ("jk-jenkins-build-duration", 24, 8)],
        [("jk-jenkins-builds-success", 12, 7), ("jk-jenkins-builds-failed", 12, 7),
         ("jk-jenkins-builds-total", 12, 7), ("jk-jenkins-builds-unstable", 12, 7)],
        [("jk-jenkins-stage-duration", 24, 8), ("jk-jenkins-build-duration", 24, 8)],
        [("jk-jenkins-traces", 48, 16)],
        [("jk-kubernetes-controller-logs", 16, 16), ("jk-jenkins-controller-logs", 16, 16),
         ("jk-jenkins-agent-logs", 16, 16)],
    ]
    objects.append(dashboard(rows))
    return objects


OBJECTS_BY_ID = {}


def validate(objects):
    by_id = {}
    for obj in objects:
        key = (obj["type"], obj["id"])
        if key in by_id:
            raise ValueError(f"Duplicate saved object: {key}")
        by_id[key] = obj
        if obj["type"] == "visualization":
            json.loads(obj["attributes"]["visState"])
        if obj["type"] == "dashboard":
            panels = json.loads(obj["attributes"]["panelsJSON"])
            if len(panels) != len(obj["references"]):
                raise ValueError(f"Panel/reference count mismatch in {obj['id']}")
    for obj in objects:
        for ref in obj.get("references", []):
            if (ref["type"], ref["id"]) not in by_id:
                raise ValueError(f"{obj['id']} references missing {ref['type']} {ref['id']}")
    return by_id


def main():
    global OBJECTS_BY_ID
    objects = build()
    OBJECTS_BY_ID = validate(objects)
    dashboard_object = next(obj for obj in objects if obj["type"] == "dashboard")
    output_dir = Path(__file__).resolve().parent
    ndjson_path = output_dir / "jenkins-kubernetes.ndjson"
    json_path = output_dir / "jenkins-kubernetes-dashboard.json"
    ndjson_path.write_text(
        "".join(json.dumps(obj, separators=(",", ":")) + "\n" for obj in objects),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps({
            "description": "Complete Kibana saved-object bundle; import the matching .ndjson file.",
            "objects": objects,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {ndjson_path}")
    print(f"wrote {json_path}")
    print(f"saved objects: {len(objects)}; dashboard panels: {len(json.loads(dashboard_object['attributes']['panelsJSON']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
