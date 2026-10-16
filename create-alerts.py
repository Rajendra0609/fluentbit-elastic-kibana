#!/usr/bin/env python3
"""Creates or updates Kibana alert rules on the k8s-logs-* indices.

Rules are updated in place, so re-running this script does not create duplicates or
delete existing rules before an update succeeds. Matches are written to the Kibana
server log by the built-in Server log connector (ID .server-log). Read them with:
    kubectl -n logging logs deploy/kibana | grep "Elasticsearch query rule"

To send alerts to email or Slack, create a connector in Stack Management -> Connectors
and set KIBANA_ALERT_CONNECTOR_ID to its ID.

Environment:
    KIBANA_URL         default http://localhost:5601 (kubectl -n logging port-forward svc/kibana 5601:5601)
    ELASTIC_PASSWORD   default: read from the logging-credentials Secret with kubectl
    KIBANA_ALERT_CONNECTOR_ID  default .server-log
    K8S_LOG_INDEX      default k8s-logs-*
    K8S_ERROR_THRESHOLD       default 50 errors per window
    K8S_WARNING_THRESHOLD    default 200 warnings per window
    K8S_ALERT_INTERVAL        default 1m
"""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

KIBANA = os.environ.get("KIBANA_URL", "http://localhost:5601").rstrip("/")
CONNECTOR_ID = os.environ.get("KIBANA_ALERT_CONNECTOR_ID", ".server-log")
INDEX = [os.environ.get("K8S_LOG_INDEX", "k8s-logs-*")]
ALERT_INTERVAL = os.environ.get("K8S_ALERT_INTERVAL", "1m")

ERRORS = ["error", "ERROR", "fatal", "FATAL", "critical", "CRITICAL"]
WARNINGS = ["warn", "WARN", "warning", "WARNING"]

MESSAGE = (
    "Kubernetes log alert '{{rule.name}}' is active. Value: {{context.value}}. "
    "Conditions: {{context.conditions}}. Window: {{rule.params.timeWindowSize}}"
    "{{rule.params.timeWindowUnit}}. Time: {{context.date}}. Link: {{context.link}}"
)

# For DSL queries Kibana applies the time window (timeWindowSize over timeField) itself,
# so these queries contain no time range.
RULES = [
    {
        "id": "k8slog-error-spike",
        "name": "K8s logs: error spike",
        "description": "More error lines than the threshold in the window, grouped by namespace.",
        "window_minutes": 5,
        "comparator": ">",
        "threshold_env": "K8S_ERROR_THRESHOLD",
        "default_threshold": 50,
        "group_by": "top",
        "term_field": "kubernetes.namespace_name",
        "term_size": 10,
        "query": {"query": {"bool": {"filter": [{"terms": {"level": ERRORS}}]}}},
    },
    {
        "id": "k8slog-warning-spike",
        "name": "K8s logs: warning spike",
        "description": "More warning lines than the threshold in the window, grouped by namespace.",
        "window_minutes": 10,
        "comparator": ">",
        "threshold_env": "K8S_WARNING_THRESHOLD",
        "default_threshold": 200,
        "group_by": "top",
        "term_field": "kubernetes.namespace_name",
        "term_size": 10,
        "query": {"query": {"bool": {"filter": [{"terms": {"level": WARNINGS}}]}}},
    },
    {
        "id": "k8slog-pipeline-silent",
        "name": "K8s logs: no logs ingested",
        "description": "No log lines at all in the window. The pipeline, or every source, has stopped.",
        "window_minutes": 10,
        "comparator": "<",
        "threshold_env": None,
        "default_threshold": 1,
        "group_by": "all",
        "term_field": None,
        "term_size": 5,
        "query": {"query": {"match_all": {}}},
    },
    {
        "id": "k8slog-logging-stack-errors",
        "name": "Logging stack: errors",
        "description": "Error logs emitted from workloads in the logging namespace.",
        "window_minutes": 5,
        "comparator": ">",
        "threshold_env": None,
        "default_threshold": 0,
        "group_by": "top",
        "term_field": "kubernetes.pod_name",
        "term_size": 10,
        "query": {"query": {"bool": {"filter": [
            {"term": {"kubernetes.namespace_name": "logging"}},
            {"terms": {"level": ERRORS}},
        ]}}},
    },
    {
        "id": "k8slog-control-plane-errors",
        "name": "Kubernetes control plane: errors",
        "description": "Error logs from workloads in kube-system.",
        "window_minutes": 5,
        "comparator": ">",
        "threshold_env": None,
        "default_threshold": 0,
        "group_by": "top",
        "term_field": "kubernetes.pod_name",
        "term_size": 10,
        "query": {"query": {"bool": {"filter": [
            {"term": {"kubernetes.namespace_name": "kube-system"}},
            {"terms": {"level": ERRORS}},
        ]}}},
    },
]


def elastic_password():
    if os.environ.get("ELASTIC_PASSWORD"):
        return os.environ["ELASTIC_PASSWORD"]
    encoded = subprocess.run(
        ["kubectl", "-n", "logging", "get", "secret", "logging-credentials",
         "-o", "jsonpath={.data.ELASTIC_PASSWORD}"],
        check=True, capture_output=True, text=True,
    ).stdout
    return base64.b64decode(encoded).decode()


AUTH = "Basic " + base64.b64encode(f"elastic:{elastic_password()}".encode()).decode()


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        KIBANA + path, data=data, method=method,
        headers={"kbn-xsrf": "true", "Content-Type": "application/json", "Authorization": AUTH},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def rule_body(rule):
    threshold_env = rule["threshold_env"]
    threshold = rule["default_threshold"]
    if threshold_env:
        threshold = int(os.environ.get(threshold_env, threshold))
    params = {
        "searchType": "esQuery",
        "timeWindowSize": rule["window_minutes"],
        "timeWindowUnit": "m",
        "threshold": [threshold],
        "thresholdComparator": rule["comparator"],
        "size": 100,
        "esQuery": json.dumps(rule["query"]),
        "aggType": "count",
        "groupBy": rule["group_by"],
        "termSize": rule["term_size"],
        "excludeHitsFromPreviousRun": False,
        "sourceFields": [],
        "index": INDEX,
        "timeField": "@timestamp",
    }
    if rule["term_field"]:
        params["termField"] = rule["term_field"]
    return {
        "name": rule["name"],
        "rule_type_id": ".es-query",
        "consumer": "stackAlerts",
        "schedule": {"interval": ALERT_INTERVAL},
        "tags": ["k8s-logs", "kubernetes", "home-lab"],
        "enabled": True,
        "params": params,
        "actions": [{
            "group": "query matched",
            "id": CONNECTOR_ID,
            "params": {"level": "warn", "message": MESSAGE},
            "frequency": {"notify_when": "onActionGroupChange", "throttle": None, "summary": False},
        }],
    }


def validate_configuration():
    for rule in RULES:
        threshold_env = rule["threshold_env"]
        if threshold_env and threshold_env in os.environ:
            try:
                value = int(os.environ[threshold_env])
            except ValueError as error:
                raise ValueError(f"{threshold_env} must be an integer") from error
            if value < 1:
                raise ValueError(f"{threshold_env} must be greater than zero")
    if not ALERT_INTERVAL:
        raise ValueError("K8S_ALERT_INTERVAL must not be empty")
    if not INDEX[0]:
        raise ValueError("K8S_LOG_INDEX must not be empty")


def upsert_rule(rule):
    rule_path = f"/api/alerting/rule/{rule['id']}"
    status, existing = call("GET", rule_path)
    if status == 404:
        status, body = call("POST", rule_path, rule_body(rule))
        operation = "created"
    elif status == 200:
        status, body = call("PUT", rule_path, rule_body(rule))
        operation = "updated"
    else:
        return status, existing, "checked"
    return status, body, operation


def main():
    try:
        validate_configuration()
    except ValueError as error:
        print(f"Invalid alert configuration: {error}", file=sys.stderr)
        return 2

    status, connectors = call("GET", "/api/actions/connectors")
    if status != 200:
        print(f"Could not list connectors (HTTP {status}): {connectors}", file=sys.stderr)
        return 1
    known = {connector["id"] for connector in connectors}
    if CONNECTOR_ID not in known:
        print(f"Connector {CONNECTOR_ID!r} not found. Create a Server log connector in Stack Management -> "
              "Connectors, then set CONNECTOR_ID in this script to its ID.", file=sys.stderr)
        return 1

    failures = 0
    for rule in RULES:
        status, body, operation = upsert_rule(rule)
        if status == 200:
            print(f"{operation:8s} {rule['id']:34s} {rule['name']}")
        else:
            failures += 1
            print(f"FAILED   {rule['id']:34s} HTTP {status}: {body}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
