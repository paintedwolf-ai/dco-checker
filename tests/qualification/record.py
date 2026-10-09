#!/usr/bin/env python3
"""Collect independently verifiable evidence from an actual consumer action run.

Uses the operator's gh login, never the action's runtime credentials. Read only.
"""
import argparse
import base64
import datetime
import json
from pathlib import Path
import re
import subprocess


def api(path):
    completed = subprocess.run(["gh", "api", path], capture_output=True, text=True,
                               check=True, timeout=60)
    return json.loads(completed.stdout)


def verify(run, jobs, checks, *, repository, run_id, head, conclusion, app_id, action_sha=None):
    errors = []
    if run.get("id") != run_id or run.get("repository", {}).get("full_name") != repository:
        errors.append("workflow run identity does not match requested consumer")
    if run.get("status") != "completed":
        errors.append("workflow run is not complete")
    if not any(any("Certify" in step.get("name", "") for step in job.get("steps", []))
               for job in jobs):
        errors.append("no composite certification step appears in recorded jobs")
    run_url = run.get("html_url")
    candidates = [check for check in checks if check.get("name") == "DCO-owned"
                  and check.get("head_sha") == head and check.get("details_url") == run_url]
    if not candidates:
        errors.append("no DCO-owned check belongs to this exact run and target head")
    for check in candidates:
        if check.get("status") != "completed" or check.get("conclusion") != conclusion:
            errors.append("published check has unexpected terminal outcome")
        if check.get("app", {}).get("id") != app_id:
            errors.append("published check has unexpected GitHub App identity")
        if not check.get("external_id"):
            errors.append("published check lacks certification evidence identity")
        output = check.get("output", {})
        if not output.get("summary"):
            errors.append("published check lacks an audit summary")
        elif action_sha is not None and f"checker: `{action_sha}`" not in output["summary"]:
            errors.append("published evidence does not identify the requested action revision")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--expected-conclusion", choices=["success", "failure", "cancelled"], required=True)
    parser.add_argument("--app-id", type=int, default=15368)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--action-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("repository must be owner/name")
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (args.head, args.action_sha)):
        parser.error("head and action-sha must be full immutable SHAs")
    prefix = f"repos/{args.repository}"
    run = api(f"{prefix}/actions/runs/{args.run_id}")
    jobs = []
    checks = []
    for path, key, target in [(f"actions/runs/{args.run_id}/jobs", "jobs", jobs),
                              (f"commits/{args.head}/check-runs", "check_runs", checks)]:
        page = 1
        while True:
            batch = api(f"{prefix}/{path}?per_page=100&page={page}")[key]
            target.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    workflow = api(f"{prefix}/contents/.github/workflows/dco.yml?ref={run['head_sha']}")
    source = base64.b64decode(workflow["content"]).decode("utf-8")
    errors = verify(run, jobs, checks, repository=args.repository, run_id=args.run_id,
                    head=args.head, conclusion=args.expected_conclusion, app_id=args.app_id, action_sha=args.action_sha)
    if f"paintedwolf-ai/dco-checker@{args.action_sha}" not in source:
        errors.append("immutable caller workflow does not pin the requested action revision")
    document = {"schema_version": 1, "qualification_kind": "hosted-token-bearing",
                "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "scenario": args.scenario, "action_sha": args.action_sha,
                "target_head": args.head, "expected_conclusion": args.expected_conclusion,
                "run": run, "jobs": jobs, "checks": checks, "caller_workflow": {"ref": run["head_sha"], "blob_sha": workflow["sha"], "source": source}, "errors": errors,
                "limitations": ["this record does not demonstrate required-check ruleset enforcement"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n")
    print("; ".join(errors) if errors else f"Qualified {args.scenario}: {run['html_url']}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
