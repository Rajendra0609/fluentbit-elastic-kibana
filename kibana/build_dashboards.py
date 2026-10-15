#!/usr/bin/env python3
"""Generates dashboards.ndjson: the data view, saved searches, visualizations and
dashboards for the k8s-logs-* indices written by Fluentd.

Run:   python3 build_dashboards.py          (writes dashboards.ndjson next to this file)
Then:  ./import-dashboards.sh

Every object has a fixed ID. Importing with overwrite updates the objects in place,
so you can edit this file and re-import without creating duplicates.

Visualizations use the Aggregation-based editor. Its saved-object format is stable and
still supported in Kibana 9.x. Lens is the recommended editor, and Kibana offers to
convert these panels to Lens from edit mode.
"""
import json
import os
import sys

KIBANA_VERSION = "9.5.5"
INDEX_ID = "k8s-logs"
INDEX_TITLE = "k8s-logs-*"
TIME_FIELD = "@timestamp"
REF_NAME = "kibanaSavedObjectMeta.searchSourceJSON.index"

# Severity queries. level is a keyword field (see the index template in 20-es-setup-job.yaml),
# so values must match exactly. The variants cover the casing used by common logging libraries.
ERROR_Q = "level:(error or ERROR or fatal or FATAL or critical or CRITICAL)"
WARN_Q = "level:(warn or WARN or warning or WARNING)"
ISSUE_Q = f"({ERROR_Q}) or ({WARN_Q})"
LOGGING_Q = 'kubernetes.namespace_name:"logging"'

SEARCH_COLUMNS = [
    "kubernetes.namespace_name",
    "kubernetes.pod_name",
    "kubernetes.container_name",
    "level",
    "stream",
    "msg",
    "log",
]

# ---------------------------------------------------------------------------
# Object builders
# ---------------------------------------------------------------------------

def search_source(query=""):
    return json.dumps({
        "query": {"query": query, "language": "kuery"},
        "filter": [],
        "indexRefName": REF_NAME,
    })


def index_ref():
    return [{"name": REF_NAME, "type": "index-pattern", "id": INDEX_ID}]


def data_view():
    return {
        "id": INDEX_ID,
        "type": "index-pattern",
        "attributes": {"title": INDEX_TITLE, "timeFieldName": TIME_FIELD},
        "references": [],
    }


def saved_search(obj_id, title, query, description=""):
    return {
        "id": obj_id,
        "type": "search",
        "attributes": {
            "title": title,
            "description": description,
            "columns": SEARCH_COLUMNS,
            "sort": [[TIME_FIELD, "desc"]],
            "version": 1,
            "kibanaSavedObjectMeta": {"searchSourceJSON": search_source(query)},
        },
        "references": index_ref(),
    }


def saved_vis(obj_id, title, vis_type, aggs, params, query="", description=""):
    vis_state = {"title": title, "type": vis_type, "aggs": aggs, "params": params}
    return {
        "id": obj_id,
        "type": "visualization",
        "attributes": {
            "title": title,
            "description": description,
            "visState": json.dumps(vis_state),
            "uiStateJSON": "{}",
            "version": 1,
            "kibanaSavedObjectMeta": {"searchSourceJSON": search_source(query)},
        },
        "references": index_ref(),
    }


# Aggregation builders. Schema names tell the editor where each aggregation goes:
#   metric = y-axis or number, segment = x-axis, group = series, bucket = table row.

def agg_count(agg_id="1"):
    return {"id": agg_id, "enabled": True, "type": "count", "params": {}, "schema": "metric"}


def agg_date_histogram(agg_id, interval="auto", schema="segment"):
    return {
        "id": agg_id,
        "enabled": True,
        "type": "date_histogram",
        "params": {
            "field": TIME_FIELD,
            "useNormalizedEsInterval": True,
            "scaleMetricValues": False,
            "interval": interval,
            "drop_partials": False,
            "min_doc_count": 1,
            "extended_bounds": {},
        },
        "schema": schema,
    }


def agg_terms(agg_id, field, size, schema, order_by="1"):
    return {
        "id": agg_id,
        "enabled": True,
        "type": "terms",
        "params": {
            "field": field,
            "orderBy": order_by,
            "order": "desc",
            "size": size,
            "otherBucket": False,
            "otherBucketLabel": "Other",
            "missingBucket": False,
            "missingBucketLabel": "Missing",
        },
        "schema": schema,
    }


def agg_field_metric(agg_id, agg_type, field):
    """cardinality, max, min: metrics that take a field."""
    return {"id": agg_id, "enabled": True, "type": agg_type, "params": {"field": field}, "schema": "metric"}


HISTOGRAM_PARAMS_TEMPLATE = {
    "type": "histogram",
    "grid": {"categoryLines": False, "valueAxis": "ValueAxis-1"},
    "categoryAxes": [{
        "id": "CategoryAxis-1", "type": "category", "position": "bottom", "show": True,
        "style": {}, "scale": {"type": "linear"},
        "labels": {"show": True, "filter": True, "truncate": 100}, "title": {},
    }],
    "valueAxes": [{
        "id": "ValueAxis-1", "name": "LeftAxis-1", "type": "value", "position": "left", "show": True,
        "style": {}, "scale": {"type": "linear", "mode": "normal"},
        "labels": {"show": True, "rotate": 0, "filter": False, "truncate": 100},
        "title": {"text": "Count"},
    }],
    "addTooltip": True,
    "addLegend": True,
    "legendPosition": "right",
    "times": [],
    "addTimeMarker": False,
    "labels": {"show": False},
    "thresholdLine": {"show": False, "value": 10, "width": 1, "style": "full", "color": "#E7664C"},
}


def histogram_params(mode):
    params = json.loads(json.dumps(HISTOGRAM_PARAMS_TEMPLATE))
    params["seriesParams"] = [{
        "show": True, "type": "histogram", "mode": mode,
        "data": {"label": "Count", "id": "1"}, "valueAxis": "ValueAxis-1",
        "drawLinesBetweenPoints": True, "lineWidth": 2, "showCircles": True,
    }]
    return params


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
        "style": {"bgFill": "#000", "bgColor": False, "labelColor": False, "subText": "", "fontSize": 60},
    },
}


def table_params(per_page=10):
    return {
        "perPage": per_page,
        "showPartialRows": False,
        "showMetricsAtAllLevels": False,
        "sort": {"columnIndex": None, "direction": None},
        "showTotal": False,
        "totalFunc": "sum",
        "percentageCol": "",
    }


PIE_PARAMS = {
    "type": "pie",
    "addTooltip": True,
    "addLegend": True,
    "legendPosition": "right",
    "isDonut": True,
    "labels": {"show": True, "values": True, "last_level": True, "truncate": 100},
}

# ---------------------------------------------------------------------------
# Visualization helpers: each returns one saved object.
# ---------------------------------------------------------------------------

def histogram(obj_id, title, query="", split=None, size=10, interval="auto", description=""):
    aggs = [agg_count("1"), agg_date_histogram("2", interval)]
    mode = "normal"
    if split:
        aggs.append(agg_terms("3", split, size, "group"))
        mode = "stacked"
    return saved_vis(obj_id, title, "histogram", aggs, histogram_params(mode), query, description)


def metric(obj_id, title, query="", agg="count", field=None, description=""):
    aggs = [agg_count("1")] if agg == "count" else [agg_field_metric("1", agg, field)]
    return saved_vis(obj_id, title, "metric", aggs, METRIC_PARAMS, query, description)


def table(obj_id, title, query="", buckets=(), extra_metrics=(), per_page=10, description=""):
    """buckets: (field, size) pairs, one table row level each.
    extra_metrics: (agg_type, field) pairs added as columns after the count."""
    aggs = [agg_count("1")]
    next_id = 2
    for field, size in buckets:
        aggs.append(agg_terms(str(next_id), field, size, "bucket"))
        next_id += 1
    for agg_type, field in extra_metrics:
        aggs.append(agg_field_metric(str(next_id), agg_type, field))
        next_id += 1
    return saved_vis(obj_id, title, "table", aggs, table_params(per_page), query, description)


def pie(obj_id, title, query="", field="", size=10, description=""):
    aggs = [agg_count("1"), agg_terms("2", field, size, "segment")]
    return saved_vis(obj_id, title, "pie", aggs, PIE_PARAMS, query, description)


# ---------------------------------------------------------------------------
# Dashboard builder. Panels flow left to right in rows on Kibana's 48-column grid.
# ---------------------------------------------------------------------------

def dashboard(obj_id, title, description, time_from, rows, refresh_ms=60000):
    """rows: list of rows. Each row is a list of (type, object_id, width, height).
    type is "visualization" or "search"."""
    panels, references = [], []
    y = 0
    n = 1
    for row in rows:
        x = 0
        for _, _, width, _ in row:
            if x + width > 48:
                raise ValueError(f"dashboard {obj_id}: row wider than 48 columns")
            x += width
        row_height = max(height for _, _, _, height in row)
        x = 0
        for kind, ref_id, width, height in row:
            ref_name = f"panel_{n - 1}"
            panels.append({
                "version": KIBANA_VERSION,
                "type": kind,
                "gridData": {"x": x, "y": y, "w": width, "h": height, "i": str(n)},
                "panelIndex": str(n),
                "embeddableConfig": {},
                "panelRefName": ref_name,
            })
            references.append({"name": ref_name, "type": kind, "id": ref_id})
            x += width
            n += 1
        y += row_height
    return {
        "id": obj_id,
        "type": "dashboard",
        "attributes": {
            "title": title,
            "description": description,
            "panelsJSON": json.dumps(panels),
            "optionsJSON": json.dumps({
                "useMargins": True, "syncColors": False, "syncCursor": True,
                "syncTooltips": False, "hidePanelTitles": False,
            }),
            "timeRestore": True,
            "timeFrom": time_from,
            "timeTo": "now",
            "refreshInterval": {"pause": False, "value": refresh_ms},
            "version": 1,
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []}),
            },
        },
        "references": references,
    }


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

def build():
    objects = [data_view()]

    # Saved searches (live feeds). Shown as panels on the dashboards below.
    objects += [
        saved_search("k8slog-search-issues", "K8s logs: errors and warnings (live)", ISSUE_Q,
                     "Every error and warning line, newest first."),
        saved_search("k8slog-search-stream", "K8s logs: live stream (all)", "",
                     "Every log line, newest first. Use the query bar to narrow it."),
        saved_search("k8slog-search-logging", "Logging stack: errors and warnings (live)",
                     f"({LOGGING_Q}) and ({ISSUE_Q})",
                     "Problems in Elasticsearch, Kibana and the other logging-namespace workloads."),
    ]

    # ---- Cluster overview -------------------------------------------------
    objects += [
        metric("k8slog-vis-total-lines", "Log lines"),
        metric("k8slog-vis-error-lines", "Error lines", ERROR_Q),
        metric("k8slog-vis-warn-lines", "Warning lines", WARN_Q),
        metric("k8slog-vis-active-pods", "Active pods", agg="cardinality", field="kubernetes.pod_name"),
        metric("k8slog-vis-active-namespaces", "Active namespaces", agg="cardinality",
               field="kubernetes.namespace_name"),
        metric("k8slog-vis-nodes", "Nodes reporting", agg="cardinality", field="kubernetes.host"),
        histogram("k8slog-vis-volume-by-namespace", "Log volume by namespace",
                  split="kubernetes.namespace_name", size=10,
                  description="Stacked bars: how many lines each namespace wrote per interval."),
        pie("k8slog-vis-share-by-namespace", "Share of log volume by namespace",
            field="kubernetes.namespace_name", size=10),
        histogram("k8slog-vis-issues-over-time", "Errors and warnings over time",
                  query=ISSUE_Q, split="level", size=5,
                  description="Stacked by the exact level value, so you can see which levels dominate."),
        table("k8slog-vis-namespace-table", "Namespaces: volume and active pods",
              buckets=[("kubernetes.namespace_name", 50)],
              extra_metrics=[("cardinality", "kubernetes.pod_name")], per_page=15),
        table("k8slog-vis-node-table", "Nodes: volume and active pods",
              buckets=[("kubernetes.host", 20)],
              extra_metrics=[("cardinality", "kubernetes.pod_name")]),
        table("k8slog-vis-container-table", "Containers by volume",
              buckets=[("kubernetes.namespace_name", 20), ("kubernetes.container_name", 10)], per_page=15),
    ]

    # ---- Errors and warnings ---------------------------------------------
    objects += [
        metric("k8slog-vis-err-count", "Errors", ERROR_Q),
        metric("k8slog-vis-warn-count", "Warnings", WARN_Q),
        metric("k8slog-vis-stderr-count", "Lines on stderr", "stream:stderr"),
        metric("k8slog-vis-err-pods", "Pods with errors", ERROR_Q, agg="cardinality",
               field="kubernetes.pod_name"),
        histogram("k8slog-vis-errors-by-ns", "Errors over time by namespace", query=ERROR_Q,
                  split="kubernetes.namespace_name", size=10),
        histogram("k8slog-vis-warns-by-ns", "Warnings over time by namespace", query=WARN_Q,
                  split="kubernetes.namespace_name", size=10),
        table("k8slog-vis-top-error-pods", "Top pods by errors", query=ERROR_Q,
              buckets=[("kubernetes.pod_name", 25)], per_page=25),
        table("k8slog-vis-top-warn-pods", "Top pods by warnings", query=WARN_Q,
              buckets=[("kubernetes.pod_name", 25)], per_page=25),
        table("k8slog-vis-top-error-messages", "Most frequent error messages", query=ERROR_Q,
              buckets=[("msg.keyword", 25)], per_page=25,
              description="Groups identical msg values. Messages longer than 256 characters are not counted."),
        table("k8slog-vis-errors-by-container", "Errors by namespace and container", query=ERROR_Q,
              buckets=[("kubernetes.namespace_name", 20), ("kubernetes.container_name", 5)], per_page=20),
    ]

    # ---- Pod and container drill-down -------------------------------------
    objects += [
        metric("k8slog-vis-drill-lines", "Lines (current filter)"),
        metric("k8slog-vis-drill-errors", "Errors (current filter)", ERROR_Q),
        metric("k8slog-vis-drill-warns", "Warnings (current filter)", WARN_Q),
        metric("k8slog-vis-drill-pods", "Pods (current filter)", agg="cardinality",
               field="kubernetes.pod_name"),
        histogram("k8slog-vis-drill-pod-volume", "Volume per pod over time",
                  split="kubernetes.pod_name", size=10),
        histogram("k8slog-vis-drill-container-volume", "Volume per container over time",
                  split="kubernetes.container_name", size=10),
        table("k8slog-vis-drill-pods-table", "Pods by volume",
              buckets=[("kubernetes.pod_name", 50)], per_page=15),
        table("k8slog-vis-drill-containers-table", "Containers by volume",
              buckets=[("kubernetes.namespace_name", 20), ("kubernetes.container_name", 10)], per_page=15),
        pie("k8slog-vis-drill-stream", "stdout vs stderr", field="stream", size=5),
        table("k8slog-vis-drill-levels", "Levels", buckets=[("level", 20)], per_page=20),
    ]

    # ---- Pipeline health and freshness ------------------------------------
    objects += [
        metric("k8slog-vis-health-docs", "Documents in window"),
        metric("k8slog-vis-health-indices", "Indices in window", agg="cardinality", field="_index"),
        metric("k8slog-vis-health-newest", "Newest log", agg="max", field=TIME_FIELD),
        metric("k8slog-vis-health-oldest", "Oldest log in window", agg="min", field=TIME_FIELD),
        histogram("k8slog-vis-health-ingest-rate", "Ingest rate (lines per minute)", interval="1m",
                  description="A sudden drop means a pipeline or source problem."),
        histogram("k8slog-vis-health-errors-per-minute", "Errors per minute", query=ERROR_Q,
                  interval="1m"),
        table("k8slog-vis-health-last-seen-ns", "Last seen per namespace",
              buckets=[("kubernetes.namespace_name", 100)],
              extra_metrics=[("max", TIME_FIELD)], per_page=20,
              description="A namespace whose newest log is much older than now has gone silent."),
        table("k8slog-vis-health-last-seen-pod", "Last seen per pod",
              buckets=[("kubernetes.pod_name", 100)],
              extra_metrics=[("max", TIME_FIELD)], per_page=20),
        table("k8slog-vis-health-index-table", "Documents per index",
              buckets=[("_index", 30)], extra_metrics=[("max", TIME_FIELD)], per_page=15,
              description="Checks daily indices and retention. Old indices should disappear after 7 days."),
    ]

    # ---- Logging stack self-monitoring ------------------------------------
    objects += [
        metric("k8slog-vis-self-lines", "Logging-namespace lines", LOGGING_Q),
        metric("k8slog-vis-self-errors", "Logging-namespace errors", f"({LOGGING_Q}) and ({ERROR_Q})"),
        metric("k8slog-vis-self-warns", "Logging-namespace warnings", f"({LOGGING_Q}) and ({WARN_Q})"),
        histogram("k8slog-vis-self-volume", "Logging-namespace volume by pod", query=LOGGING_Q,
                  split="kubernetes.pod_name", size=10,
                  description="Fluentd does not appear here: its own logs are excluded to avoid a feedback loop."),
        histogram("k8slog-vis-self-issues", "Logging-namespace errors and warnings by pod",
                  query=f"({LOGGING_Q}) and ({ISSUE_Q})", split="kubernetes.pod_name", size=10),
        table("k8slog-vis-self-pod-table", "Logging-namespace pods", query=LOGGING_Q,
              buckets=[("kubernetes.pod_name", 20)], per_page=20),
        table("k8slog-vis-self-messages", "Most frequent logging-namespace problems",
              query=f"({LOGGING_Q}) and ({ISSUE_Q})", buckets=[("msg.keyword", 20)], per_page=20),
    ]

    # ---- Dashboards -------------------------------------------------------
    stat_row = lambda ids: [("visualization", i, 8, 6) for i in ids]  # six metrics, 8 columns each

    objects += [
        dashboard(
            "k8slog-dash-overview", "K8s Logs: Cluster Overview",
            "Start here. Volume, severity and where the logs come from, across the whole cluster.",
            "now-24h",
            [
                stat_row(["k8slog-vis-total-lines", "k8slog-vis-error-lines", "k8slog-vis-warn-lines",
                          "k8slog-vis-active-pods", "k8slog-vis-active-namespaces", "k8slog-vis-nodes"]),
                [("visualization", "k8slog-vis-volume-by-namespace", 32, 14),
                 ("visualization", "k8slog-vis-share-by-namespace", 16, 14)],
                [("visualization", "k8slog-vis-issues-over-time", 24, 14),
                 ("visualization", "k8slog-vis-namespace-table", 24, 14)],
                [("visualization", "k8slog-vis-node-table", 16, 12),
                 ("visualization", "k8slog-vis-container-table", 32, 12)],
                [("search", "k8slog-search-issues", 48, 16)],
            ],
        ),
        dashboard(
            "k8slog-dash-errors", "K8s Logs: Errors and Warnings",
            "Where errors and warnings come from, which pods produce them, and the most frequent messages.",
            "now-24h",
            [
                [("visualization", "k8slog-vis-err-count", 12, 6),
                 ("visualization", "k8slog-vis-warn-count", 12, 6),
                 ("visualization", "k8slog-vis-stderr-count", 12, 6),
                 ("visualization", "k8slog-vis-err-pods", 12, 6)],
                [("visualization", "k8slog-vis-errors-by-ns", 24, 14),
                 ("visualization", "k8slog-vis-warns-by-ns", 24, 14)],
                [("visualization", "k8slog-vis-top-error-pods", 24, 14),
                 ("visualization", "k8slog-vis-top-warn-pods", 24, 14)],
                [("visualization", "k8slog-vis-top-error-messages", 24, 14),
                 ("visualization", "k8slog-vis-errors-by-container", 24, 14)],
                [("search", "k8slog-search-issues", 48, 16)],
            ],
        ),
        dashboard(
            "k8slog-dash-drilldown", "K8s Logs: Pod and Container Drill-down",
            "Type a query in the bar at the top, for example: kubernetes.namespace_name : \"demo\" and "
            "kubernetes.pod_name : log-generator*. Every panel follows that query.",
            "now-1h",
            [
                [("visualization", "k8slog-vis-drill-lines", 12, 6),
                 ("visualization", "k8slog-vis-drill-errors", 12, 6),
                 ("visualization", "k8slog-vis-drill-warns", 12, 6),
                 ("visualization", "k8slog-vis-drill-pods", 12, 6)],
                [("visualization", "k8slog-vis-drill-pod-volume", 24, 14),
                 ("visualization", "k8slog-vis-drill-container-volume", 24, 14)],
                [("visualization", "k8slog-vis-drill-pods-table", 24, 14),
                 ("visualization", "k8slog-vis-drill-containers-table", 24, 14)],
                [("visualization", "k8slog-vis-drill-stream", 16, 14),
                 ("visualization", "k8slog-vis-drill-levels", 32, 14)],
                [("search", "k8slog-search-stream", 48, 18)],
            ],
            refresh_ms=30000,
        ),
        dashboard(
            "k8slog-dash-health", "K8s Logs: Pipeline Health and Freshness",
            "Is logging still working end to end? Ingest rate, silent sources and retention.",
            "now-6h",
            [
                [("visualization", "k8slog-vis-health-docs", 12, 6),
                 ("visualization", "k8slog-vis-health-indices", 12, 6),
                 ("visualization", "k8slog-vis-health-newest", 12, 6),
                 ("visualization", "k8slog-vis-health-oldest", 12, 6)],
                [("visualization", "k8slog-vis-health-ingest-rate", 48, 14)],
                [("visualization", "k8slog-vis-health-last-seen-ns", 24, 16),
                 ("visualization", "k8slog-vis-health-last-seen-pod", 24, 16)],
                [("visualization", "k8slog-vis-health-errors-per-minute", 24, 12),
                 ("visualization", "k8slog-vis-health-index-table", 24, 12)],
            ],
        ),
        dashboard(
            "k8slog-dash-logging-stack", "K8s Logs: Logging Stack Self-Monitoring",
            "Monitors the monitoring: Elasticsearch, Kibana and anything else in the logging namespace.",
            "now-24h",
            [
                [("visualization", "k8slog-vis-self-lines", 16, 6),
                 ("visualization", "k8slog-vis-self-errors", 16, 6),
                 ("visualization", "k8slog-vis-self-warns", 16, 6)],
                [("visualization", "k8slog-vis-self-volume", 24, 14),
                 ("visualization", "k8slog-vis-self-issues", 24, 14)],
                [("visualization", "k8slog-vis-self-pod-table", 24, 14),
                 ("visualization", "k8slog-vis-self-messages", 24, 14)],
                [("search", "k8slog-search-logging", 48, 16)],
            ],
        ),
    ]
    return objects


def validate(objects):
    ids = {}
    for obj in objects:
        key = (obj["type"], obj["id"])
        if key in ids:
            raise ValueError(f"duplicate object {key}")
        ids[key] = obj
    for obj in objects:
        for ref in obj.get("references", []):
            if (ref["type"], ref["id"]) not in ids:
                raise ValueError(f"{obj['id']} references missing {ref['type']} {ref['id']}")
        if obj["type"] == "visualization":
            json.loads(obj["attributes"]["visState"])  # must be valid JSON
    return ids


def main():
    objects = build()
    validate(objects)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards.ndjson")
    with open(out, "w", encoding="utf-8") as f:
        for obj in objects:
            f.write(json.dumps(obj, separators=(",", ":")) + "\n")
    counts = {}
    for obj in objects:
        counts[obj["type"]] = counts.get(obj["type"], 0) + 1
    print(f"wrote {out}")
    print("objects:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
