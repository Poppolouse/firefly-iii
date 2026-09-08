#!/usr/bin/env python3
"""Apply a reviewed Sure-to-Firefly API plan to an initially empty Firefly user.

No HTTP request is made unless `--apply` is supplied. Read the generated plan,
back up the target, and verify its `manual_review` list before invoking this.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


RESOURCE_NAME_FIELDS = {
    "/api/v1/accounts": "name",
    "/api/v1/categories": "name",
    "/api/v1/tags": "tag",
    "/api/v1/budgets": "name",
}


def load_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("format") != "sure-to-firefly-api-plan/v1":
        raise ValueError("Unsupported migration plan format")
    if plan.get("manual_review"):
        raise ValueError("Plan has manual_review items; resolve or explicitly remove them before applying")
    return plan


def request_json(base_url: str, token: str, method: str, endpoint: str, payload: dict | None = None) -> tuple[int, dict]:
    url = urljoin(f"{base_url.rstrip('/')}/", endpoint.lstrip("/"))
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method=method, headers={
        "Accept": "application/vnd.api+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        response = error.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            data = {"error": "non-JSON response"}
        return error.code, data
    except URLError as error:
        raise RuntimeError(f"Could not reach Firefly at {base_url}: {error.reason}") from error


def existing_names(base_url: str, token: str, endpoint: str, field: str) -> set[str]:
    names: set[str] = set()
    next_endpoint: str | None = endpoint
    while next_endpoint:
        status, response = request_json(base_url, token, "GET", next_endpoint)
        if status != 200:
            raise RuntimeError(f"Could not list existing resources at {endpoint} (HTTP {status})")
        for item in response.get("data", []):
            name = item.get("attributes", {}).get(field)
            if name:
                names.add(name)
        next_endpoint = response.get("links", {}).get("next")
    return names


def apply(plan: dict, base_url: str, token: str) -> dict:
    known_names = {endpoint: existing_names(base_url, token, endpoint, field) for endpoint, field in RESOURCE_NAME_FIELDS.items()}
    summary = {"created": 0, "skipped_existing": 0, "failed": 0}
    for operation in plan["operations"]:
        endpoint = operation["endpoint"]
        payload = operation["payload"]
        if endpoint in RESOURCE_NAME_FIELDS:
            name = payload[RESOURCE_NAME_FIELDS[endpoint]]
            if name in known_names[endpoint]:
                summary["skipped_existing"] += 1
                continue
        status, _ = request_json(base_url, token, operation["method"], endpoint, payload)
        if status not in (200, 201):
            summary["failed"] += 1
            raise RuntimeError(f"Migration stopped at {endpoint} with HTTP {status}; no later operations were attempted")
        if endpoint in RESOURCE_NAME_FIELDS:
            known_names[endpoint].add(payload[RESOURCE_NAME_FIELDS[endpoint]])
        summary["created"] += 1
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--url", default="http://localhost:8088")
    parser.add_argument("--apply", action="store_true", help="Permit writes to Firefly III.")
    args = parser.parse_args()
    plan = load_plan(args.plan)
    if not args.apply:
        print(json.dumps({"dry_run": True, "operations": len(plan["operations"]), "manual_review": len(plan["manual_review"])}))
        return
    token = os.environ.get("FIREFLY_ACCESS_TOKEN")
    if not token:
        raise SystemExit("FIREFLY_ACCESS_TOKEN must be set only in your shell before --apply")
    print(json.dumps(apply(plan, args.url, token)))


if __name__ == "__main__":
    main()
