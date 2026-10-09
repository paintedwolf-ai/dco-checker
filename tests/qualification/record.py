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
                  and check.get("head_sha") == head
                  and str(check.get("external_id", "")).startswith(f"dco:v2:{run_id}:{run.get('run_attempt', 1)}:")]
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
    parser.add_argument("--allow-legacy-missing-run-link", action="store_true", help="Candidate-only evidence for the pre-link implementation; never use for release qualification")
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
            query = f"per_page=100&page={page}" + ("&filter=all" if key == "check_runs" else "")
            batch = api(f"{prefix}/{path}?{query}")[key]
            target.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    workflow = api(f"{prefix}/contents/.github/workflows/dco.yml?ref={run['head_sha']}")
    source = base64.b64decode(workflow["content"]).decode("utf-8")
    errors = verify(run, jobs, checks, repository=args.repository, run_id=args.run_id,
                    head=args.head, conclusion=args.expected_conclusion, app_id=args.app_id, action_sha=args.action_sha)
    logs = subprocess.run(["gh", "run", "view", str(args.run_id), "--repo", args.repository, "--log"],
                          capture_output=True, text=True, check=True, timeout=60).stdout
    if f"Download action repository 'paintedwolf-ai/dco-checker@{args.action_sha}' (SHA:{args.action_sha})" not in logs:
        errors.append("runner logs do not attest downloading the requested immutable action SHA")
    identified = [check for check in checks if str(check.get("external_id", "")).startswith(f"dco:v2:{args.run_id}:{run.get('run_attempt', 1)}:")]
    if not args.allow_legacy_missing_run_link and any(run["html_url"] not in check.get("output", {}).get("summary", "") for check in identified):
        errors.append("published summary lacks the explicit certification workflow run link")
    if not args.allow_legacy_missing_run_link:
        for check in identified:
            try:
                text = check["output"]["text"]
                if not text.startswith("```json\n") or not text.endswith("\n```"):
                    raise ValueError("not fenced JSON")
                provenance = json.loads(text[8:-4])
                expected = {"run_url": run["html_url"], "run_id": args.run_id,
                            "attempt": run.get("run_attempt", 1), "external_id": check["external_id"],
                            "checker_revision": args.action_sha, "policy_version": "2",
                            "evidence_digest": check["external_id"].rsplit(":", 1)[-1]}
                if any(str(provenance.get(key)) != str(value) for key, value in expected.items()):
                    errors.append("published execution provenance differs from the recorded action/run/evidence")
            except (KeyError, TypeError, ValueError):
                errors.append("published check lacks valid structured execution provenance")
    if f"paintedwolf-ai/dco-checker@{args.action_sha}" not in source:
        errors.append("immutable caller workflow does not pin the requested action revision")
    document = {"schema_version": 1, "qualification_kind": "hosted-token-bearing",
                "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "scenario": args.scenario, "action_sha": args.action_sha,
                "target_head": args.head, "expected_conclusion": args.expected_conclusion,
                "release_eligible": not args.allow_legacy_missing_run_link and not errors,
                "legacy_missing_run_link_allowed": args.allow_legacy_missing_run_link,
                "runner_logs": logs, "run": run, "jobs": jobs, "checks": checks, "caller_workflow": {"ref": run["head_sha"], "blob_sha": workflow["sha"], "source": source}, "errors": errors,
                "limitations": ["this record does not demonstrate required-check ruleset enforcement"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n")
    print("; ".join(errors) if errors else f"Qualified {args.scenario}: {run['html_url']}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
