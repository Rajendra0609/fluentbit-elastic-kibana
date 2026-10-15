#!/usr/bin/env python3
"""Creates Kibana alert rules (Elasticsearch query rules) on the k8s-logs-* indices.

Each rule is deleted and recreated, so re-running this script applies any change you make
to RULES below. Matches are written to the Kibana server log by the built-in Server log
connector (ID .server-log). Read them with:
    kubectl -n logging logs deploy/kibana | grep "Elasticsearch query rule"

To send alerts to email or Slack instead, create that connector in Stack Management ->
Connectors, then add an action with its ID to the rule.

Environment:
    KIBANA_URL         default http://localhost:5601 (kubectl -n logging port-forward svc/kibana 5601:5601)
    ELASTIC_PASSWORD   default: read from the logging-credentials Secret with kubectl
"""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

KIBANA = os.environ.get("KIBANA_URL", "http://localhost:5601").rstrip("/")
CONNECTOR_ID = ".server-log"
INDEX = ["k8s-logs-*"]

ERRORS = ["error", "ERROR", "fatal", "FATAL", "critical", "CRITICAL"]
WARNINGS = ["warn", "WARN", "warning", "WARNING"]

# The message uses Kibana's rule variables, as shown in the Kibana rule UI.
MESSAGE = (
    "Elasticsearch query rule '{{rule.name}}' is active: - Value: {{context.value}} - "
    "Conditions Met: {{context.conditions}} over {{rule.params.timeWindowSize}}{{rule.params.timeWindowUnit}} - "
    "Timestamp: {{context.date}} - Link: {{context.link}}"
)

# For DSL queries Kibana applies the time window (timeWindowSize over timeField) itself,
# so these queries contain no time range.
RULES = [
    {
        "id": "k8slog-error-spike",
        "name": "K8s logs: error spike",
        "description": "More error lines than the threshold in the window, across all namespaces.",
        "window_minutes": 5,
        "comparator": ">",
        "threshold": 50,
        "query": {"query": {"bool": {"filter": [{"terms": {"level": ERRORS}}]}}},
    },
    {
        "id": "k8slog-warning-spike",
        "name": "K8s logs: warning spike",
        "description": "More warning lines than the threshold in the window.",
        "window_minutes": 10,
        "comparator": ">",
        "threshold": 200,
        "query": {"query": {"bool": {"filter": [{"terms": {"level": WARNINGS}}]}}},
    },
    {
        "id": "k8slog-pipeline-silent",
        "name": "K8s logs: no logs ingested",
        "description": "No log lines at all in the window. The pipeline, or every source, has stopped.",
        "window_minutes": 10,
        "comparator": "<",
        "threshold": 1,
        "query": {"query": {"match_all": {}}},
    },
    {
        "id": "k8slog-logging-stack-errors",
        "name": "Logging stack: errors",
        "description": "Any error line from the logging namespace (Elasticsearch, Kibana).",
        "window_minutes": 5,
        "comparator": ">",
        "threshold": 0,
        "query": {"query": {"bool": {"filter": [
            {"term": {"kubernetes.namespace_name": "logging"}},
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
    return {
        "name": rule["name"],
        "rule_type_id": ".es-query",
        "consumer": "stackAlerts",
        "schedule": {"interval": "1m"},
        "tags": ["k8s-logs", "home-lab"],
        "enabled": True,
        "params": {
            "searchType": "esQuery",
            "timeWindowSize": rule["window_minutes"],
            "timeWindowUnit": "m",
            "threshold": [rule["threshold"]],
            "thresholdComparator": rule["comparator"],
            "size": 100,
            "esQuery": json.dumps(rule["query"]),
            "aggType": "count",
            "groupBy": "all",
            "termSize": 5,
            "excludeHitsFromPreviousRun": False,
            "sourceFields": [],
            "index": INDEX,
            "timeField": "@timestamp",
        },
        "actions": [{
            "group": "query matched",
            "id": CONNECTOR_ID,
            "params": {"level": "warn", "message": MESSAGE},
            "frequency": {"notify_when": "onActionGroupChange", "throttle": None, "summary": False},
        }],
    }


def main():
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
        call("DELETE", f"/api/alerting/rule/{rule['id']}")  # 404 on first run is fine
        status, body = call("POST", f"/api/alerting/rule/{rule['id']}", rule_body(rule))
        if status == 200:
            print(f"created  {rule['id']:30s} {rule['name']}")
        else:
            failures += 1
            print(f"FAILED   {rule['id']:30s} HTTP {status}: {body}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
